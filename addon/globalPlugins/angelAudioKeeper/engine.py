"""Thread-owned audio state machine with bounded retries and diagnostic logging.

One worker owns every stream. Each selected output is serviced independently so
that one failing or unplugged endpoint cannot stop the others.
"""
from dataclasses import dataclass
import logging
import os
import sys
from pathlib import Path
import threading
import time
from .noise import Noise
from .storage import (MAX_SELECTED_DEVICES, MODE_ALL, MODE_DEFAULT, MODE_DEVICE,
                      MODE_DEVICES, MODE_NVDA, MODES)

VERSION = "0.1.0"

# Sentinel target meaning "whatever Windows currently calls the default output".
FOLLOW_DEFAULT = ""
# Bound worker cost, memory and log volume regardless of how many endpoints exist.
MAX_STREAMS = MAX_SELECTED_DEVICES
MAX_LISTED_DEVICES = 64
MAX_ERROR_CHARS = 300

MODE_DESCRIPTIONS = {
    MODE_NVDA: "Follow NVDA's configured output",
    MODE_DEFAULT: "Follow the Windows default output (multimedia)",
    MODE_DEVICE: "One selected output",
    MODE_DEVICES: "Several selected outputs",
    MODE_ALL: "All active outputs",
}


class RotatingLogHandler(logging.Handler):
    """Small bounded handler; NVDA's frozen Python omits logging.handlers."""
    def __init__(self, path, max_bytes=512 * 1024, backups=3):
        super().__init__()
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self.last_error = ""

    def emit(self, record):
        try:
            payload = (self.format(record) + "\n").encode("utf-8", errors="replace")
            if len(payload) >= self.max_bytes:
                payload = payload[:self.max_bytes - 32] + b"\n[log entry truncated]\n"
            current = self.path.stat().st_size if self.path.exists() else 0
            if current + len(payload) >= self.max_bytes:
                for index in range(self.backups, 0, -1):
                    source = self.path if index == 1 else Path(str(self.path) + f".{index - 1}")
                    if source.exists():
                        os.replace(source, Path(str(self.path) + f".{index}"))
            with self.path.open("ab") as handle:
                handle.write(payload)
            self.last_error = ""
        except Exception as exc:
            if not self.last_error and sys.stderr:
                try:
                    sys.stderr.write("Audio Keeper could not write its log; check its diagnostic summary.\n")
                except Exception:
                    pass
            # Do not recursively flood NVDA's own log if rotation is blocked.
            self.last_error = str(exc)


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    device: str = ""
    volume: int = 5
    keep_system: bool = False
    keep_display: bool = False
    awake_on_battery: bool = False
    debug: bool = False
    mode: str = MODE_DEFAULT
    # Tuples keep this value hashable and comparable, so an unchanged
    # configuration never reopens a stream.
    devices: tuple = ()
    # NVDA's configured output device, resolved on the NVDA side and passed in;
    # the worker never imports or reads NVDA configuration itself.
    nvda_device: str = ""

    @classmethod
    def from_config(cls, section, nvda_device=""):
        mode = section.get("mode", MODE_DEFAULT)
        return cls(bool(section["enabled"]), str(section["device"]),
                   max(0, min(100, int(section["volume"]))), bool(section["keepSystem"]),
                   bool(section["keepDisplay"]), bool(section["awakeOnBattery"]),
                   bool(section["debug"]),
                   mode if mode in MODES else MODE_DEFAULT,
                   tuple(str(entry) for entry in section.get("devices", ())),
                   str(nvda_device or ""))


