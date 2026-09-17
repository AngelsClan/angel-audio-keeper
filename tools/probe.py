"""Read-only endpoint inspection by default; explicit --silent-test runs zero samples.

Does not install or access NVDA. Silent mode never enables power requests.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("aak")
pkg.__path__ = [str(ROOT / "addon/globalPlugins/angelAudioKeeper")]
sys.modules["aak"] = pkg
from aak.wasapi import AudioSystem, RenderStream
from aak.noise import Noise

parser = argparse.ArgumentParser()
parser.add_argument("--silent-test", type=int, default=0, metavar="SECONDS")
args = parser.parse_args()
if not 0 <= args.silent_test <= 600:
    parser.error("Silent test must be between 0 and 600 seconds")
system = AudioSystem()
try:
    print(json.dumps({"devices": system.devices(), "default": system.default_id()}, indent=2))
    stream = RenderStream(system, initialize=bool(args.silent_test))
    try:
        print(json.dumps({"name": stream.name, "format": stream.format.__dict__,
                          "bufferFrames": stream.capacity}, indent=2))
        if args.silent_test:
            noise = Noise(stream.format, 0)
            stream.write(noise.take(stream.capacity))
            stream.start()
            frames = stream.capacity
            blocks = 1
            empty = 0
            end = time.monotonic() + args.silent_test
            while time.monotonic() < end:
                available = stream.available()
                if available:
                    empty += available == stream.capacity
                    stream.write(noise.take(available))
                    frames += available
                    blocks += 1
                time.sleep(0.02)
            print(json.dumps({"silentTestSeconds": args.silent_test, "submittedFrames": frames,
                              "submittedBuffers": blocks, "emptyRefills": empty}))
    finally:
        stream.close()
finally:
    system.close()
