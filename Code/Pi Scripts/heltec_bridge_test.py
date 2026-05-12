#!/usr/bin/env python3
"""
Heltec <-> Pi bridge test.

Reads lines from the camera-side Heltec over USB serial and prints them.
Lets you type commands at stdin which get sent to the Heltec.

Commands the CameraSideTracker.ino sketch understands:
  M 200 0     base move 200 steps, hinges 0
  M 0 100     base 0, hingeRight +100, hingeLeft -100 (mirrored)
  S           status query (returns {"status":{...}})
  quit / q    exit the script

Usage:
  python3 heltec_bridge_test.py                 # auto-detect port
  python3 heltec_bridge_test.py /dev/ttyUSB0    # explicit port
"""

import glob
import json
import queue
import select
import serial
import sys
import threading
import time
import math
from datetime import datetime

from heltec_messages import extract_positions


def find_port():
    """Look in the usual places on Linux/Pi and macOS."""
    candidates = sorted(
        glob.glob('/dev/ttyUSB*')
        + glob.glob('/dev/ttyACM*')
        + glob.glob('/dev/cu.usbmodem*')
        + glob.glob('/dev/cu.SLAB_USBtoUART*')
        + glob.glob('/dev/cu.usbserial*')
    )
    if not candidates:
        sys.exit("No serial port found. Plug in the Heltec or pass a port as argv[1].")
    return candidates[0]


def reader_thread(ser, out_q):
    """Continuously read bytes, split on newlines, push complete lines onto the queue."""
    buf = bytearray()
    while True:
        try:
            chunk = ser.read(256)
        except serial.SerialException as e:
            out_q.put(f"[serial error] {e}")
            return
        if not chunk:
            continue
        buf.extend(chunk)
        while b'\n' in buf:
            line, _, buf = buf.partition(b'\n')
            out_q.put(line.decode('utf-8', errors='replace').strip())


def pretty(line):
    """Compact JSON for one-line display; raw text if not JSON."""
    try:
        return json.dumps(json.loads(line), separators=(',', ':'))
    except json.JSONDecodeError:
        return line
    

def distance_camera_to_surfer_haversine(camera_lat, camera_lon, surfer_lat, surfer_lon):
    earths_radius = 6371000.0 # in meters, may have to change?
    camera_lat, camera_lon, surfer_lat, surfer_lon = map(math.radians, [camera_lat, camera_lon, surfer_lat, surfer_lon])

    latitude_difference = camera_lat - surfer_lat
    longitude_difference = camera_lon - surfer_lon

    a = math.sin(latitude_difference / 2)**2 + math.cos(camera_lat) * math.cos(surfer_lat) * math.sin(longitude_difference / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = earths_radius * c

    return distance

def bearing_camera_to_surfer(camera_lat, camera_lon, surfer_lat, surfer_lon):
    """Initial great-circle bearing from camera to surfer, in degrees (0 = N, 90 = E)."""
    # Convert everything to radians for the trig
    phi1 = math.radians(camera_lat)   # start latitude
    phi2 = math.radians(surfer_lat)   # end latitude
    delta_lambda = math.radians(surfer_lon - camera_lon)  # longitude difference

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)

    theta = math.atan2(y, x)                       # radians, -pi to +pi
    return (math.degrees(theta) + 360) % 360       # compass bearing, 0 to 360



def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    print(f"Opening {port} @ 115200 baud")
    ser = serial.Serial(port, 115200, timeout=0.1)
    time.sleep(2)  # ESP32 auto-resets when DTR drops; wait for boot
    ser.reset_input_buffer()
    print("Type a command and press enter (or 'quit'):\n")

    incoming = queue.Queue()
    threading.Thread(target=reader_thread, args=(ser, incoming), daemon=True).start()

    rx = tx = 0
    try:
        while True:
            # Drain anything the Heltec sent
            while not incoming.empty():
                line = incoming.get()
                rx += 1
                ts = f"{datetime.now():%H:%M:%S}"

                positions = extract_positions(line)
                if positions:
                    surfer, camera = positions['surfer'], positions['camera']
                    camera_lat, camera_lon, surfer_la, surfer_lon = camera['lat'], camera['lon'], surfer['lat'], surfer['lon']


                    print(
                        f"[{ts}] POS  "
                        f"surfer=({surfer['lat']:.6f},{surfer['lon']:.6f}) "
                        f"camera=({camera['lat']:.6f},{camera['lon']:.6f}) "
                        f"rssi={positions['rssi_dbm']:.0f}dBm  snr={positions['snr_db']:.1f}dB"
                    )
                else:
                    # Heartbeat, ack, status, error, or garbage - print as-is
                    print(f"[{ts}] RX: {pretty(line)}")
                    print("Nothing coming through")
            
            

            # Non-blocking check for typed input
            if select.select([sys.stdin], [], [], 0.1)[0]:
                cmd = sys.stdin.readline().rstrip('\n')
                if not cmd:
                    continue
                if cmd.lower() in ('quit', 'exit', 'q'):
                    break
                ser.write((cmd + '\n').encode())
                tx += 1
                print(f"[{datetime.now():%H:%M:%S}] TX: {cmd}")
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print(f"\nClosed. RX={rx}, TX={tx}")


if __name__ == '__main__':
    main()
