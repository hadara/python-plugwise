# Copyright (C) 2011 Sven Petai <hadara@bsd.ee> 
# Use of this source code is governed by the MIT license found in the LICENSE file.


import struct
import binascii
import datetime

from exceptions import *
from util import *

DEBUG_PROTOCOL = False

# plugwise year information is offset from y2k
PLUGWISE_EPOCH = 2000

import crcmod

crc_fun = crcmod.mkCrcFun(0x11021, rev=False, initCrc=0x0000, xorOut=0x0000)

class BaseType(object):
    def __init__(self, value, length):
        self.value = value
        self.length = length

    def serialize(self):
        return self.value

    def unserialize(self, val):
        self.value = val

    def __len__(self):
        return self.length

class CompositeType(BaseType):
    def __init__(self):
        self.contents = []

    def serialize(self):
        return ''.join(a.serialize() for a in self.contents)

    def unserialize(self, val):
        for p in self.contents:
            myval = val[:len(p)]
            debug("parse:"+str(myval))
            p.unserialize(myval)
            debug("newval:"+str(p.value))
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
        fmt = "%%0%dX" % self.length
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
        self.value += PLUGWISE_EPOCH

class DateTime(CompositeType):
    """datetime value as used in the general info response
    format is: YYMMmmmm
    where year is offset value from the epoch which is Y2K
    """

    def __init__(self, year=0, month=0, minutes=0):
        CompositeType.__init__(self)        
        self.year = Year2k(year-PLUGWISE_EPOCH, 2)
        self.month = Int(month, 2)
        self.minutes = Int(minutes, 4)
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

    def __init__(self, hour=0, minute=0, second=0):
        CompositeType.__init__(self)
        self.hour = Int(hour, 2)
        self.minute = Int(minute, 2)
        self.second = Int(second, 2)
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
        return "%04X" % crc_fun(s)

class PlugwiseResponse(PlugwiseMessage):
    def __init__(self):
        PlugwiseMessage.__init__(self)
        self.params = []

    def unserialize(self, response):
        if len(response) != len(self):
            raise ProtocolError, "message doesn't have expected length. expected %d bytes got %d" % (len(self), len(response))

        header, function_code, command_counter, mac = struct.unpack("4s4s4s16s", response[:28])
        debug(repr(header)+" "+repr(function_code)+" "+repr(command_counter)+" "+repr(mac))

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
            debug("parse:"+str(myval))
            p.unserialize(myval)
            debug("newval:"+str(p.value))
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
            self.last_logaddr, self.relay_state, 
            self.hz, self.hw_ver, self.fw_ver, self.unknown
        ]

class PlugwiseInitResponse(PlugwiseResponse):
    ID = '0011'

    def __init__(self):
        PlugwiseResponse.__init__(self)
        self.unknown = Int(0, length=2)
        self.network_is_online = Int(0, length=2)
        self.network_id = Int(0, length=16)
        self.network_id_short = Int(0, length=4)
        self.unknown = Int(0, length=2)
        self.params += [
            self.unknown,
            self.network_is_online,
            self.network_id,
            self.network_id_short,
            self.unknown,
        ]

class PlugwiseRequest(PlugwiseMessage):
    def __init__(self, mac):
        PlugwiseMessage.__init__(self)
        self.args = []
        self.mac = mac

class PlugwiseInitRequest(PlugwiseRequest):
    """initialize Stick"""
    ID = '000A'

    def __init__(self):
        """message for that initializes the Stick"""
        # init is the only request message that doesn't send MAC address
        PlugwiseRequest.__init__(self, '')

class PlugwisePowerUsageRequest(PlugwiseRequest):
    ID = '0012'

class PlugwiseInfoRequest(PlugwiseRequest):
    ID = '0023'

class PlugwiseClockInfoRequest(PlugwiseRequest):
    ID = '003E'

class PlugwiseClockSetRequest(PlugwiseRequest):
    ID = '0016'

    def __init__(self, mac, dt):
        PlugwiseRequest.__init__(self, mac)
        month_minutes = ((dt.day-1)*24*60)+dt.minute
        d = DateTime(dt.year, dt.month, month_minutes)
        t = Time(dt.hour, dt.minute, dt.second)
        day_of_week = Int(dt.weekday(), 2)
        # FIXME: use LogAddr instead
        log_buf_addr = String('FFFFFFFF', 8)
        self.args += [d, log_buf_addr, t, day_of_week]

class PlugwiseSwitchRequest(PlugwiseRequest):
    """switches Plug or or off"""
    ID = '0017'
    
    def __init__(self, mac, on):
        PlugwiseRequest.__init__(self, mac)
        val = 1 if on == True else 0
        self.args.append(Int(val, length=2))

class PlugwiseCalibrationRequest(PlugwiseRequest):
    ID = '0026'
