import signal
from datetime import datetime as dt
from datetime import timedelta as td
import socket
import struct
import time
import sys
import threading
from salsa20 import Salsa20_xor
from flask import Flask, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app)

# ports for send and receive data
SendPort = 33739
ReceivePort = 33740

data_storage = {}

# data stream decoding
def salsa20_dec(dat):
    KEY = b'Simulator Interface Packet GT7 ver 0.0'
    oiv = dat[0x40:0x44]
    iv1 = int.from_bytes(oiv, byteorder='little')
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

def udp_listener(ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', ReceivePort))
    s.settimeout(10)

    send_hb(s, ip)

    prevlap = -1
    pktid = 0
    pknt = 0
    while True:
        try:
            data, address = s.recvfrom(4096)
            print("Received data:", data) 
            pknt += 1
            ddata = salsa20_dec(data)
            print(ddata)
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
                    data_storage['curLapTime'] = secondsToLaptime(curLapTime.total_seconds())
                else:
                    curLapTime = 0
                    data_storage['curLapTime'] = ''

                cgear = struct.unpack('B', ddata[0x90:0x90+1])[0] & 0b00001111
                sgear = struct.unpack('B', ddata[0x90:0x90+1])[0] >> 4
                if cgear < 1:
                    cgear = 'R'
                if sgear > 14:
                    sgear = '–'

                print("Current Gear:", cgear)
                print("Suggested Gear:", sgear)


                fuelCapacity = struct.unpack('f', ddata[0x48:0x48+4])[0]
                isEV = fuelCapacity <= 0
                if isEV:
                    data_storage['fuel_type'] = 'Charge'
                    data_storage['fuel_remaining'] = '{:3.0f} kWh'.format(struct.unpack('f', ddata[0x44:0x44+4])[0])
                    data_storage['fuel_capacity'] = '??? kWh'
                else:
                    data_storage['fuel_type'] = 'Fuel'
                    data_storage['fuel_remaining'] = '{:3.0f} lit'.format(struct.unpack('f', ddata[0x44:0x44+4])[0])
                    data_storage['fuel_capacity'] = '{:3.0f} lit'.format(fuelCapacity)

                boost = struct.unpack('f', ddata[0x50:0x50+4])[0] - 1
                hasTurbo = boost > -1

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

                data_storage['time_of_day'] = str(td(seconds=round(struct.unpack('i', ddata[0x80:0x80+4])[0] / 1000)))
                data_storage['curLap'] = '{:3.0f}'.format(curlap)
                data_storage['totalLaps'] = '{:3.0f}'.format(struct.unpack('h', ddata[0x76:0x76+2])[0])
                data_storage['curPos'] = '{:2.0f}'.format(struct.unpack('h', ddata[0x84:0x84+2])[0])
                data_storage['totalPos'] = '{:2.0f}'.format(struct.unpack('h', ddata[0x86:0x86+2])[0])

                if bstlap != -1:
                    data_storage['bestLapTime'] = secondsToLaptime(bstlap / 1000)
                else:
                    data_storage['bestLapTime'] = ''

                if lstlap != -1:
                    data_storage['lastLapTime'] = secondsToLaptime(lstlap / 1000)
                else:
                    data_storage['lastLapTime'] = ''

                data_storage['carID'] = '{:5.0f}'.format(struct.unpack('i', ddata[0x124:0x124+4])[0])
                data_storage['throttle'] = '{:3.0f}'.format(struct.unpack('B', ddata[0x91:0x91+1])[0] / 2.55)
                data_storage['rpm'] = '{:7.0f}'.format(struct.unpack('f', ddata[0x3C:0x3C+4])[0])
                data_storage['speed_kph'] = '{:7.1f}'.format(carSpeed)
                data_storage['rpm_warning'] = '{:5.0f}'.format(struct.unpack('H', ddata[0x88:0x88+2])[0])
                data_storage['brake'] = '{:3.0f}'.format(struct.unpack('B', ddata[0x92:0x92+1])[0] / 2.55)
                data_storage['actual_gear'] = '{}'.format(cgear)
                data_storage['suggested_gear'] = '{}'.format(sgear)

                if hasTurbo:
                    data_storage['boost'] = '{:7.2f}'.format(boost)
                else:
                    data_storage['boost'] = '–'

                data_storage['rpm_limiter'] = '{:5.0f}'.format(struct.unpack('H', ddata[0x8A:0x8A+2])[0])
                data_storage['est_top_speed'] = '{:5.0f}'.format(struct.unpack('h', ddata[0x8C:0x8C+2])[0])
                data_storage['clutch'] = '{:5.3f}'.format(struct.unpack('f', ddata[0xF4:0xF4+4])[0])
                data_storage['clutch_engaged'] = '{:5.3f}'.format(struct.unpack('f', ddata[0xF8:0xF8+4])[0])
                data_storage['rpm_after_clutch'] = '{:7.0f}'.format(struct.unpack('f', ddata[0xFC:0xFC+4])[0])
                data_storage['oil_temp'] = '{:6.1f}'.format(struct.unpack('f', ddata[0x5C:0x5C+4])[0])
                data_storage['water_temp'] = '{:6.1f}'.format(struct.unpack('f', ddata[0x58:0x58+4])[0])
                data_storage['oil_pressure'] = '{:6.2f}'.format(struct.unpack('f', ddata[0x54:0x54+4])[0])
                data_storage['ride_height'] = '{:6.0f}'.format(1000 * struct.unpack('f', ddata[0x38:0x38+4])[0])

                data_storage['tyre_temp_FL'] = '{:6.1f}'.format(struct.unpack('f', ddata[0x60:0x60+4])[0])
                data_storage['tyre_temp_FR'] = '{:6.1f}'.format(struct.unpack('f', ddata[0x64:0x64+4])[0])
                data_storage['tyre_diam_FL'] = '{:6.1f}'.format(1000 * tyreDiamFL)
                data_storage['tyre_diam_FR'] = '{:6.1f}'.format(1000 * tyreDiamFR)
                data_storage['tyre_slip_ratio_FL'] = tyreSlipRatioFL
                data_storage['tyre_slip_ratio_FR'] = tyreSlipRatioFR

                data_storage['tyre_temp_RL'] = '{:6.1f}'.format(struct.unpack('f', ddata[0x68:0x68+4])[0])
                data_storage['tyre_temp_RR'] = '{:6.1f}'.format(struct.unpack('f', ddata[0x6C:0x6C+4])[0])
                data_storage['tyre_diam_RL'] = '{:6.1f}'.format(1000 * tyreDiamRL)
                data_storage['tyre_diam_RR'] = '{:6.1f}'.format(1000 * tyreDiamRR)
                data_storage['tyre_slip_ratio_RL'] = tyreSlipRatioRL
                data_storage['tyre_slip_ratio_RR'] = tyreSlipRatioRR

                socketio.emit('telemetry', data_storage)
                print(data_storage)
        except Exception as e:
            print(e)
            break

def send_hb(s, ip):
    while True:
        s.sendto('A'.encode('utf-8'), (ip, SendPort))
        time.sleep(1)

@app.route('/')
def index():
    return jsonify(data_storage)

if __name__ == '__main__':
    if len(sys.argv) == 2:
        ip = sys.argv[1]
    else:
        print('Run like: python3 server.py <playstation-ip>')
        sys.exit(1)

    threading.Thread(target=udp_listener, args=(ip,)).start()
    socketio.run(app, host='0.0.0.0', port=5000)


