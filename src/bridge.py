"""
TouchDesigner Setup — OSC In CHOP
----------------------------------
1. In TouchDesigner, press Tab and add an 'OSC In' CHOP.
2. In its parameters, set:
      Network Port : 7000
      Local Address: 127.0.0.1  (or leave blank to listen on all interfaces)
3. Cook the CHOP (set to 'Always' cook if you want live updates).
4. Each OSC address this script sends becomes a named channel inside that CHOP:
      /td/color/r      -> red   (0-255)
      /td/color/g      -> green (0-255)
      /td/color/b      -> blue  (0-255)
      /td/angularity   -> float 0.0-1.0
      /td/noise        -> float 0.0-1.0
      /td/audio_prompt -> string (connect downstream to a 'DAT' for text)
5. To read the audio prompt string, add an 'OSC In' DAT (not CHOP) with the
   same port — DATs handle string payloads; CHOPs handle numeric ones.
"""

import sys
import time
import random
from pathlib import Path

# Allow running this file directly from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pythonosc import udp_client

from src.brain import TasteMapper
from src.prompt_engine import generate_bundle

OSC_HOST = "127.0.0.1"
OSC_PORT = 7000

_mapper = TasteMapper()
_client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)


def send_osc_data(visual: dict, audio_prompt: str) -> None:
    """Send pre-computed visual params and audio prompt over OSC."""
    r, g, b = visual["color_rgb"]
    _client.send_message("/td/color/r", float(r))
    _client.send_message("/td/color/g", float(g))
    _client.send_message("/td/color/b", float(b))
    _client.send_message("/td/angularity", visual["shape_angularity"])
    _client.send_message("/td/noise", visual["noise_level"])
    _client.send_message("/td/audio_prompt", audio_prompt)

    print(
        f"[OSC] RGB({r:3d},{g:3d},{b:3d}) | "
        f"angularity={visual['shape_angularity']:.3f} | "
        f"noise={visual['noise_level']:.3f}\n"
        f"      prompt: {audio_prompt}\n"
    )


def send_to_touchdesigner(raw_data: dict) -> None:
    """Process one set of sensor readings and fire OSC messages to TouchDesigner."""
    intensities = _mapper.process_data(
        raw_ph=raw_data["ph"],
        raw_temp=raw_data["temp"],
        raw_brix=raw_data["brix"],
        raw_spicy=raw_data["spicy"],
        raw_co2=raw_data.get("co2",   0.0),
        raw_ibu=raw_data.get("ibu",   0.0),
        raw_salt=raw_data.get("salt",  0.0),
        raw_umami=raw_data.get("umami", 0.0),
    )
    visual = _mapper.get_visual_params(intensities)
    bundle = generate_bundle(intensities)
    send_osc_data(visual, bundle.master_prompt)


if __name__ == "__main__":
    print(f"Sending OSC to {OSC_HOST}:{OSC_PORT} — Ctrl+C to stop.\n")

    # Baseline reading: slightly sour-sweet sparkling citrus drink
    BASE  = {"ph": 3.2, "temp": 20.0, "brix": 12.0, "spicy": 500.0,
             "co2": 3.0, "ibu": 5.0, "salt": 0.5, "umami": 0.0}

    # Simulated sensor noise ranges (±delta around the baseline)
    NOISE = {"ph": 0.15, "temp": 2.0, "brix": 1.0, "spicy": 200.0,
             "co2": 0.2, "ibu": 1.0, "salt": 0.1, "umami": 0.0}

    try:
        while True:
            # Add a small random walk to each sensor value to mimic live readings
            jittered = {
                key: BASE[key] + random.uniform(-NOISE[key], NOISE[key])
                for key in BASE
            }
            send_to_touchdesigner(jittered)
            time.sleep(2)
    except KeyboardInterrupt:
        print("Stopped.")
