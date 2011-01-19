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

"""
Library for communicating with Plugwise Circle and Circle+ smartplugs.

There's no official documentation available about these things so this implementation is based
on partial reverse engineering by Maarten Damen (http://www.maartendamen.com/downloads/?did=5)
and several other sources. 

Sipmle usage example:

   >>> from plugwise import Circle
   >>> c = Circle(<some mac>)
   >>> c.switch_off()
   >>> c.switch_on()
   >>> print c.power_usage()

Slightly more complex example with a different port:

   >>> from plugwise import Stick
   >>> s = Stick(port="/dev/ttyUSB1")
   >>> c1, c2 = Circle(<mac1>, s), Circle(<mac2>, s)
   >>> c1.switch_on()
   >>> print c2.power_usage()

"""

# TODO:
#   - implement stick init
#   - implement reading from the buffer
#   - implement schedule upload
#   - make com chan. concurrency safe

import sys
import time
import serial
import struct
import datetime
import binascii

class PlugwiseException(Exception):
    pass

class ProtocolError(PlugwiseException):
    pass

class TimeoutException(PlugwiseException):
    pass

def hexstr(s):
    return ' '.join(hex(ord(x)) for x in s)

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

from CrcMoose import CrcAlgorithm
crca =  CrcAlgorithm(16, 0x11021)

# base types
class BaseType(object):
    def __init__(self, value, length):
        self.value = value
        self.length = length

    def unserialize(self, val):
        self.value = val

    def __len__(self):
        return self.length

class CompositeType(object):
    def __init__(self):
        self.contents = []

    def serialize(self):
        return ''.join(a.serialize() for a in self.contents)

    def unserialize(self, val):
        for p in self.contents:
            myval = val[:len(p)]
            print "parse:",myval
            p.unserialize(myval)
            print "newval:",p.value
            val = val[len(myval):]
        return val
        
    def __len__(self):
        return sum(len(x) for x in self.contents)

class String(BaseType):
    pass

class Int(BaseType):
    def __init__(self, value, length=2):
        self.value = value
        self.length = length

    def serialize(self):
        fmt = "%%0%dd" % self.length
        return fmt % self.value

    def unserialize(self, val):
        self.value = int(val, 16)

class UnixTimestamp(Int):
    def __init__(self, value, length=8):
        Int.__init__(self, value, length=length)

    def unserialize(self, val):
        Int.unserialize(self, val)
        self.value = datetime.datetime.fromtimestamp(self.value)

class Year2k(Int):
    """year value that is offset from the year 2000"""

    def unserialize(self, val):
        Int.unserialize(self, val)
        self.value += 2000

class DateTime(CompositeType):
    """datetime value as used in the general info response
    format is: YYMMmmmm
    where year is offset value from the epoch which is Y2K
    """

    def __init__(self):
        CompositeType.__init__(self)        
        self.year = Year2k(0, 2)
        self.month = Int(0, 2)
        self.minutes = Int(0, 4)
        self.contents += [self.year, self.month, self.minutes]

    def unserialize(self, val):
        CompositeType.unserialize(self, val)
        minutes = self.minutes.value
        hours = minutes // 60
        days = hours // 24
        hours -= (days*24)
        minutes -= (days*24*60)+(hours*60)
        self.value = datetime.datetime(self.year.value, self.month.value, days, hours, minutes)

class Time(CompositeType):
    """time value as used in the clock info response"""

    def __init__(self):
        CompositeType.__init__(self)
        self.hour = Int(0, 2)
        self.minute = Int(0, 2)
        self.second = Int(0, 2)
        self.contents += [self.hour, self.minute, self.second]

    def unserialize(self, val):
        CompositeType.unserialize(self, val)
        self.value = datetime.time(self.hour.value, self.minute.value, self.second.value)
        

class Float(BaseType):
    def __init__(self, value, length=4):
        self.value = value
        self.length = length

    def unserialize(self, val):
        hexval = binascii.unhexlify(val)
        self.value = struct.unpack("!f", hexval)[0]

