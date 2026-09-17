"""NVDA integration. Importing this module does not open an audio stream."""
import os
import time
from pathlib import Path
import globalPluginHandler
import globalVars
import gui
from gui import guiHelper
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
from logHandler import log
from NVDAState import WritePaths
from scriptHandler import script
import ui
import versionInfo
import wx
from .engine import Engine, Settings, VERSION, make_logger, summary
from .storage import SettingsStore

_plugin = None

ABOUT_TEXT = (
    f"Angel Audio Keeper {VERSION}\nCopyright 2026 Angels Clan\n"
    "GNU GPL version 2 or later; distributed without warranty. "
    "You may redistribute and modify it under that license. See LICENSE.txt in the package.\n\n"
    "Keeps your selected sound output active with continuous quiet noise, even when NVDA is silent. "
    "This may reduce sound-device wake delays and clipped speech on affected hardware; "
    "it does not repair drivers or guarantee that audio enhancements stay disabled.\n\n"
    "Independent noise plays on every channel exposed by that output, including HDMI surround "
    "when Windows and the receiver expose it. It uses one output at a time, not every device. "
    "Start with volume 5 and increase gently only if needed. Zero is silence.\n\n"
    "Fresh installations start disabled. Settings are under Preferences, Settings, Audio Keeper. "
    "Computer/display keep-awake options are optional; battery use must be explicitly allowed. "
    "Settings are global across NVDA profiles and survive upgrades.\n\n"
    "Stop audio with NVDA+Shift+F12 or Stop audio now. Playback stops when NVDA exits. "
    "No microphone capture, speech recording, networking or automatic uploads. "
    "Bounded local logs include device details; review them before sharing.\n\n"
    "This initial release has been tested on Windows 11 with NVDA 2026.2 and Realtek stereo. "
    "Surround layouts are software-tested; physical HDMI receiver testing remains limited. "
    "See the add-on help for installation, all settings, troubleshooting and removal."
)


