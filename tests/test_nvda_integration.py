"""Exercise plugin lifecycle and settings with NVDA API doubles, no live NVDA."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class Action:
    def __init__(self):
        self.handlers = []

    def register(self, callback):
        self.handlers.append(callback)

    def unregister(self, callback):
        self.handlers.remove(callback)


class Configuration(dict):
    def __init__(self):
        super().__init__(angelAudioKeeper=dict(enabled=False, device="", volume=5,
                         keepSystem=False, keepDisplay=False, awakeOnBattery=False, debug=False))
        self.spec = {}
        self.saved = 0

    def save(self):
        self.saved += 1


class BasePlugin:
    def terminate(self):
        pass


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conf = Configuration()
        self.profile = Action()
        self.reset = Action()
        self.categories = []
        self.appArgs = types.SimpleNamespace(secure=False)
        self.ui = types.ModuleType("ui")
        self.ui.message = MagicMock()
        self.ui.browseableMessage = MagicMock()
        modules = {}
        for name in ("config", "globalPluginHandler", "globalVars", "gui", "gui.guiHelper",
                     "gui.settingsDialogs", "logHandler", "NVDAState", "scriptHandler", "versionInfo", "wx"):
            modules[name] = types.ModuleType(name)
        modules["config"].conf = self.conf
        modules["config"].post_configProfileSwitch = self.profile
        modules["config"].post_configReset = self.reset
        modules["globalPluginHandler"].GlobalPlugin = BasePlugin
        modules["globalVars"].appArgs = self.appArgs
        modules["gui"].guiHelper = modules["gui.guiHelper"]
        modules["gui.settingsDialogs"].NVDASettingsDialog = types.SimpleNamespace(categoryClasses=self.categories)
        modules["gui.settingsDialogs"].SettingsPanel = object
        modules["logHandler"].log = MagicMock()
        modules["NVDAState"].WritePaths = types.SimpleNamespace(configDir=self.temp.name)
        modules["scriptHandler"].script = lambda **kwargs: lambda function: function
        modules["versionInfo"].version = "2026.2"
        modules["ui"] = self.ui
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        specification = importlib.util.spec_from_file_location(
            "aak_integration", ROOT / "addon/globalPlugins/angelAudioKeeper/__init__.py",
            submodule_search_locations=[str(ROOT / "addon/globalPlugins/angelAudioKeeper")])
        self.plugin_module = importlib.util.module_from_spec(specification)
        sys.modules["aak_integration"] = self.plugin_module
        specification.loader.exec_module(self.plugin_module)
        self.fake = MagicMock()
        self.fake.stop.return_value = True
        self.engine_patch = patch.object(self.plugin_module, "Engine", return_value=self.fake)
        self.constructor = self.engine_patch.start()
        self.plugin = None

    def tearDown(self):
        if self.plugin:
            self.plugin.terminate()
        self.engine_patch.stop()
        self.module_patch.stop()
        self.temp.cleanup()

    def test_secure_mode_registers_nothing(self):
        self.appArgs.secure = True
        self.plugin = self.plugin_module.GlobalPlugin()
        self.constructor.assert_not_called()
        self.assertEqual(self.categories, [])
        self.assertEqual(self.profile.handlers, [])
        self.assertEqual(self.reset.handlers, [])

    def test_about_is_readable_and_does_not_change_audio(self):
        panel = self.plugin_module.AudioKeeperPanel()
        panel.onAbout(None)
        self.ui.browseableMessage.assert_called_once_with(
            self.plugin_module.ABOUT_TEXT, title="About Angel Audio Keeper")
        self.assertIn("0.1.0", self.plugin_module.ABOUT_TEXT)
        self.assertIn("NVDA+Shift+F12", self.plugin_module.ABOUT_TEXT)
        self.constructor.assert_not_called()

    def test_registration_and_disabled_start(self):
        self.plugin = self.plugin_module.GlobalPlugin()
        self.assertEqual(len(self.categories), 1)
        self.assertFalse(self.fake.update.call_args.args[0].enabled)
        self.assertEqual(len(self.profile.handlers), 1)
        self.plugin.terminate()
        self.plugin = None
        self.assertEqual(self.categories, [])
        self.assertEqual(self.profile.handlers, [])
        self.assertEqual(self.reset.handlers, [])

    def test_settings_are_global_not_nvda_profiles(self):
        self.plugin = self.plugin_module.GlobalPlugin()
        self.plugin.saveSettings(dict(self.plugin.store.data, volume=17, enabled=True))
        self.assertEqual(self.fake.update.call_args.args[0].volume, 17)
        self.assertEqual(len(self.profile.handlers), 1)
        self.assertEqual(len(self.reset.handlers), 1)
        self.assertEqual(self.conf.saved, 0)
        self.plugin.disable()
        self.assertFalse(self.plugin.store.data["enabled"])
        self.assertEqual(self.conf.saved, 0)

    def test_stop_persists(self):
        self.plugin = self.plugin_module.GlobalPlugin()
        self.plugin.store.data["enabled"] = True
        self.plugin.script_stop(None)
        self.assertFalse(self.fake.update.call_args.args[0].enabled)
        self.assertFalse(self.plugin.store.data["enabled"])
        from aak_integration.storage import SettingsStore
        self.assertFalse(SettingsStore(self.plugin.store.path).data["enabled"])

    def test_initialization_failure_cleans_up(self):
        self.constructor.side_effect = RuntimeError("test failure")
        self.plugin = self.plugin_module.GlobalPlugin()
        self.assertEqual(self.categories, [])
        self.assertEqual(self.profile.handlers, [])

    def test_settings_save_persists_and_applies(self):
        self.plugin = self.plugin_module.GlobalPlugin()
        panel = self.plugin_module.AudioKeeperPanel()
        for name, value in (("enableBox", True), ("volume", 12), ("systemBox", False),
                            ("displayBox", True), ("batteryBox", False), ("debugBox", True)):
            control = MagicMock()
            control.GetValue.return_value = value
            setattr(panel, name, control)
        panel.output = MagicMock()
        panel.output.GetSelection.return_value = 0
        panel.mode = MagicMock()
        panel.mode.GetSelection.return_value = 2
        panel.outputs = MagicMock()
        panel.outputs.GetCheckedItems.return_value = []
        panel.device_ids = ["endpoint-test"]
        panel.onSave()
        self.assertEqual(self.conf.saved, 0)
        self.assertTrue(self.plugin.store.path.exists())
        settings = self.fake.update.call_args.args[0]
        self.assertEqual(settings.device, "endpoint-test")
        self.assertEqual(settings.volume, 12)
        self.assertTrue(settings.keep_display)
        self.assertTrue(settings.debug)

    def test_follow_nvda_updates_when_profile_changes(self):
        self.conf["audio"] = {"outputDevice": "first"}
        self.plugin = self.plugin_module.GlobalPlugin()
        self.plugin.saveSettings(dict(self.plugin.store.data, mode="nvda", enabled=True))
        self.assertEqual(self.fake.update.call_args.args[0].nvda_device, "first")
        self.conf["audio"]["outputDevice"] = "second"
        self.profile.handlers[0]()
        self.assertEqual(self.fake.update.call_args.args[0].nvda_device, "second")
        self.assertEqual(self.plugin.store.data["mode"], "nvda")

    def test_stop_works_even_if_save_fails(self):
        self.plugin = self.plugin_module.GlobalPlugin()
        self.plugin.store.data["enabled"] = True
        with patch.object(self.plugin.store, "save", side_effect=OSError("disk failure")):
            self.plugin.disable()
        self.assertFalse(self.fake.update.call_args.args[0].enabled)

    def test_save_failure_does_not_apply_new_settings(self):
        self.plugin = self.plugin_module.GlobalPlugin()
        self.fake.update.reset_mock()
        with patch.object(self.plugin.store, "save", side_effect=OSError("disk failure")):
            self.assertFalse(self.plugin.saveSettings(dict(self.plugin.store.data, enabled=True)))
        self.fake.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
