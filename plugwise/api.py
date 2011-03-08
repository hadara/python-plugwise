#!/bin/env python

# Copyright (C) 2011 Sven Petai <hadara@bsd.ee> 
# Use of this source code is governed by the MIT license found in the LICENSE file.

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
#   - support for older firmware versions

import re
import sys
import time

from util import *
from protocol import *
from exceptions import *

class Stick(SerialComChannel):
    """provides interface to the Plugwise Stick"""

    def __init__(self, port=0, timeout=5):
        SerialComChannel.__init__(self, port=port, timeout=timeout)
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
        if msg == "":
            raise TimeoutException, "Timeout while waiting for response from device"

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

    def __init__(self, mac, comchan):
        """
        will raise ValueError if mac doesn't look valid
        """
        mac = mac.upper()
        if self._validate_mac(mac) == False:
            raise ValueError, "MAC address is in unexpected format: "+str(mac)

        self.mac = mac

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

    def pulses_to_watts(self, pulses, seconds):
        """converts the pulse count to Watts
        @param pulse: number of pulses
        @param seconds: over how many seconds were the pulses counted
        """
        if self.gain_a is None:
            self.calibrate()

        pulses /= seconds
        correction = 1.0 * (((((pulses + self.off_ruis)**2) * self.gain_b) + ((pulses + self.off_ruis) * self.gain_a)) + self.off_tot)
        return ((correction / 1) / 468.9385193) * 1000

    def calibrate(self):
        """fetch calibration info from the device
        """
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
        """returns power usage for the last second in Watts
        """
        msg = PlugwisePowerUsageRequest(self.mac).serialize()
        self._comchan.send_msg(msg)
        power_usage_response = self._comchan.expect_response(PlugwisePowerUsageResponse)
        pulses = power_usage_response.pulse_1s.value
        retval = self.pulses_to_watts(pulses, 1)
        # sometimes it's slightly less than 0, probably caused by calibration/calculation errors
        # it doesn't make much sense to return negative power usage in that case
        return retval if retval > 0.0 else 0.0

    def get_info(self):
        """fetch relay state & current logbuffer index info
        """
        msg = PlugwiseInfoRequest(self.mac).serialize()
        self._comchan.send_msg(msg)
        resp = self._comchan.expect_response(PlugwiseInfoResponse)
        return response_to_dict(resp)

    def get_clock(self):
        """fetch current time from the device
        """
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
        @param on: new state, boolean
        """
        req = PlugwiseSwitchRequest(self.mac, on)
        return self._comchan.send_msg(req.serialize())

    def switch_on(self):
        self.switch(True)

    def switch_off(self):
        self.switch(False)

    def power_usage_history(self, log_buffer_index=None):
        """Returns the power usage for 4 hours from the log buffer of the Circle.

        @param log_buffer_index: index of the first log buffer to return.
            If None then current log buffer index - 4 is used
        @return: list of (datetime, power_usage_in_watts) tuples
        """
        if log_buffer_index is None:
            info_resp = self.get_info()
            log_buffer_index = info_resp['last_logaddr']-4

        log_req = PlugwisePowerBufferRequest(self.mac, log_buffer_index).serialize()
        self._comchan.send_msg(log_req)
        resp = self._comchan.expect_response(PlugwisePowerBufferResponse)
        retl = []

        for i in range(1, 5):
            dt = getattr(resp, "logdate%d" % (i,)).value
            watts = self.pulses_to_watts(getattr(resp, "pulses%d" % (i,)).value, 3600)
            retl.append((dt, watts))

        return retl

def response_to_dict(r):
    retd = {}
    for key in dir(r):
        ptr = getattr(r, key)
        if isinstance(ptr, BaseType):
            retd[key] = ptr.value
    return retd
