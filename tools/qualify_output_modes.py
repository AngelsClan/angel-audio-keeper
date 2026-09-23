"""Short, silent native WASAPI check of all/multiple/follow-NVDA modes."""
from pathlib import Path
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("aak")
pkg.__path__ = [str(ROOT / "addon/globalPlugins/angelAudioKeeper")]
sys.modules["aak"] = pkg
from aak.engine import Engine, Settings, make_logger
from aak.storage import MODE_ALL, MODE_DEVICES, MODE_NVDA
from aak.wasapi import AudioSystem

logger = make_logger(ROOT / "test-results")
system = AudioSystem()
try:
    device_ids = [identifier for identifier, _ in system.devices()]
finally:
    system.close()

engine = Engine(logger)
try:
    for mode, selected, nvda in (
            (MODE_ALL, (), ""),
            (MODE_DEVICES, tuple(device_ids[:2]), ""),
            (MODE_NVDA, (), device_ids[0] if device_ids else "default")):
        engine.update(Settings(enabled=True, mode=mode, devices=selected,
                               nvda_device=nvda, volume=0))
        until = time.monotonic() + 6
        expected = min(len(device_ids), 16) if mode == MODE_ALL else (
            len(selected) if mode == MODE_DEVICES else int(bool(device_ids)))
        while time.monotonic() < until:
            state = engine.snapshot()
            if state["activeOutputs"] == expected and state["outputMode"]:
                break
            time.sleep(.05)
        else:
            raise RuntimeError(f"{mode} did not start {expected} silent streams: {state['state']}")
        print(f"{mode}: active={state['activeOutputs']} selected={state['selectedOutputs']} "
              f"buffers={state['buffers']} errors={bool(state['lastError'])}", flush=True)
        time.sleep(.5)
finally:
    stopped = engine.stop()
    for handler in logger.handlers:
        handler.close()
    if not stopped:
        raise RuntimeError("Audio worker did not stop cleanly")
