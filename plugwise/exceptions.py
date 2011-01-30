class PlugwiseException(Exception):
    pass

class ProtocolError(PlugwiseException):
    pass

class TimeoutException(PlugwiseException):
    pass
