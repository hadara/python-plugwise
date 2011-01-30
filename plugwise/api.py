#!/bin/env python

# Copyright (C) 2011 Sven Petai <hadara@bsd.ee> 
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# 

# TODO:
#   - implement reading energy usage history from the buffer inside Circle
#   - make communication channel concurrency safe
#   - make circle-port combo singleton
#   - return more reasonable responses than response message objects from the functions that don't do so yet
#   - make message construction syntax better. Fields should only be specified once and contain name so we can serialize response message to dict
#   - verify response checksums
#   - look at the ACK messages
#   - unit tests
#   - python 3 support
#   - pairing
#   - switching schedule upload
#   - implement timeouts
#   - support for older firmware versions

import re
import sys
import time
import serial

from protocol import *
from exceptions import *
from util import *

# FIXME: rename args to same names as the underlying serial interface
class SerialComChannel(object):
    def __init__(self, device="/dev/ttyUSB0", baud=115200, bits=8, stop=1, parity='N'):
        self.device = device
        self.baud = baud
        self.bits = bits
        self.stop = stop
        self.parity = parity
        self._fd = serial.Serial(device, baudrate=baud, bytesize=bits, stopbits=stop, parity=parity)
        self._fd.setTimeout(5)

    def open(self):
        self._fd = Serial(port=self.device, baudrate=self.baud, bytesize=self.bits, parity='N', stopbits=stop)

    def read(self, bytecount):
        return self._fd.read(bytecount)

    def readline(self):
        return self._fd.readline()

    def write(self, data):
        self._fd.write(data)

class Stick(SerialComChannel):
    def __init__(self, *args):
        SerialComChannel.__init__(self, *args)
        self.init()

    def init(self):
        """send init message to the stick"""
        msg = PlugwiseInitRequest().serialize()
        self.send_msg(msg)
        resp = self.expect_response(PlugwiseInitResponse)
        debug(str(resp))

    def send_msg(self, cmd):
        debug("_send_cmd:"+repr(cmd))
        self.write(cmd)

    def _recv_response(self, response_obj):
        readlen = len(response_obj)
        debug("expecting to read "+str(readlen)+" bytes for msg. "+str(response_obj))
        msg = self.readline()
        debug("read:"+repr(msg)+" with length "+str(len(msg)))
        response_obj.unserialize(msg)
        return response_obj

    def expect_response(self, response_class):
        resp = response_class()
        # XXX: there's a lot of debug info flowing on the bus so it's
        # expected that we constantly get unexpected messages
        while 1:
            try:
                return self._recv_response(resp)
            except ProtocolError, reason:
                error("encountered protocol error:"+str(reason))

class Circle(object):
    """provides interface to the Plugwise Plug & Plug+ devices
    """

    def __init__(self, mac, comchan=None):
        """
        will raise ValueError if mac doesn't look valid
        """
        mac = mac.upper()
        if self._validate_mac(mac) == False:
            raise ValueError, "MAC address is in unexpected format: "+str(mac)

        self.mac = mac

        if comchan is None:
            self._comchan = Stick()
        else:
            self._comchan = comchan

        self.gain_a = None
        self.gain_b = None
        self.off_ruis = None
        self.off_tot = None

    def _validate_mac(self, mac):
        if not re.match("^[A-F0-9]+$", mac):
            return False

        try:
            _ = int(mac, 16)
        except ValueError:
            return False

        return True

    def set_timeout(self, timeout):
        """sets timeout for commands in seconds
        if we do not receive response from the device in this time TimeoutException will be rised
        """
        # FIXME: implement me
        self._timeout = timeout

    def calibrate(self):
        """fetch calibration info from the device"""
        msg = PlugwiseCalibrationRequest(self.mac).serialize()
        self._comchan.send_msg(msg)
        calibration_response = self._comchan.expect_response(PlugwiseCalibrationResponse)
        retl = []

        for x in ('gain_a', 'gain_b', 'off_ruis', 'off_tot'):
            val = getattr(calibration_response, x).value
            retl.append(val)
            setattr(self, x, val)

        return retl

    def get_power_usage(self):
        """returns power usage for the last 8 seconds in Watts
        """
        if self.gain_a is None:
            self.calibrate()

        msg = PlugwisePowerUsageRequest(self.mac).serialize()
        self._comchan.send_msg(msg)
        power_usage_response = self._comchan.expect_response(PlugwisePowerUsageResponse)
        p1s = power_usage_response.pulse_1s.value
        # XXX: make sense of this eq & the magic 468.X
        cp = 1.0 * (((((p1s + self.off_ruis)**2) * self.gain_b) + ((p1s + self.off_ruis) * self.gain_a)) + self.off_tot)
        return ((cp / 1) / 468.9385193) * 1000

    def get_info(self):
        """fetch state & logbuffer info
        """
        msg = PlugwiseInfoRequest(self.mac).serialize()
        self._comchan.send_msg(msg)
        resp = self._comchan.expect_response(PlugwiseInfoResponse)
        return resp

    def get_clock(self):
        """fetch current time from the device"""
        msg = PlugwiseClockInfoRequest(self.mac).serialize()
        self._comchan.send_msg(msg)
        resp = self._comchan.expect_response(PlugwiseClockInfoResponse)
        return resp.time.value

    def set_clock(self, dt):
        """set clock to the value indicated by the datetime object dt
        """
        msg = PlugwiseClockSetRequest(self.mac, dt).serialize()
        self._comchan.send_msg(msg)
        return dt

    def switch(self, on):
        """switch power on or off
        @arg on: new state, boolean
        """
        req = PlugwiseSwitchRequest(self.mac, on)
        return self._comchan.send_msg(req.serialize())

    def switch_on(self):
        self.switch(True)

    def switch_off(self):
        self.switch(False)