def make_logger(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    logger = logging.Logger("angelAudioKeeper", logging.INFO)
    handler = RotatingLogHandler(path / "audio-keeper.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


@dataclass
class Target:
    """Independent playback state for one selected output."""
    key: str
    name: str = ""
    stream: object = None
    noise: object = None
    volume_applied: object = None
    state: str = "Starting"
    error: str = ""
    retry_at: float = 0.0
    retry_delay: float = 1.0
    started_at: float = 0.0
    next_default_check: float = 0.0
    opens: int = 0
    frames: int = 0
    buffers: int = 0
    empty: int = 0

    def describe(self):
        if self.name:
            return self.name
        return "Windows default output" if self.key == FOLLOW_DEFAULT else self.key

    def report(self):
        detail = f"{self.describe()}: {self.state}"
        if self.stream is not None:
            detail += (f", {self.stream.format}, {self.frames} frames, {self.buffers} buffers,"
                       f" {self.empty} empty refills")
        if self.error:
            detail += f", last error: {self.error}"
        if self.opens > 1:
            detail += f", restarts: {self.opens - 1}"
        return detail


class Engine:
    def __init__(self, logger, backend=None):
        if backend is None:
            from . import wasapi as backend
        self.backend = backend
        self.logger = logger
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.quit = threading.Event()
        self.scan_requested = threading.Event()
        self._power_error = None
        self.settings = Settings()
        self.status = {"state": "Disabled", "outputMode": MODE_DESCRIPTIONS[MODE_DEFAULT],
                       "device": "", "format": "", "frames": 0,
                       "buffers": 0, "emptyBuffers": 0, "recoveries": 0,
                       "lastError": "", "devices": [], "scanGeneration": 0,
                       "scanError": "", "version": VERSION,
                       "selectedOutputs": 0, "activeOutputs": 0,
                       "outputNote": "", "streams": []}
        self.status["channelLayout"] = "Not opened yet"
        self.status["noiseMode"] = "Independent noise on every exposed output channel"
        self.thread = threading.Thread(target=self._run, name="AngelAudioKeeper", daemon=True)
        self.thread.start()

    def update(self, settings):
        with self.lock:
            self.settings = settings
        self.wake.set()

    def request_scan(self):
        self.scan_requested.set()
        self.wake.set()

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def _status(self, **values):
        with self.lock:
            self.status.update(values)

    def stop(self):
        self.quit.set()
        self.wake.set()
        self.thread.join(1)
        if self.thread.is_alive():
            self.logger.error("Worker did not stop within one second; no replacement worker started")
            return False
        return True

    # Target selection ----------------------------------------------------

    def _wanted_targets(self, settings, devices):
        """Return (ordered target keys, note) for the configured output mode."""
        note = ""
        identifiers = [identifier for identifier, name in devices]
        if settings.mode == MODE_ALL:
            keys = list(identifiers)
            if not keys:
                note = "No active outputs have been found yet"
        elif settings.mode == MODE_DEVICES:
            keys = [key for key in settings.devices if key]
            if not keys:
                note = "No outputs are selected; choose at least one or pick another mode"
            else:
                missing = [key for key in keys if identifiers and key not in identifiers]
                if missing:
                    note = f"{len(missing)} selected output(s) are not connected; retrying"
        elif settings.mode == MODE_NVDA:
            key, note = self._nvda_target(settings, identifiers, devices)
            keys = [] if key is None else [key]
        elif settings.mode == MODE_DEVICE:
            keys = [settings.device]
            if not settings.device:
                note = "No output is selected; the Windows default is used"
        else:
            keys = [FOLLOW_DEFAULT]
        ordered = []
        for key in keys:
            if key not in ordered:
                ordered.append(key)
        if len(ordered) > MAX_STREAMS:
            note = f"Only the first {MAX_STREAMS} outputs are used; {len(ordered)} were selected"
            ordered = ordered[:MAX_STREAMS]
        return ordered, note

    def _nvda_target(self, settings, identifiers, devices):
        """Map NVDA's audio output setting onto an endpoint.

        NVDA stores a string that may be absent, the literal "default", an
        endpoint ID, or (in older configurations) a friendly device name.
        """
        value = (settings.nvda_device or "").strip()
        if not value or value.lower() == "default":
            return FOLLOW_DEFAULT, "NVDA is set to the Windows default output"
        if value in identifiers:
            return value, ""
        for identifier, name in devices:
            if name == value:
                return identifier, "Matched NVDA's output by name"
        if not devices:
            return None, "Waiting for the output list before following NVDA"
        # NVDA itself falls back to the default output when its device is gone.
        return FOLLOW_DEFAULT, "NVDA's configured output is unavailable; following the Windows default"

    # Worker --------------------------------------------------------------

    def _run(self):
        system = None
        targets = {}
        devices = []
        applied = None
        power = (False, False)
        power_released = False
        note = ""
        system_retry = 0.0
        system_delay = 1.0
        next_devices = next_power = next_report = next_status = 0.0
        active = 0
        self.logger.info("Angel Audio Keeper %s worker started; shared render only, no capture", VERSION)
        try:
            while not self.quit.is_set():
                # Clear before reading settings; an update after reading stays signaled.
                self.wake.clear()
                with self.lock:
                    settings = self.settings
                scan = self.scan_requested.is_set()
                self.scan_requested.clear()
                now = time.monotonic()
                if settings != applied:
                    self.logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)
                    self.logger.info(
                        "Settings enabled=%s mode=%s volume=%d selected=%s multiple=%s nvdaOutput=%s"
                        " systemAwake=%s displayAwake=%s batteryAllowed=%s debug=%s",
                        settings.enabled, settings.mode, settings.volume,
                        settings.device or "Windows default", len(settings.devices),
                        settings.nvda_device or "default", settings.keep_system,
                        settings.keep_display, settings.awake_on_battery, settings.debug)
                    applied = settings
                    system_retry = next_devices = next_power = 0.0
                    system_delay = 1.0
                    next_status = 0.0
                try:
                    if system is None and (settings.enabled or scan) and (scan or now >= system_retry):
                        system = self.backend.AudioSystem()
                        system_delay = 1.0
                        next_devices = 0.0
                    if system and (scan or (settings.enabled and now >= next_devices)):
                        devices = self._rescan(system, devices)
                        next_devices = now + 5
                        next_status = 0.0
                except Exception as exc:
                    self.logger.exception("Audio device access failed; retry in %.0f seconds", system_delay)
                    self._status(lastError=str(exc)[:MAX_ERROR_CHARS])
                    self._close_all(targets, smooth=False)
                    targets.clear()
                    system = self._close_system(system)
                    system_retry = now + system_delay
                    system_delay = min(30, system_delay * 2)
                    next_status = 0.0
                if settings.enabled and system:
                    wanted, note = self._wanted_targets(settings, devices)
                    for key in [key for key in targets if key not in wanted]:
                        removed = targets.pop(key)
                        self.logger.info("Output no longer selected or present: %s", removed.describe())
                        self._close_target(removed, smooth=True)
                        next_status = 0.0
                    for key in wanted:
                        if key not in targets:
                            targets[key] = Target(key)
                            next_status = 0.0
                        self._service(targets[key], system, settings, now)
                else:
                    wanted = []
                    if targets:
                        self._close_all(targets, smooth=True)
                        targets.clear()
                        next_status = 0.0
                    if not settings.enabled:
                        note = ""
                        system = self._close_system(system)
                previous_active, active = active, sum(1 for t in targets.values() if t.stream)
                if active != previous_active:
                    next_power = next_status = 0.0
                if not active:
                    # Release the execution state as soon as nothing is playing.
                    if power != (False, False) or not power_released:
                        power_released = self._set_power()
                        power = (False, False)
                        next_power = now + 2
                elif now >= next_power:
                    power = self._apply_power(settings, power, active)
                    power_released = power == (False, False) and power_released
                    next_power = now + 2
                if system:
                    pump = getattr(self.backend, "pump_messages", None)
                    if pump:
                        pump()
                if now >= next_report and (active or targets):
                    self.logger.info("Activity outputs=%d/%d frames=%d buffers=%d emptyRefills=%d restarts=%d",
                                     active, len(targets), *self._totals(targets))
                    for target in list(targets.values())[:MAX_STREAMS]:
                        self.logger.debug("Output detail %s", target.report())
                    next_report = now + (10 if settings.debug else 60)
                if now >= next_status:
                    self._publish(settings, targets, note)
                    next_status = now + 0.25
                self.wake.wait(0.02 if active else 0.5)
        except Exception as exc:
            self._status(state="Stopped after unexpected error", lastError=str(exc)[:MAX_ERROR_CHARS])
            self.logger.exception("Audio worker stopped unexpectedly")
        finally:
            # Shutdown must fit inside the one-second join; never fade here.
            self._close_all(targets, smooth=False)
            self._set_power()
            self._close_system(system)
            frames, buffers, empty, restarts = self._totals(targets)
            self._status(state="Stopped", activeOutputs=0, streams=[])
            self.logger.info("Worker stopped; final frames=%d buffers=%d", frames, buffers)

    def _rescan(self, system, previous):
        try:
            devices = system.devices()[:MAX_LISTED_DEVICES]
            self._status(devices=devices, scanError="")
        except Exception:
            # A property problem on an unrelated endpoint must not tear down a
            # healthy active stream. Keep the previous list and retry later.
            self.logger.warning("Output list refresh failed", exc_info=True)
            self._status(scanError="Output list refresh failed; see log")
            devices = previous
        self._status(scanGeneration=self.snapshot()["scanGeneration"] + 1)
        return devices

    def _service(self, target, system, settings, now):
        """Run one output. Every failure here is contained to this output."""
        try:
            if target.stream and target.key == FOLLOW_DEFAULT and now >= target.next_default_check:
                target.next_default_check = now + 2
                if system.default_id() != target.stream.device_id:
                    self.logger.info("Windows default output changed; reopening")
                    self._close_target(target, smooth=True)
            if target.stream is None:
                if now < target.retry_at:
                    target.state = "Waiting to recover" if target.error else "Starting"
                    return
                # Own the stream immediately so any later failure still closes it.
                stream = target.stream = self.backend.RenderStream(system, target.key)
                target.opens += 1
                target.name = stream.name
                # Set the stream gain before starting; never rebuild noise live.
                stream.set_volume(settings.volume)
                noise = Noise(stream.format, 100)
                stream.write(noise.take(stream.capacity))
                stream.start()
                target.noise = noise
                target.volume_applied = settings.volume
                target.frames += stream.capacity
                target.buffers += 1
                target.started_at = now
                target.next_default_check = now + 2
                target.state = "Playing"
                target.error = ""
                layout = ", ".join(stream.format.channel_names)
                self.logger.info("Stream started output=%s id=%s format=%s bufferFrames=%d",
                                 stream.name, stream.device_id, stream.format, stream.capacity)
                self.logger.info("All-channel independent noise; channel layout: %s", layout)
                return
            if target.volume_applied != settings.volume:
                target.stream.set_volume(settings.volume)
                target.volume_applied = settings.volume
            available = target.stream.available()
            if available:
                if available == target.stream.capacity:
                    target.empty += 1
                    self.logger.debug("Render buffer empty at refill on %s; total=%d",
                                      target.describe(), target.empty)
                target.stream.write(target.noise.take(available))
                target.frames += available
                target.buffers += 1
            if now - target.started_at >= 60:
                target.retry_delay = 1.0
        except Exception as exc:
            message = str(exc)[:MAX_ERROR_CHARS]
            if message != target.error:
                self.logger.exception("Output %s failed; retry in %.0f seconds",
                                      target.describe(), target.retry_delay)
            else:
                # Bound the log while an output stays unavailable for a long time.
                self.logger.debug("Output %s still unavailable: %s", target.describe(), message)
            if target.stream is not None:
                self._close_target(target, smooth=False)
            target.error = message
            target.state = "Waiting to recover"
            target.retry_at = now + target.retry_delay
            target.retry_delay = min(30, target.retry_delay * 2)

    def _apply_power(self, settings, power, active):
        try:
            allow = settings.awake_on_battery or not self.backend.on_battery()
        except Exception as exc:
            # Power state is advisory only; audio must keep playing without it.
            if str(exc) != self._power_error:
                self.logger.warning("Power state unavailable; keep-awake withheld: %s", exc)
                self._power_error = str(exc)
            allow = False
        wanted = (settings.keep_system and allow and active > 0,
                  settings.keep_display and allow and active > 0)
        if wanted != power and self._set_power(*wanted):
            self.logger.info("Power request system=%s display=%s", *wanted)
            return wanted
        return power

    def _totals(self, targets):
        values = list(targets.values())
        return (sum(t.frames for t in values), sum(t.buffers for t in values),
                sum(t.empty for t in values), sum(max(0, t.opens - 1) for t in values))

    def _publish(self, settings, targets, note):
        values = list(targets.values())
        playing = [t for t in values if t.stream]
        frames, buffers, empty, restarts = self._totals(targets)
        errors = [t.error for t in values if t.error]
        if not settings.enabled:
            state = "Disabled"
        elif not values:
            state = "No output selected" if note else "Starting"
        elif len(playing) == len(values):
            state = "Playing" if playing else "Waiting to recover"
        elif playing:
            state = f"Playing on {len(playing)} of {len(values)} outputs"
        else:
            state = "Waiting to recover"
        first = playing[0] if playing else None
        self._status(state=state,
                     outputMode=MODE_DESCRIPTIONS.get(settings.mode, settings.mode),
                     device="; ".join(t.describe() for t in playing),
                     format=str(first.stream.format) if first else "",
                     channelLayout=", ".join(first.stream.format.channel_names) if first
                     else "Not opened yet",
                     frames=frames, buffers=buffers, emptyBuffers=empty, recoveries=restarts,
                     lastError=errors[-1] if errors else "",
                     selectedOutputs=len(values), activeOutputs=len(playing),
                     outputNote=note,
                     streams=[t.report() for t in values[:MAX_STREAMS]])

    def _set_power(self, system=False, display=False):
        try:
            self.backend.set_awake(system, display)
            self._power_error = None
            return True
        except Exception as exc:
            if str(exc) != self._power_error:
                self.logger.warning("Power request failed; audio may continue: %s", exc)
                self._power_error = str(exc)
            return False

    def _close_system(self, system):
        if system is not None:
            try:
                system.close()
            except Exception:
                self.logger.exception("Audio enumerator teardown reported an error")
        return None

    def _fade(self, target):
        try:
            if target.noise and target.stream.started:
                available = target.stream.available()
                if available:
                    target.stream.write(target.noise.take(available, fade_out=True))
                    return target.stream.capacity / target.stream.format.rate
        except Exception:
            self.logger.debug("Fade unavailable during device teardown", exc_info=True)
        return 0.0

    def _close_target(self, target, smooth):
        # Fade the next available block then let queued audio drain, bounded.
        delay = self._fade(target) if smooth else 0.0
        if delay:
            time.sleep(min(0.25, delay))
        self._release(target)

    def _close_all(self, targets, smooth):
        """Fade every output once, then close; one bounded wait for all of them."""
        delay = max([self._fade(t) for t in targets.values() if t.stream] or [0.0]) if smooth else 0.0
        if delay:
            time.sleep(min(0.25, delay))
        for target in targets.values():
            self._release(target)

    def _release(self, target):
        stream, target.stream, target.noise = target.stream, None, None
        target.volume_applied = None
        target.state = "Stopped"
        if stream is None:
            return
        try:
            stream.close()
        except Exception:
            self.logger.exception("Render stream teardown reported an error")


def summary(status):
    lines = []
    for key, value in status.items():
        if key == "devices":
            continue
        if key == "streams":
            lines.append("outputs:" + ("".join(f"\n  {entry}" for entry in value) or " none"))
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
