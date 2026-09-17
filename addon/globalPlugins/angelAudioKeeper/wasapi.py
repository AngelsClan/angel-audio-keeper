"""Minimal Windows Core Audio shared-render wrapper; owns COM on calling thread.

All COM pointers, audio buffers and execution-state requests stay on that worker.
No capture interfaces, exclusive mode, master-volume or enhancement changes.
"""
import ctypes as C
from ctypes import wintypes as W
import struct
import uuid
from .noise import AudioFormat

HRESULT = C.c_int32
UINT = C.c_uint32
PTR = C.c_void_p
_OLE = C.WinDLL("ole32")
_KERNEL = C.WinDLL("kernel32", use_last_error=True)
_USER = C.WinDLL("user32")


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


class PropertyKey(C.Structure):
    _fields_ = [("fmtid", GUID), ("pid", UINT)]


class VariantValue(C.Union):
    # PROPVARIANT includes a counted array: ULONG plus an aligned pointer.
    _fields_ = [("ptr", PTR), ("raw", C.c_ubyte * (16 if C.sizeof(PTR) == 8 else 8))]


class PropVariant(C.Structure):
    _fields_ = [("vt", C.c_uint16), ("r1", C.c_uint16),
                ("r2", C.c_uint16), ("r3", C.c_uint16), ("value", VariantValue)]


def check(hr, operation):
    if hr < 0:
        raise OSError(f"{operation}: HRESULT 0x{hr & 0xffffffff:08X}")


def call(obj, index, argtypes, *args, result=HRESULT):
    if not obj:
        raise RuntimeError("COM object is closed")
    table = C.cast(obj, C.POINTER(C.POINTER(PTR))).contents
    method = C.WINFUNCTYPE(result, PTR, *argtypes)(table[index])
    return method(obj, *args)


def release(obj):
    if obj:
        call(obj, 2, [], result=UINT)


