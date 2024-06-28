import signal
from datetime import datetime as dt
from datetime import timedelta as td
import socket
import time
import sys
import struct
import threading
from salsa20 import Salsa20_xor

# ports for send and receive data
SendPort = 33739
ReceivePort = 33740

# ctrl-c handler
def handler(signum, frame):
	sys.stdout.flush()
	exit(1)

# handle ctrl-c
signal.signal(signal.SIGINT, handler)

# get ip address from command line
if len(sys.argv) == 2:
    ip = sys.argv[1]
else:
    print('Run like : python3 gt7telemetry.py <playstation-ip>')
    exit(1)

# Create a UDP socket and bind it
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', ReceivePort))
s.settimeout(10)

# data stream decoding
def salsa20_dec(dat):
	KEY = b'Simulator Interface Packet GT7 ver 0.0'
	# Seed IV is always located here
	oiv = dat[0x40:0x44]
	iv1 = int.from_bytes(oiv, byteorder='little')
	# Notice DEADBEAF, not DEADBEEF
	iv2 = iv1 ^ 0xDEADBEAF
	IV = bytearray()
	IV.extend(iv2.to_bytes(4, 'little'))
	IV.extend(iv1.to_bytes(4, 'little'))
	ddata = Salsa20_xor(dat, bytes(IV), KEY[0:32])
	magic = int.from_bytes(ddata[0:4], byteorder='little')
	if magic != 0x47375330:
		return bytearray(b'')
	return ddata

# send heartbeat
def send_hb(s):
	send_data = 'A'
	s.sendto(send_data.encode('utf-8'), (ip, SendPort))
	#print('send heartbeat')

def secondsToLaptime(seconds):
	remaining = seconds
	minutes = seconds // 60
	remaining = seconds % 60
	return '{:01.0f}:{:06.3f}'.format(minutes, remaining)


# start by sending heartbeat
send_hb(s)

# Initialize variables
prevlap = -1
pktid = 0
pknt = 0

