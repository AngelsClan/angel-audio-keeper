import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_audio import pkg
from aak.storage import SettingsStore, validated, MODE_DEFAULT, MODE_DEVICE, MODE_DEVICES


class StorageTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            self.assertFalse(path.exists())
            self.assertFalse(store.data["enabled"])
            store.save(dict(store.data, enabled=True, volume=14))
            self.assertEqual(SettingsStore(path).data["volume"], 14)
            self.assertTrue(SettingsStore(path).data["enabled"])
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_corrupt_settings_fail_closed_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("broken", encoding="utf-8")
            store = SettingsStore(path)
            self.assertFalse(store.data["enabled"])
            self.assertTrue(store.load_error)
            self.assertEqual(path.read_text(), "broken")

    def test_invalid_values(self):
        for data in ({"volume": True}, {"volume": 101}, {"enabled": "yes"},
                     {"device": 1}, {"mode": "unknown"},
                     {"devices": ["one"] * 17}, {"devices": "one"}, []):
            with self.assertRaises(ValueError):
                validated(data)

    def test_existing_single_output_keeps_its_choice(self):
        old = dict(enabled=True, device="saved-endpoint", volume=7,
                   keepSystem=False, keepDisplay=False, awakeOnBattery=False, debug=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(old), encoding="utf-8")
            store = SettingsStore(path)
            self.assertEqual(store.data["mode"], MODE_DEVICE)
            self.assertEqual(store.data["device"], "saved-endpoint")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), old)
        self.assertEqual(validated(dict(old, device=""))["mode"], MODE_DEFAULT)

    def test_multiple_output_ids_are_unique_and_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            store.save(dict(store.data, mode=MODE_DEVICES, devices=["one", "two", "one"]))
            self.assertEqual(SettingsStore(path).data["devices"], ["one", "two"])

    def test_failed_replace_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            store.save(store.data)
            original = path.read_bytes()
            with patch("aak.storage.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    store.save(dict(store.data, enabled=True))
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(store.data["enabled"])
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