class AudioKeeperPanel(SettingsPanel):
    title = "Audio Keeper"

    def makeSettings(self, settingsSizer):
        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        section = _plugin.store.data
        self.enableBox = helper.addItem(wx.CheckBox(self, label="&Enable continuous audio (also after NVDA restarts)"))
        self.enableBox.SetValue(section["enabled"])
        self.output = helper.addLabeledControl("Audio &output:", wx.Choice, choices=[])
        self.device_ids = []
        self._refresh_outputs(section["device"])
        refresh = helper.addItem(wx.Button(self, label="&Refresh output list"))
        refresh.Bind(wx.EVT_BUTTON, self.onRefresh)
        self.volume = helper.addLabeledControl("Noise &volume (0–100; start at 5; zero may not keep audio awake):", wx.SpinCtrl, min=0, max=100)
        self.volume.SetValue(section["volume"])
        helper.addItem(wx.StaticText(self, label="Start at 5. Increase gently if needed. Zero sends silence and may not keep hardware awake. Independent noise plays on every supported channel, including HDMI surround channels when exposed by Windows."))
        self.systemBox = helper.addItem(wx.CheckBox(self, label="Keep the co&mputer awake while audio is running"))
        self.systemBox.SetValue(section["keepSystem"])
        self.displayBox = helper.addItem(wx.CheckBox(self, label="Keep the &display awake while audio is running"))
        self.displayBox.SetValue(section["keepDisplay"])
        self.batteryBox = helper.addItem(wx.CheckBox(self, label="Allow keep-awake requests on &battery power"))
        self.batteryBox.SetValue(section["awakeOnBattery"])
        self.debugBox = helper.addItem(wx.CheckBox(self, label="Detailed diagnostic &logging"))
        self.debugBox.SetValue(section["debug"])
        self.statusText = helper.addLabeledControl("Current &status (use Refresh status to update):", wx.TextCtrl,
                                                  style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 110))
        self.refreshStatus()
        for title, handler in (("Refresh s&tatus", self.onStatus),
                               ("&Copy diagnostic summary", self.onCopy),
                               ("Open log &folder", self.onLogs),
                               ("&About the add-on", self.onAbout),
                               ("Stop audio &now", self.onStop)):
            button = helper.addItem(wx.Button(self, label=title))
            button.Bind(wx.EVT_BUTTON, handler)
        helper.addItem(wx.StaticText(self, label="Apply or OK activates changes. Cancel does not undo Stop audio now. Logs contain device details and errors, never recordings. Existing audio keeper add-ons are not disabled automatically."))
        self.scanTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onScanTimer, self.scanTimer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.onDestroy)
        self.beginScan()

    def _refresh_outputs(self, selected):
        entries = _plugin.engine.snapshot()["devices"] if _plugin else []
        self.device_ids = [""] + [identifier for identifier, name in entries]
        labels = ["Follow Windows default (multimedia)"] + [name for identifier, name in entries]
        if selected not in self.device_ids:
            self.device_ids.append(selected)
            labels.append("Saved output (currently unavailable)")
        self.output.Set(labels)
        self.output.SetSelection(self.device_ids.index(selected))

    def onRefresh(self, event):
        self.beginScan()
        ui.message("Scanning outputs. The list will update automatically.")

    def beginScan(self):
        if _plugin:
            self.scanRevision = _plugin.engine.snapshot().get("scanGeneration", 0)
            self.scanDeadline = time.monotonic() + 10
            _plugin.engine.request_scan()
            self.scanTimer.Start(200)

    def onScanTimer(self, event):
        if not _plugin:
            self.scanTimer.Stop()
            return
        state = _plugin.engine.snapshot()
        if state.get("scanGeneration", 0) > self.scanRevision:
            self.scanTimer.Stop()
            index = self.output.GetSelection()
            self._refresh_outputs(self.device_ids[index] if index >= 0 else "")
            self.refreshStatus()
        elif time.monotonic() >= self.scanDeadline:
            self.scanTimer.Stop()
            self.statusText.SetValue("Output scan has not completed yet. Check the diagnostic log or try Refresh output list again.")

    def onDestroy(self, event):
        if event.GetEventObject() is self:
            self.scanTimer.Stop()
        event.Skip()

    def refreshStatus(self):
        self.statusText.SetValue(_plugin.diagnostics() if _plugin else "Audio Keeper unavailable")

    def onStatus(self, event):
        self.refreshStatus()

    def onCopy(self, event):
        if not _plugin:
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(_plugin.diagnostics()))
                wx.TheClipboard.Flush()
            finally:
                wx.TheClipboard.Close()
            ui.message("Audio Keeper diagnostic summary copied")
        else:
            ui.message("Clipboard unavailable; please try again")

    def onLogs(self, event):
        if _plugin:
            os.startfile(str(_plugin.log_dir))

    def onAbout(self, event):
        ui.browseableMessage(ABOUT_TEXT, title="About Angel Audio Keeper")

    def onStop(self, event):
        self.enableBox.SetValue(False)
        if _plugin:
            _plugin.disable()

    def onSave(self):
        if not _plugin:
            return
        section = dict(_plugin.store.data)
        section["enabled"] = self.enableBox.GetValue()
        selected = self.output.GetSelection()
        section["device"] = self.device_ids[selected] if selected >= 0 else ""
        section["volume"] = self.volume.GetValue()
        section["keepSystem"] = self.systemBox.GetValue()
        section["keepDisplay"] = self.displayBox.GetValue()
        section["awakeOnBattery"] = self.batteryBox.GetValue()
        section["debug"] = self.debugBox.GetValue()
        _plugin.saveSettings(section)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Audio Keeper"

    def __init__(self):
        super().__init__()
        self.engine = None
        self.logger = None
        if globalVars.appArgs.secure:
            return
        global _plugin
        self.log_dir = Path(WritePaths.configDir) / "angelAudioKeeperLogs"
        try:
            self.store = SettingsStore(Path(WritePaths.configDir) / "angelAudioKeeper.json")
            self.logger = make_logger(self.log_dir)
            self.logger.info("NVDA %s; add-on %s", versionInfo.version, VERSION)
            if self.store.load_error:
                self.logger.error("Settings could not be loaded; starting disabled: %s", self.store.load_error)
            self.engine = Engine(self.logger)
            _plugin = self
            NVDASettingsDialog.categoryClasses.append(AudioKeeperPanel)
            self.applyConfig()
        except Exception:
            log.exception("Angel Audio Keeper initialization failed")
            self.terminate()

    def applyConfig(self, **kwargs):
        if self.engine:
            self.engine.update(Settings.from_config(self.store.data))

    def saveSettings(self, data):
        try:
            self.store.save(data)
        except Exception:
            self.logger.exception("Unable to save add-on settings")
            ui.message("Audio Keeper could not save settings. Changes were not applied. Check its log.")
            return False
        self.applyConfig()
        return True

    def diagnostics(self):
        log_errors = "; ".join(getattr(handler, "last_error", "") for handler in self.logger.handlers
                               if getattr(handler, "last_error", ""))
        return (f"NVDA: {versionInfo.version}\n" + summary(self.engine.snapshot())
                + f"\nSettings load error: {self.store.load_error or 'None'}\nLog folder: {self.log_dir}"
                + f"\nLog write error: {log_errors or 'None'}"
                + "\nChanges apply with Apply or OK. Independent noise plays on all channels exposed by the selected output."
                + "\nNo speech or microphone recordings. Profile switches do not change these global settings.")

    def disable(self):
        self.store.data["enabled"] = False
        self.applyConfig()  # Emergency stop must work even if disk writes fail.
        try:
            self.store.save(self.store.data)
        except Exception:
            log.exception("Unable to persist Audio Keeper stop setting")
            ui.message("Stopped, but could not save the change. Audio may restart next time NVDA starts.")
            return
        ui.message("Audio Keeper disabled")

    @script(description="Stop Audio Keeper immediately", gesture="kb:NVDA+shift+f12")
    def script_stop(self, gesture):
        if self.engine:
            self.disable()

    @script(description="Toggle continuous audio on or off")
    def script_toggle(self, gesture):
        if self.engine:
            if self.store.data["enabled"]:
                self.disable()
            else:
                data = dict(self.store.data, enabled=True)
                if self.saveSettings(data):
                    ui.message("Audio Keeper enabled")

    @script(description="Report Audio Keeper status")
    def script_status(self, gesture):
        if self.engine:
            status = self.engine.snapshot()
            ui.message("Audio Keeper: " + ". ".join(str(status[key]) for key in ("state", "device", "lastError") if status[key]))

    def terminate(self):
        global _plugin
        if _plugin is self:
            _plugin = None
        if AudioKeeperPanel in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.remove(AudioKeeperPanel)
        stopped = self.engine.stop() if self.engine else True
        if self.logger and stopped:
            for handler in self.logger.handlers[:]:
                handler.close()
                self.logger.removeHandler(handler)
        self.engine = None
        super().terminate()