while True:
    try:
        data, address = s.recvfrom(4096)
        pknt += 1
        ddata = salsa20_dec(data)
        
        if len(ddata) > 0 and struct.unpack('i', ddata[0x70:0x70+4])[0] > pktid:
            pktid = struct.unpack('i', ddata[0x70:0x70+4])[0]

            bstlap = struct.unpack('i', ddata[0x78:0x78+4])[0]
            lstlap = struct.unpack('i', ddata[0x7C:0x7C+4])[0]
            curlap = struct.unpack('h', ddata[0x74:0x74+2])[0]
            
            if curlap > 0:
                dt_now = dt.now()
                if curlap != prevlap:
                    prevlap = curlap
                    dt_start = dt_now
                curLapTime = dt_now - dt_start
                curLapTimeFormatted = secondsToLaptime(curLapTime.total_seconds())
            else:
                curLapTime = 0
                curLapTimeFormatted = ''
                    
            cgear = struct.unpack('B', ddata[0x90:0x90+1])[0] & 0b00001111
            sgear = struct.unpack('B', ddata[0x90:0x90+1])[0] >> 4
            if cgear < 1:
                cgear = 'R'
            if sgear > 14:
                sgear = '–'

            fuelCapacity = struct.unpack('f', ddata[0x48:0x48+4])[0]
            isEV = False if fuelCapacity > 0 else True
            
            if isEV:
                fuelType = 'Charge'
                fuelRemaining = '{:3.0f} kWh'.format(struct.unpack('f', ddata[0x44:0x44+4])[0])
                fuelCapacityFormatted = '??? kWh'
            else:
                fuelType = 'Fuel'
                fuelRemaining = '{:3.0f} lit'.format(struct.unpack('f', ddata[0x44:0x44+4])[0])
                fuelCapacityFormatted = '{:3.0f} lit'.format(struct.unpack('f', ddata[0x48:0x48+4])[0])

            boost = struct.unpack('f', ddata[0x50:0x50+4])[0] - 1
            hasTurbo = True if boost > -1 else False

            tyreDiamFL = struct.unpack('f', ddata[0xB4:0xB4+4])[0]
            tyreDiamFR = struct.unpack('f', ddata[0xB8:0xB8+4])[0]
            tyreDiamRL = struct.unpack('f', ddata[0xBC:0xBC+4])[0]
            tyreDiamRR = struct.unpack('f', ddata[0xC0:0xC0+4])[0]

            tyreSpeedFL = abs(3.6 * tyreDiamFL * struct.unpack('f', ddata[0xA4:0xA4+4])[0])
            tyreSpeedFR = abs(3.6 * tyreDiamFR * struct.unpack('f', ddata[0xA8:0xA8+4])[0])
            tyreSpeedRL = abs(3.6 * tyreDiamRL * struct.unpack('f', ddata[0xAC:0xAC+4])[0])
            tyreSpeedRR = abs(3.6 * tyreDiamRR * struct.unpack('f', ddata[0xB0:0xB0+4])[0])

            carSpeed = 3.6 * struct.unpack('f', ddata[0x4C:0x4C+4])[0]

            if carSpeed > 0:
                tyreSlipRatioFL = '{:6.2f}'.format(tyreSpeedFL / carSpeed)
                tyreSlipRatioFR = '{:6.2f}'.format(tyreSpeedFR / carSpeed)
                tyreSlipRatioRL = '{:6.2f}'.format(tyreSpeedRL / carSpeed)
                tyreSlipRatioRR = '{:6.2f}'.format(tyreSpeedRR / carSpeed)
            else:
                tyreSlipRatioFL = '  –  '
                tyreSlipRatioFR = '  –  '
                tyreSlipRatioRL = '  -  '
                tyreSlipRatioRR = '  –  '

            timeOfDay = '{:>8}'.format(str(td(seconds=round(struct.unpack('i', ddata[0x80:0x80+4])[0] / 1000))))

            curLap = '{:3.0f}'.format(curlap)
            totalLaps = '{:3.0f}'.format(struct.unpack('h', ddata[0x76:0x76+2])[0])

            curPosition = '{:2.0f}'.format(struct.unpack('h', ddata[0x84:0x84+2])[0])
            totalPositions = '{:2.0f}'.format(struct.unpack('h', ddata[0x86:0x86+2])[0])

            bestLapTime = secondsToLaptime(bstlap / 1000) if bstlap != -1 else ''
            lastLapTime = secondsToLaptime(lstlap / 1000) if lstlap != -1 else ''

            carID = '{:5.0f}'.format(struct.unpack('i', ddata[0x124:0x124+4])[0])

            throttle = '{:3.0f}'.format(struct.unpack('B', ddata[0x91:0x91+1])[0] / 2.55)
            rpm = '{:7.0f}'.format(struct.unpack('f', ddata[0x3C:0x3C+4])[0])
            speedKPH = '{:7.1f}'.format(carSpeed)
            rpmRevWarning = '{:5.0f}'.format(struct.unpack('H', ddata[0x88:0x88+2])[0])

            brake = '{:3.0f}'.format(struct.unpack('B', ddata[0x92:0x92+1])[0] / 2.55)
            actualGear = cgear
            suggestedGear = sgear

            boostFormatted = '{:7.2f}'.format(boost) if hasTurbo else '–'

            rpmRevLimiter = '{:5.0f}'.format(struct.unpack('H', ddata[0x8A:0x8A+2])[0])
            estTopSpeed = '{:5.0f}'.format(struct.unpack('h', ddata[0x8C:0x8C+2])[0])

            clutch = '{:5.3f}'.format(struct.unpack('f', ddata[0xF4:0xF4+4])[0])
            clutchEngaged = '{:5.3f}'.format(struct.unpack('f', ddata[0xF8:0xF8+4])[0])
            rpmAfterClutch = '{:7.0f}'.format(struct.unpack('f', ddata[0xFC:0xFC+4])[0])

            oilTemp = '{:6.1f}'.format(struct.unpack('f', ddata[0x5C:0x5C+4])[0])
            waterTemp = '{:6.1f}'.format(struct.unpack('f', ddata[0x58:0x58+4])[0])

            oilPressure = '{:6.2f}'.format(struct.unpack('f', ddata[0x54:0x54+4])[0])
            rideHeight = '{:6.0f}'.format(1000 * struct.unpack('f', ddata[0x38:0x38+4])[0])

            tyreTempFL = '{:6.1f}'.format(struct.unpack('f', ddata[0x60:0x60+4])[0])
            tyreTempFR = '{:6.1f}'.format(struct.unpack('f', ddata[0x64:0x64+4])[0])
            tyreDiamFLFormatted = '{:6.1f}'.format(200 * tyreDiamFL)
            tyreDiamFRFormatted = '{:6.1f}'.format(200 * tyreDiamFR)

            tyreSpeedFLFormatted = '{:6.1f}'.format(tyreSpeedFL)
            tyreSpeedFRFormatted = '{:6.1f}'.format(tyreSpeedFR)
            tyreSlipRatioFLFormatted = tyreSlipRatioFL
            tyreSlipRatioFRFormatted = tyreSlipRatioFR

            suspensionFL = '{:6.2f}'.format(struct.unpack('f', ddata[0x98:0x98+4])[0])
            suspensionFR = '{:6.2f}'.format(struct.unpack('f', ddata[0x9C:0x9C+4])[0])

            steeringAngle = '{:6.1f}'.format(struct.unpack('f', ddata[0x68:0x68+4])[0])

            outputVariables = {
                'curLapTime': curLapTimeFormatted,
                'bestLapTime': bestLapTime,
                'lastLapTime': lastLapTime,
                'fuelType': fuelType,
                'fuelRemaining': fuelRemaining,
                'fuelCapacity': fuelCapacityFormatted,
                'boost': boostFormatted,
                'tyreSlipRatioFL': tyreSlipRatioFLFormatted,
                'tyreSlipRatioFR': tyreSlipRatioFRFormatted,
                'timeOfDay': timeOfDay,
                'curLap': curLap,
                'totalLaps': totalLaps,
                'curPosition': curPosition,
                'totalPositions': totalPositions,
                'carID': carID,
                'throttle': throttle,
                'rpm': rpm,
                'speedKPH': speedKPH,
                'rpmRevWarning': rpmRevWarning,
                'brake': brake,
                'actualGear': actualGear,
                'suggestedGear': suggestedGear,
                'rpmRevLimiter': rpmRevLimiter,
                'estTopSpeed': estTopSpeed,
                'clutch': clutch,
                'clutchEngaged': clutchEngaged,
                'rpmAfterClutch': rpmAfterClutch,
                'oilTemp': oilTemp,
                'waterTemp': waterTemp,
                'oilPressure': oilPressure,
                'rideHeight': rideHeight,
                'tyreTempFL': tyreTempFL,
                'tyreTempFR': tyreTempFR,
                'tyreDiamFL': tyreDiamFLFormatted,
                'tyreDiamFR': tyreDiamFRFormatted,
                'tyreSpeedFL': tyreSpeedFLFormatted,
                'tyreSpeedFR': tyreSpeedFRFormatted,
                'suspensionFL': suspensionFL,
                'suspensionFR': suspensionFR,
                'steeringAngle': steeringAngle,
            }

            for key, value in outputVariables.items():
                print(f'{key}: {value}')

        if pknt > 100:
            send_hb(s)
            pknt = 0

    except Exception as e:
        print(f'Exception: {e}')
        send_hb(s)
        pknt = 0