class AudioSystem:
    def __init__(self):
        self.ole = _OLE
        self.ole.CoInitializeEx.argtypes = [PTR, UINT]
        self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoCreateInstance.argtypes = [C.POINTER(GUID), PTR, UINT, C.POINTER(GUID), C.POINTER(PTR)]
        self.ole.CoCreateInstance.restype = HRESULT
        self.ole.CoTaskMemFree.argtypes = [PTR]
        self.ole.CoTaskMemFree.restype = None
        self.ole.PropVariantClear.argtypes = [C.POINTER(PropVariant)]
        self.ole.PropVariantClear.restype = HRESULT
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.enumerator = PTR()
        self.initialized = False
        # STA also matches Microsoft's Windows 8 IAudioClient first-use guidance.
        check(self.ole.CoInitializeEx(None, 2), "CoInitializeEx")
        self.initialized = True
        try:
            check(self.ole.CoCreateInstance(
                C.byref(GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")), None, 1,
                C.byref(GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")),
                C.byref(self.enumerator)), "Create audio enumerator")
        except Exception:
            self.close()
            raise

    def device(self, device_id=""):
        device = PTR()
        if device_id:
            check(call(self.enumerator, 5, [W.LPCWSTR, C.POINTER(PTR)],
                       device_id, C.byref(device)), "Get selected device")
        else:
            check(call(self.enumerator, 4, [C.c_int, C.c_int, C.POINTER(PTR)],
                       0, 1, C.byref(device)), "Get default multimedia output")
        return device

    def identity(self, device):
        identifier = self.device_id(device)
        name = identifier
        store = PTR()
        variant = PropVariant()
        try:
            check(call(device, 4, [UINT, C.POINTER(PTR)], 0, C.byref(store)), "Open properties")
            key = PropertyKey(GUID("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)
            check(call(store, 5, [C.POINTER(PropertyKey), C.POINTER(PropVariant)],
                       C.byref(key), C.byref(variant)), "Get output name")
            if variant.vt == 31 and variant.value.ptr:
                name = C.wstring_at(variant.value.ptr)
        finally:
            self.ole.PropVariantClear(C.byref(variant))
            release(store)
        return identifier, name

    def device_id(self, device):
        value = PTR()
        check(call(device, 5, [C.POINTER(PTR)], C.byref(value)), "Get device ID")
        try:
            identifier = C.wstring_at(value)
        finally:
            self.ole.CoTaskMemFree(value)
        return identifier

    def devices(self):
        collection = PTR()
        try:
            check(call(self.enumerator, 3, [C.c_int, UINT, C.POINTER(PTR)],
                       0, 1, C.byref(collection)), "List active render devices")
            count = UINT()
            check(call(collection, 3, [C.POINTER(UINT)], C.byref(count)), "Count devices")
            result = []
            for index in range(count.value):
                device = PTR()
                try:
                    check(call(collection, 4, [UINT, C.POINTER(PTR)], index, C.byref(device)), "Get output")
                    result.append(self.identity(device))
                finally:
                    release(device)
            return result
        finally:
            release(collection)

    def default_id(self):
        device = self.device()
        try:
            return self.device_id(device)
        finally:
            release(device)

    def close(self):
        release(self.enumerator)
        self.enumerator = PTR()
        if self.initialized:
            self.ole.CoUninitialize()
            self.initialized = False


class RenderStream:
    def __init__(self, system, device_id="", initialize=True):
        self.system = system
        self.device = PTR()
        self.client = PTR()
        self.render = PTR()
        self.stream_volume = PTR()
        self.mix = PTR()
        self.started = False
        try:
            self.device = system.device(device_id)
            self.device_id, self.name = system.identity(self.device)
            check(call(self.device, 3, [C.POINTER(GUID), UINT, PTR, C.POINTER(PTR)],
                       C.byref(GUID("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2")),
                       1, None, C.byref(self.client)), "Activate IAudioClient")
            check(call(self.client, 8, [C.POINTER(PTR)], C.byref(self.mix)), "Get mix format")
            header = C.string_at(self.mix, 18)
            tag, channels, rate, avg, align, bits, extra = struct.unpack("<HHIIHHH", header)
            mask = 0
            valid = bits
            if tag == 0xfffe:
                if extra < 22:
                    raise ValueError("Truncated extensible audio format")
                ext = C.string_at(self.mix.value + 18, 22)
                valid, mask = struct.unpack_from("<HI", ext)
                subtype = uuid.UUID(bytes_le=ext[6:22])
                if subtype == uuid.UUID("00000003-0000-0010-8000-00aa00389b71"):
                    tag = 3
                elif subtype == uuid.UUID("00000001-0000-0010-8000-00aa00389b71"):
                    tag = 1
                else:
                    raise ValueError(f"Unsupported audio subtype {subtype}")
            if tag not in (1, 3):
                raise ValueError(f"Unsupported mix format tag {tag}")
            self.format = AudioFormat(rate, channels, bits, tag == 3, mask, valid)
            if align != self.format.frame_bytes or avg != rate * align:
                raise ValueError("Inconsistent device block alignment")
            self.capacity = 0
            if initialize:
                # Shared mode, no special conversion, 200 ms requested buffer.
                check(call(self.client, 3, [C.c_int, UINT, C.c_int64, C.c_int64, PTR, PTR],
                           0, 0, 2_000_000, 0, self.mix, None), "Initialize shared render")
                frames = UINT()
                check(call(self.client, 4, [C.POINTER(UINT)], C.byref(frames)), "Get buffer size")
                self.capacity = frames.value
                if not 0 < self.capacity <= rate * 2:
                    raise ValueError("Unexpected render buffer capacity")
                check(call(self.client, 14, [C.POINTER(GUID), C.POINTER(PTR)],
                           C.byref(GUID("F294ACFC-3146-4483-A7BF-ADDCA7C260E2")),
                           C.byref(self.render)), "Get render service")
                check(call(self.client, 14, [C.POINTER(GUID), C.POINTER(PTR)],
                           C.byref(GUID("93014887-242D-4068-8A15-CF5E93B90FE3")),
                           C.byref(self.stream_volume)), "Get stream-only volume service")
                count = UINT()
                check(call(self.stream_volume, 3, [C.POINTER(UINT)], C.byref(count)), "Get stream channel count")
                if count.value != self.format.channels:
                    raise ValueError("Stream volume channel count does not match mix format")
        except Exception:
            self.close()
            raise

    def available(self):
        padding = UINT()
        check(call(self.client, 6, [C.POINTER(UINT)], C.byref(padding)), "Get current padding")
        if padding.value > self.capacity:
            raise RuntimeError("Invalid audio buffer padding")
        return self.capacity - padding.value

    def write(self, data):
        if len(data) % self.format.frame_bytes:
            raise ValueError("Audio data is not frame aligned")
        frames = len(data) // self.format.frame_bytes
        if not frames:
            return
        if frames > self.capacity:
            raise ValueError("Audio block exceeds buffer capacity")
        pointer = PTR()
        check(call(self.render, 3, [UINT, C.POINTER(PTR)], frames, C.byref(pointer)), "Get render buffer")
        try:
            C.memmove(pointer, data, len(data))
        except Exception:
            call(self.render, 4, [UINT, UINT], frames, 2)  # AUDCLNT_BUFFERFLAGS_SILENT
            raise
        check(call(self.render, 4, [UINT, UINT], frames, 0), "Release render buffer")

    def start(self):
        check(call(self.client, 10, []), "Start audio")
        self.started = True

    def set_volume(self, volume):
        # This affects only this render stream, not NVDA's other streams or mixer.
        level = max(0, min(100, int(volume))) / 100.0
        levels = (C.c_float * self.format.channels)(*([level] * self.format.channels))
        check(call(self.stream_volume, 6, [UINT, C.POINTER(C.c_float)],
                   self.format.channels, levels), "Set all stream channel volumes")

    def close(self):
        if self.started and self.client:
            call(self.client, 11, [])
            self.started = False
        release(self.render)
        release(self.stream_volume)
        release(self.client)
        release(self.device)
        self.render = self.client = self.device = PTR()
        self.stream_volume = PTR()
        if self.mix:
            self.system.ole.CoTaskMemFree(self.mix)
            self.mix = PTR()


def set_awake(system=False, display=False):
    function = _KERNEL.SetThreadExecutionState
    function.argtypes = [UINT]
    function.restype = UINT
    flags = 0x80000000 | (1 if system else 0) | (2 if display else 0)
    if not function(flags):
        raise OSError("SetThreadExecutionState did not accept the requested state")


def pump_messages():
    """Service STA messages without dispatching any NVDA/UI-thread messages."""
    user = _USER
    peek = user.PeekMessageW
    peek.argtypes = [C.POINTER(W.MSG), W.HWND, UINT, UINT, UINT]
    peek.restype = W.BOOL
    user.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
    user.TranslateMessage.restype = W.BOOL
    user.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
    user.DispatchMessageW.restype = C.c_ssize_t
    message = W.MSG()
    # Bounded so a pathological message producer cannot starve audio or stop.
    for _ in range(32):
        if not peek(C.byref(message), None, 0, 0, 1):
            break
        user.TranslateMessage(C.byref(message))
        user.DispatchMessageW(C.byref(message))


class PowerStatus(C.Structure):
    _fields_ = [("ac", C.c_ubyte), ("battery_flag", C.c_ubyte),
                ("percent", C.c_ubyte), ("reserved", C.c_ubyte),
                ("life", UINT), ("full_life", UINT)]


def on_battery():
    status = PowerStatus()
    function = _KERNEL.GetSystemPowerStatus
    function.argtypes = [C.POINTER(PowerStatus)]
    function.restype = W.BOOL
    # Unknown power is treated conservatively for keep-awake requests.
    return not function(C.byref(status)) or status.ac != 1
