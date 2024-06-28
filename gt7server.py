from datetime import datetime as dt
from datetime import timedelta as td
from flask import Flask, jsonify
import socket
import struct
import threading
import sys
import signal
import time
from salsa20 import Salsa20_xor

app = Flask(__name__)
shared_data = {}

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


def secondsToLaptime(seconds):
	remaining = seconds
	minutes = seconds // 60
	remaining = seconds % 60
	return '{:01.0f}:{:06.3f}'.format(minutes, remaining)

# Define a function to continuously update shared_data
def update_shared_data():
    global shared_data
    SendPort = 33739
    ReceivePort = 33740

    # Create a UDP socket and bind it
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', ReceivePort))
    s.settimeout(10)

    while True:
        try:
            data, address = s.recvfrom(4096)
            ddata = salsa20_dec(data)

            if len(ddata) > 0 and struct.unpack('i', ddata[0x70:0x70+4])[0] > shared_data.get("pktid", -1):
                shared_data["pktid"] = struct.unpack('i', ddata[0x70:0x70+4])[0]

                shared_data["bstlap"] = struct.unpack('i', ddata[0x78:0x78+4])[0]
                shared_data["lstlap"] = struct.unpack('i', ddata[0x7C:0x7C+4])[0]
                shared_data["curlap"] = struct.unpack('h', ddata[0x74:0x74+2])[0]

                if shared_data["curlap"] > 0:
                    dt_now = dt.now()
                    if shared_data["curlap"] != shared_data.get("prevlap", -1):
                        shared_data["prevlap"] = shared_data["curlap"]
                        shared_data["dt_start"] = dt_now
                    shared_data["curLapTime"] = str(dt_now - shared_data["dt_start"])
                else:
                    shared_data["curLapTime"] = ''

                shared_data["cgear"] = struct.unpack('B', ddata[0x90:0x90+1])[0] & 0b00001111
                shared_data["sgear"] = struct.unpack('B', ddata[0x90:0x90+1])[0] >> 4
                if shared_data["cgear"] < 1:
                    shared_data["cgear"] = 'R'
                if shared_data["sgear"] > 14:
                    shared_data["sgear"] = '–'

                shared_data["fuelCapacity"] = struct.unpack('f', ddata[0x48:0x48+4])[0]
                shared_data["isEV"] = False if shared_data["fuelCapacity"] > 0 else True

                if shared_data["isEV"]:
                    shared_data["fuelType"] = 'Charge'
                    shared_data["fuelRemaining"] = '{:3.0f} kWh'.format(struct.unpack('f', ddata[0x44:0x44+4])[0])
                    shared_data["fuelCapacityFormatted"] = '??? kWh'
                else:
                    shared_data["fuelType"] = 'Fuel'
                    shared_data["fuelRemaining"] = '{:3.0f} lit'.format(struct.unpack('f', ddata[0x44:0x44+4])[0])
                    shared_data["fuelCapacityFormatted"] = '{:3.0f} lit'.format(struct.unpack('f', ddata[0x48:0x48+4])[0])

                shared_data["boost"] = struct.unpack('f', ddata[0x50:0x50+4])[0] - 1
                shared_data["hasTurbo"] = True if shared_data["boost"] > -1 else False

                shared_data["tyreDiamFL"] = struct.unpack('f', ddata[0xB4:0xB4+4])[0]
                shared_data["tyreDiamFR"] = struct.unpack('f', ddata[0xB8:0xB8+4])[0]
                shared_data["tyreDiamRL"] = struct.unpack('f', ddata[0xBC:0xBC+4])[0]
                shared_data["tyreDiamRR"] = struct.unpack('f', ddata[0xC0:0xC0+4])[0]

                shared_data["tyreSpeedFL"] = abs(3.6 * shared_data["tyreDiamFL"] * struct.unpack('f', ddata[0xA4:0xA4+4])[0])
                shared_data["tyreSpeedFR"] = abs(3.6 * shared_data["tyreDiamFR"] * struct.unpack('f', ddata[0xA8:0xA8+4])[0])
                shared_data["tyreSpeedRL"] = abs(3.6 * shared_data["tyreDiamRL"] * struct.unpack('f', ddata[0xAC:0xAC+4])[0])
                shared_data["tyreSpeedRR"] = abs(3.6 * shared_data["tyreDiamRR"] * struct.unpack('f', ddata[0xB0:0xB0+4])[0])

                shared_data["carSpeed"] = 3.6 * struct.unpack('f', ddata[0x4C:0x4C+4])[0]

                if shared_data["carSpeed"] > 0:
                    shared_data["tyreSlipRatioFL"] = '{:6.2f}'.format(shared_data["tyreSpeedFL"] / shared_data["carSpeed"])
                    shared_data["tyreSlipRatioFR"] = '{:6.2f}'.format(shared_data["tyreSpeedFR"] / shared_data["carSpeed"])
                    shared_data["tyreSlipRatioRL"] = '{:6.2f}'.format(shared_data["tyreSpeedRL"] / shared_data["carSpeed"])
                    shared_data["tyreSlipRatioRR"] = '{:6.2f}'.format(shared_data["tyreSpeedRR"] / shared_data["carSpeed"])
                else:
                    shared_data["tyreSlipRatioFL"] = '  –  '
                    shared_data["tyreSlipRatioFR"] = '  –  '
                    shared_data["tyreSlipRatioRL"] = '  -  '
                    shared_data["tyreSlipRatioRR"] = '  –  '

                shared_data["timeOfDay"] = '{:>8}'.format(str(td(seconds=round(struct.unpack('i', ddata[0x80:0x80+4])[0] / 1000))))

                shared_data["curLap"] = '{:3.0f}'.format(shared_data["curlap"])
                shared_data["totalLaps"] = '{:3.0f}'.format(struct.unpack('h', ddata[0x76:0x76+2])[0])

                shared_data["curPosition"] = '{:2.0f}'.format(struct.unpack('h', ddata[0x84:0x84+2])[0])
                shared_data["totalPositions"] = '{:2.0f}'.format(struct.unpack('h', ddata[0x86:0x86+2])[0])
                shared_data["bestLapTime"] = secondsToLaptime(shared_data["bstlap"] / 1000) if shared_data["bstlap"] != -1 else ''
                shared_data["lastLapTime"] = secondsToLaptime(shared_data["lstlap"] / 1000) if shared_data["lstlap"] != -1 else ''

                shared_data["carID"] = '{:5.0f}'.format(struct.unpack('i', ddata[0x124:0x124+4])[0])

                shared_data["throttle"] = '{:3.0f}'.format(struct.unpack('B', ddata[0x91:0x91+1])[0] / 2.55)
                shared_data["rpm"] = '{:7.0f}'.format(struct.unpack('f', ddata[0x3C:0x3C+4])[0])
                shared_data["speedKPH"] = '{:7.1f}'.format(shared_data["carSpeed"])
                shared_data["rpmRevWarning"] = '{:5.0f}'.format(struct.unpack('H', ddata[0x88:0x88+2])[0])

                shared_data["brake"] = '{:3.0f}'.format(struct.unpack('B', ddata[0x92:0x92+1])[0] / 2.55)
                shared_data["actualGear"] = shared_data["cgear"]
                shared_data["suggestedGear"] = shared_data["sgear"]

                shared_data["boostFormatted"] = '{:7.2f}'.format(shared_data["boost"]) if shared_data["hasTurbo"] else '–'

                shared_data["rpmRevLimiter"] = '{:5.0f}'.format(struct.unpack('H', ddata[0x8A:0x8A+2])[0])
                shared_data["estTopSpeed"] = '{:5.0f}'.format(struct.unpack('h', ddata[0x8C:0x8C+2])[0])

                shared_data["clutch"] = '{:5.3f}'.format(struct.unpack('f', ddata[0xF4:0xF4+4])[0])
                shared_data["clutchEngaged"] = '{:5.3f}'.format(struct.unpack('f', ddata[0xF8:0xF8+4])[0])
                shared_data["rpmAfterClutch"] = '{:7.0f}'.format(struct.unpack('f', ddata[0xFC:0xFC+4])[0])

                shared_data["oilTemp"] = '{:6.1f}'.format(struct.unpack('f', ddata[0x5C:0x5C+4])[0])
                shared_data["waterTemp"] = '{:6.1f}'.format(struct.unpack('f', ddata[0x58:0x58+4])[0])

                shared_data["oilPressure"] = '{:6.2f}'.format(struct.unpack('f', ddata[0x54:0x54+4])[0])
                shared_data["rideHeight"] = '{:6.0f}'.format(1000 * struct.unpack('f', ddata[0x38:0x38+4])[0])

                print(shared_data)

                shared_data["tyreTempFL"] = '{:6.1f}'.format(struct.unpack('f', ddata[0x60:0x60+4])[0])
                shared_data["tyreTempFR"] = '{:6.1f}'.format(struct.unpack('f', ddata[0x64:0x64+4])[0])
                shared_data["tyreDiamFL"] = '{:6.1f}'.format(200 * shared_data["tyreDiamFL"])
                shared_data["tyreDiamFR"] = '{:6.1f}'.format(200 * shared_data["tyreDiamFR"])

                shared_data["tyreSpeedFL"] = '{:6.1f}'.format(shared_data["tyreSpeedFL"])
                shared_data["tyreSpeedFR"] = '{:6.1f}'.format(shared_data["tyreSpeedFR"])
                shared_data["suspensionFL"] = '{:6.2f}'.format(struct.unpack('f', ddata[0x98:0x98+4])[0])
                shared_data["suspensionFR"] = '{:6.2f}'.format(struct.unpack('f', ddata[0x9C:0x9C+4])[0])

                shared_data["steeringAngle"] = '{:6.1f}'.format(struct.unpack('f', ddata[0x68:0x68+4])[0])

                time.sleep(0.01)

        except Exception as e:
            print(f'Exception: {e}')
            time.sleep(1)

# Define a route to expose the telemetry data
@app.route('/telemetry', methods=['GET'])
def get_telemetry():
    print(shared_data)
    return jsonify(shared_data)

# Start the thread to update shared_data
thread = threading.Thread(target=update_shared_data)
thread.daemon = True
thread.start()

# Start the Flask server
if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
