"""Global add-on-only settings: never save or modify NVDA configuration profiles."""
import json
import os
from pathlib import Path
import tempfile

# Output modes. "device" keeps the 0.1.0 single-output behaviour; older settings
# files without a mode are migrated below without rewriting them on disk.
MODE_NVDA = "nvda"
MODE_DEFAULT = "windowsDefault"
MODE_DEVICE = "device"
MODE_DEVICES = "devices"
MODE_ALL = "all"
MODES = (MODE_NVDA, MODE_DEFAULT, MODE_DEVICE, MODE_DEVICES, MODE_ALL)
# Bounds the saved list, the settings UI and the number of concurrent streams.
MAX_SELECTED_DEVICES = 16

DEFAULTS = dict(enabled=False, mode=MODE_DEFAULT, device="", devices=[], volume=5,
                keepSystem=False, keepDisplay=False, awakeOnBattery=False, debug=False)


def _device_id(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Invalid output device ID")
    return value


def validated(values):
    if not isinstance(values, dict):
        raise ValueError("Settings must be an object")
    result = dict(DEFAULTS)
    result["devices"] = []
    for key in result:
        if key not in values:
            continue
        value = values[key]
        if key == "volume":
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError("Volume must be an integer from 0 to 100")
        elif key == "device":
            _device_id(value)
        elif key == "mode":
            if value not in MODES:
                raise ValueError(f"Unknown output mode: {value!r}")
        elif key == "devices":
            if not isinstance(value, list) or len(value) > MAX_SELECTED_DEVICES:
                raise ValueError("Selected outputs must be a list of at most "
                                 f"{MAX_SELECTED_DEVICES} device IDs")
            unique = []
            for entry in value:
                if _device_id(entry) and entry not in unique:
                    unique.append(entry)
            value = unique
        elif type(value) is not bool:
            raise ValueError(f"Invalid boolean setting: {key}")
        result[key] = value
    if "mode" not in values:
        # Settings written by 0.1.0 knew only one output; keep that choice.
        result["mode"] = MODE_DEVICE if result["device"] else MODE_DEFAULT
    return result


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path)
        self.data = dict(DEFAULTS)
        self.load_error = ""
        if self.path.exists():
            try:
                if self.path.stat().st_size > 65536:
                    raise ValueError("Settings file exceeds size limit")
                self.data = validated(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, RecursionError) as exc:
                self.load_error = str(exc)

    def save(self, data):
        data = validated(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix="audio-keeper-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.data = data
            self.load_error = ""
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
