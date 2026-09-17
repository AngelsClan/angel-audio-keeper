"""Global add-on-only settings: never save or modify NVDA configuration profiles."""
import json
import os
from pathlib import Path
import tempfile

DEFAULTS = dict(enabled=False, device="", volume=5, keepSystem=False,
                keepDisplay=False, awakeOnBattery=False, debug=False)


def validated(values):
    if not isinstance(values, dict):
        raise ValueError("Settings must be an object")
    result = dict(DEFAULTS)
    for key in result:
        if key not in values:
            continue
        value = values[key]
        if key == "volume":
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError("Volume must be an integer from 0 to 100")
        elif key == "device":
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError("Invalid output device ID")
        elif type(value) is not bool:
            raise ValueError(f"Invalid boolean setting: {key}")
        result[key] = value
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
