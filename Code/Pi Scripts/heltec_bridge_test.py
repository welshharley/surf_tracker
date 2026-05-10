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
from datetime import datetime


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
                print(f"[{datetime.now():%H:%M:%S}] RX: {pretty(line)}")

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
