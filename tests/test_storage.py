import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_audio import pkg
from aak.storage import SettingsStore, validated


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
                     {"device": 1}, []):
            with self.assertRaises(ValueError):
                validated(data)

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
