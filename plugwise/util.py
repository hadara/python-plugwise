# Copyright (C) 2011 Sven Petai <hadara@bsd.ee> 
# Use of this source code is governed by the MIT license found in the LICENSE file.


import serial

DEBUG_PROTOCOL = False

def hexstr(s):
    return ' '.join(hex(ord(x)) for x in s)

def debug(msg):
    if __debug__ and DEBUG_PROTOCOL:
        print(msg)

def error(msg):
    # XXX: we currently have far to many false "protocol errors"  since we don't look for ACKs etc.
    # so just ignore these for now unless the debug is set
    return debug(msg)

class SerialComChannel(object):
    """simple wrapper around serial module"""

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
