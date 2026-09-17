"""Explicit silent Windows-engine qualification, never installs or captures audio."""
import ctypes as C
import json
from pathlib import Path
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("aak")
pkg.__path__ = [str(ROOT / "addon/globalPlugins/angelAudioKeeper")]
sys.modules["aak"] = pkg
from aak.engine import Engine, Settings, make_logger


class Memory(C.Structure):
    _fields_ = [("cb", C.c_uint32), ("faults", C.c_uint32)] + [
        (key, C.c_size_t) for key in ("peakWorking", "working", "peakPaged", "paged",
                                    "peakNonPaged", "nonPaged", "pagefile", "peakPagefile")]


def memory_bytes():
    value = Memory()
    value.cb = C.sizeof(value)
    kernel = C.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = C.c_void_p
    function = C.WinDLL("psapi").GetProcessMemoryInfo
    function.argtypes = [C.c_void_p, C.POINTER(Memory), C.c_uint32]
    function.restype = C.c_int
    if not function(kernel.GetCurrentProcess(), C.byref(value), C.sizeof(value)):
        raise OSError("Unable to inspect test process memory")
    return value.working


target = ROOT / "test-results"
logger = make_logger(target)
engine = Engine(logger)
started = time.monotonic()
cpu_start = time.process_time()
samples = []
try:
    engine.update(Settings(enabled=True, volume=0))
    for index in range(18):
        time.sleep(10)
        status = engine.snapshot()
        samples.append(dict(seconds=round(time.monotonic() - started, 2),
                            workingBytes=memory_bytes(), state=status["state"],
                            frames=status["frames"], buffers=status["buffers"],
                            empty=status["emptyBuffers"], recoveries=status["recoveries"]))
        print(json.dumps(samples[-1]), flush=True)
        if status["state"] != "Playing" or status["lastError"]:
            raise RuntimeError(f"Silent qualification failed: {status}")
        # Toggle detailed logging live without reopening the audio device.
        if index in (3, 8):
            engine.update(Settings(enabled=True, volume=0, debug=index == 3))
    final = engine.snapshot()
    if final["recoveries"] != 0:
        raise RuntimeError("Unexpected reopen during live logging change")
finally:
    stopped = engine.stop()
    for handler in logger.handlers:
        handler.close()
result = dict(durationSeconds=time.monotonic() - started,
              cpuSeconds=time.process_time() - cpu_start, stoppedCleanly=stopped,
              status=final, samples=samples, note="Digital silence only; does not establish audible efficacy")
(target / "windows-engine-qualification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k not in ("samples", "status")}), flush=True)
if not stopped:
    raise SystemExit(1)
