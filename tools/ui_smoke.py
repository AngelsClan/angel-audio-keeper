"""Construct real wx controls in a hidden test frame using NVDA API doubles.

Does not inject into/restart/install NVDA or play audio. Tests constructor API,
labels and value round trips, not live NVDA screen-reader announcements.
"""
import os
import importlib
# Keep ctypes and its native extension from this standalone interpreter together.
# Mixing NVDA's newer ctypes bytecode with Python 3.13.0's _ctypes is not valid.
import ctypes
import ctypes.wintypes
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
NVDA = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVDA"
dll = os.add_dll_directory(str(NVDA))
sys.path.insert(0, str(NVDA / "library.zip"))
sys.path.insert(0, str(NVDA))
import wx
sys.path.insert(0, str(ROOT / "tests"))
from test_nvda_integration import IntegrationTests


class Helper:
    def __init__(self, parent, sizer):
        self.parent = parent
        self.sizer = sizer

    def addItem(self, item):
        self.sizer.Add(item)
        return item

    def addLabeledControl(self, label, cls, **kwargs):
        self.sizer.Add(wx.StaticText(self.parent, label=label))
        control = cls(self.parent, **kwargs)
        self.sizer.Add(control)
        return control


class RealControls(unittest.TestCase):
    def runTest(self):
        fixture = IntegrationTests()
        fixture.setUp()
        sys.modules["wx"] = wx  # wx internals must resolve the real module too.
        frame = panel = None
        try:
            module = fixture.plugin_module
            # Exercise backend imports; ctypes stays matched to this test interpreter.
            backend = importlib.import_module("aak_integration.wasapi")
            self.assertEqual(backend.C.sizeof(backend.PropVariant), 24)
            module.wx = wx
            module.guiHelper.BoxSizerHelper = Helper
            fixture.fake.snapshot.return_value = dict(state="Disabled", device="", format="", frames=0,
                buffers=0, emptyBuffers=0, recoveries=0, lastError="", devices=[("one", "Test speakers")], version="test")
            fixture.plugin = module.GlobalPlugin()
            frame = wx.Frame(None, title="Audio Keeper hidden qualification")
            # Mix in wx.Panel: settings methods from the real add-on, GUI base doubled.
            class Panel(wx.Panel, module.AudioKeeperPanel):
                pass
            panel = Panel(frame)
            sizer = wx.BoxSizer(wx.VERTICAL)
            panel.SetSizer(sizer)
            panel.makeSettings(sizer)
            about = next(child for child in panel.GetChildren()
                         if isinstance(child, wx.Button) and child.GetLabel() == "&About the add-on")
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, about.GetId())
            event.SetEventObject(about)
            about.GetEventHandler().ProcessEvent(event)
            fixture.ui.browseableMessage.assert_called_once_with(
                module.ABOUT_TEXT, title="About Angel Audio Keeper")
            self.assertEqual(panel.volume.GetValue(), 5)
            self.assertEqual(panel.output.GetString(1), "Test speakers")
            fixture.fake.snapshot.return_value["scanGeneration"] = 1
            fixture.fake.snapshot.return_value["devices"].append(("two", "Second test output"))
            panel.onScanTimer(None)
            self.assertEqual(panel.output.GetString(2), "Second test output")
            self.assertFalse(panel.scanTimer.IsRunning())
            panel.volume.SetValue(11)
            panel.enableBox.SetValue(True)
            panel.onSave()
            self.assertEqual(fixture.plugin.store.data["volume"], 11)
            panel.onStop(None)
            self.assertFalse(fixture.plugin.store.data["enabled"])
            self.assertFalse(panel.enableBox.GetValue())
            print("Real wx settings controls constructed; asynchronous device list, values, Apply and Stop passed. Frame never shown.")
        finally:
            if frame is not None:
                frame.Destroy()
            fixture.tearDown()


app = wx.App(False)
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([RealControls()]))
app.ProcessPendingEvents()
app.Destroy()
raise SystemExit(0 if result.wasSuccessful() else 1)
