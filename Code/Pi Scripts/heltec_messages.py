"""
Parse JSON messages from the camera-side Heltec.

The Heltec emits several message types (position updates, heartbeats, command
acks, status replies, errors). This module pulls position data out of position
updates and ignores everything else.
"""

import json
from typing import Optional


def extract_positions(line: str) -> Optional[dict]:
    print("iN EXTRACTION FUNCTION")
    """Parse one JSON line from the Heltec and pull out surfer + camera positions.

    Returns a dict with keys:
      timestamp_ms  - sender's millis() at TX time (wraps every ~49 days)
      surfer        - {lat, lon, alt_m, speed_mps, heading_deg, sats, hdop}
      camera        - {lat, lon, alt_m}
      rssi_dbm      - link RSSI at the receiver, dBm
      snr_db        - link SNR, dB

    Returns None if the line isn't a position update:
      - invalid JSON
      - heartbeat ({"hb": ...})
      - command ack ({"ack": ...})
      - status reply ({"status": ...})
      - error ({"err": ...})
      - camera fix not yet valid

    Example:
        from heltec_messages import extract_positions
        pos = extract_positions(serial_line)
        if pos:
            surfer_lat = pos['surfer']['lat']
            camera_lat = pos['camera']['lat']
    """
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        print("JSON decoder error")
        return None

    surfer = msg.get("surfer")
    camera = msg.get("camera")
    if not isinstance(surfer, dict) or not isinstance(camera, dict):
        print("no instances")
        return None
    if not camera.get("valid"):
        print("camera get was not valid")
        return None

    link = msg.get("link") or {}

    return {
        "timestamp_ms": msg.get("ts"),
        "surfer": {
            "lat":           surfer.get("lat"),
            "lon":           surfer.get("lon"),
            "alt_m":         surfer.get("alt"),
            "speed_mps":     surfer.get("spd"),
            "heading_deg":   surfer.get("hdg"),
            "sats":          surfer.get("sats"),
            "hdop":          surfer.get("hdop"),
        },
        "camera": {
            "lat":   camera.get("lat"),
            "lon":   camera.get("lon"),
            "alt_m": camera.get("alt"),
        },
        "rssi_dbm": link.get("rssi"),
        "snr_db":   link.get("snr"),
    }


if __name__ == "__main__":
    # Demo: feed example messages through the parser and print results
    examples = [
        # Real position update
        '{"ts":583122,"surfer":{"lat":-34.067888,"lon":151.1161023,"alt":74.0,'
        '"spd":0.24,"hdg":0.0,"sats":7,"hdop":1.8},'
        '"camera":{"valid":1,"lat":-34.0678452,"lon":151.1161165,"alt":55.2},'
        '"link":{"rssi":-53.0,"snr":11.0}}',

        # Heartbeat - should return None
        '{"hb":{"up":536,"pkt":1023,"cmd":0}}',

        # Ack - should return None
        '{"ack":"M","base":200,"hinge":0}',

        # Garbage - should return None
        'not json at all',

        # Position with camera not yet valid - should return None
        '{"surfer":{"lat":1,"lon":2,"alt":3},"camera":{"valid":0}}',
    ]

    for line in examples:
        result = extract_positions(line)
        print(f"\nInput:  {line[:90]}{'...' if len(line) > 90 else ''}")
        print(f"Result: {result}")