class LogAddr(Int):
    LOGADDR_OFFSET = 278528

    def unserialize(self, val):
        Int.unserialize(self, val)
        self.value = (self.value - self.LOGADDR_OFFSET) / 32

# /base types

class PlugwiseMessage(object):
    PACKET_HEADER = '\x05\x05\x03\x03'
    PACKET_FOOTER = '\x0d\x0a'
    
    def serialize(self):
        """return message in a serialized format that can be sent out
        on wire
        """
        args = ''.join(a.serialize() for a in self.args)
        msg = self.ID+self.mac+args
        checksum = self.calculate_checksum(msg)
        return self.PACKET_HEADER+msg+checksum+self.PACKET_FOOTER

    def calculate_checksum(self, s):
        crcval = crca.calcString(s)
        return "%04X" % crca.calcString(s)

class PlugwiseResponse(PlugwiseMessage):
    def __init__(self):
        PlugwiseMessage.__init__(self)
        self.params = []

    def unserialize(self, response):
        if len(response) != len(self):
            raise ProtocolError, "message doesn't have expected length. expected %d bytes got %d" % (len(self), len(response))

        header, function_code, command_counter, mac = struct.unpack("4s4s4s16s", response[:28])
        print repr(header),repr(function_code),repr(command_counter),repr(mac)

        # FIXME: check function code match

        if header != self.PACKET_HEADER:
            raise ProtocolError, "broken header!"

        # FIXME: avoid magic numbers
        response = response[28:]
        response = self._parse_params(response)
        crc = response[:4]

        if response[4:] != self.PACKET_FOOTER:
            raise ProtocolError, "broken footer!"

    def _parse_params(self, response):
        for p in self.params:
            myval = response[:len(p)]
            print "parse:",myval
            p.unserialize(myval)
            print "newval:",p.value
            response = response[len(myval):]
        return response

    def __len__(self):
        arglen = sum(len(x) for x in self.params)
        return 34 + arglen

class PlugwiseCalibrationResponse(PlugwiseResponse):
    ID = '0027'

    def __init__(self):
        PlugwiseResponse.__init__(self)
        self.gain_a = Float(0, 8)
        self.gain_b = Float(0, 8)
        self.off_tot = Float(0, 8)
        self.off_ruis = Float(0, 8)
        self.params += [self.gain_a, self.gain_b, self.off_tot, self.off_ruis]

class PlugwiseClockInfoResponse(PlugwiseResponse):
    ID = '003F'

    def __init__(self):
        PlugwiseResponse.__init__(self)
        self.time = Time()
        self.day_of_week = Int(0, 2)
        self.unknown = Int(0, 2)
        self.unknown2 = Int(0, 4)
        self.params += [self.time, self.day_of_week, self.unknown, self.unknown2]

class PlugwisePowerUsageResponse(PlugwiseResponse):
    """returns power usage as impulse counters for several different timeframes
    """
    ID = '0013'

    def __init__(self):
        PlugwiseResponse.__init__(self)
        self.pulse_1s = Int(0, 4)
        self.pulse_8s = Int(0, 4)
        # XXX: is it really total or just some longer period, for example hour?
        self.pulse_total = Int(0, 8)
        self.unknown1 = Int(0, 4)
        self.unknown2 = Int(0, 4)
        self.unknown3 = Int(0, 4)
        self.params += [self.pulse_1s, self.pulse_8s, self.pulse_total, self.unknown1, self.unknown2, self.unknown3]

class PlugwiseInfoResponse(PlugwiseResponse):
    ID = '0024'
    
    def __init__(self):
        PlugwiseResponse.__init__(self)
        self.datetime = DateTime()
        self.last_logaddr = LogAddr(0, length=8)
        self.relay_state = Int(0, length=2)
        self.hz = Int(0, length=2)
        self.hw_ver = String(None, length=12)
        self.fw_ver = UnixTimestamp(0)
        self.unknown = Int(0, length=2)
        self.params += [
            self.datetime,
            #self.year, self.month, self.minutes, 
            self.last_logaddr, self.relay_state, 
            self.hz, self.hw_ver, self.fw_ver, self.unknown
        ]

