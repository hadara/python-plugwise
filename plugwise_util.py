import optparse

from plugwise import *

DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"

parser = optparse.OptionParser()
parser.add_option("-m", "--mac", dest="mac", help="MAC address")
parser.add_option("-d", "--device", dest="device", help="serial port device")
parser.add_option("-p", "--power", action="store_true", help="get power usage")
parser.add_option("-s", "--switch", dest="switch", help="switch power on/off")

options, args = parser.parse_args()

device = DEFAULT_SERIAL_PORT
if options.device:
    device = options.device

if not options.mac:
    print("you have to specify mac with -m")
    parser.print_help()
    sys.exit(-1)

device = Stick(device)
c = Circle(options.mac, device)

if options.switch:
    sw_direction = options.switch.lower()
    if sw_direction in ('on', '1'):
        c.switch_on()
    elif sw_direction in ('off', '1'):
        c.switch_off()
    else:
        print("unknown switch direction: "+sw_direction)
        sys.exit(-1)

if options.power:
    print("power usage: %.2fW" % (c.get_power_usage(),))
