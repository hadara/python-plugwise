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