class PlugwiseRequest(PlugwiseMessage):
    def __init__(self, mac):
        PlugwiseMessage.__init__(self)
        self.args = []
        self.mac = mac

class PlugwisePowerUsageRequest(PlugwiseRequest):
    ID = '0012'

class PlugwiseInfoRequest(PlugwiseRequest):
    ID = '0023'

class PlugwiseClockInfoRequest(PlugwiseRequest):
    ID = '003E'

class PlugwiseSwitchRequest(PlugwiseRequest):
    """switches Plug or or off"""
    ID = '0017'
    
    def __init__(self, mac, on):
        PlugwiseRequest.__init__(self, mac)
        val = 1 if on == True else 0
        self.args.append(Int(val, length=2))

class PlugwiseCalibrationRequest(PlugwiseRequest):
    ID = '0026'

class Stick(SerialComChannel):
    pass

class Circle(object):
    """provides interface to the Plugwise Plug & Plug+ devices
    """

    def __init__(self, mac, comchan=None):
        self.mac = mac

        if comchan is None:
            self._comchan = SerialComChannel()
        else:
            self._comchan = comchan

        self.gain_a = None
        self.gain_b = None
        self.off_ruis = None
        self.off_tot = None

    def set_timeout(self, timeout):
        """sets timeout for commands in seconds
        if we do not receive response from the device in this time TimeoutException will be rised
        """
        # FIXME: implement me
        self._timeout = timeout

    # generic communication functions
    def _send_msg(self, cmd):
        print "_send_cmd:",repr(cmd)
        self._comchan.write(cmd)

    def _recv_response(self, response_obj):
        readlen = len(response_obj)
        print "expecting to read",readlen,"bytes for msg.",response_obj
        msg = self._comchan.readline()
        print "read:",repr(msg),"with length",len(msg)
        response_obj.unserialize(msg)
        return response_obj

    def _expect_response(self, response_class):
        resp = response_class()
        # XXX: there's a lot of debug info flowing on the bus so it's
        # expected that we constantly get unexpected messages
        while 1:
            try:
                return self._recv_response(resp)
            except ProtocolError, reason:
                print "encountered protocol error:",reason
    # /generic communication

    def calibrate(self):
        """fetch calibration info from the device"""
        msg = PlugwiseCalibrationRequest(self.mac).serialize()
        self._send_msg(msg)
        calibration_response = self._expect_response(PlugwiseCalibrationResponse)
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
        self._send_msg(msg)
        power_usage_response = self._expect_response(PlugwisePowerUsageResponse)
        p8s = power_usage_response.pulse_1s.value
        # XXX: make sense of this eq & the magic 468.X
        cp = 1.0 * (((((p8s + self.off_ruis)**2) * self.gain_b) + ((p8s + self.off_ruis) * self.gain_a)) + self.off_tot)
        return ((cp / 1) / 468.9385193) * 1000

    def get_info(self):
        """fetch state & logbuffer info
        """
        msg = PlugwiseInfoRequest(self.mac).serialize()
        self._send_msg(msg)
        resp = self._expect_response(PlugwiseInfoResponse)

    def switch(self, on):
        """switch power on or off
        @arg on: new state, boolean
        """
        req = PlugwiseSwitchRequest(self.mac, on)
        return self._send_msg(req.serialize())

    def get_clock(self):
        """fetch current time from the device"""
        msg= PlugwiseClockInfoRequest(self.mac).serialize()
        self._send_msg(msg)
        resp = self._expect_response(PlugwiseClockInfoResponse)
        print resp

    def set_clock(self, dt):
        """set clock to the value indicated by the datetime object dt
        """
        pass

    def switch_on(self):
        self.switch(True)

    def switch_off(self):
        self.switch(False)

if __name__ == '__main__':
    mac = sys.argv[1]
    #comchan = SerialComChannel()
    pw_dev = Circle(mac)
    #pw_dev.switch_off()
    #time.sleep(5)
    #pw_dev.switch_on()
    #pw_dev.calibrate()
    print pw_dev.get_power_usage()
    print pw_dev.get_info()
    print pw_dev.get_clock()
