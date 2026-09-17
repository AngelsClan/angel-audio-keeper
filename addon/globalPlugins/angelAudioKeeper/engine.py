"""Thread-owned audio state machine with bounded retries and diagnostic logging."""
from dataclasses import dataclass
import logging
import os
import sys
from pathlib import Path
import threading
import time
from .noise import Noise

VERSION = "0.1.0"


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

    @classmethod
    def from_config(cls, section):
        return cls(bool(section["enabled"]), str(section["device"]),
                   max(0, min(100, int(section["volume"]))), bool(section["keepSystem"]),
                   bool(section["keepDisplay"]), bool(section["awakeOnBattery"]),
                   bool(section["debug"]))


def make_logger(directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    logger = logging.Logger("angelAudioKeeper", logging.INFO)
    handler = RotatingLogHandler(path / "audio-keeper.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


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
        self.status = {"state": "Disabled", "device": "", "format": "", "frames": 0,
                       "buffers": 0, "emptyBuffers": 0, "recoveries": 0,
                       "lastError": "", "devices": [], "scanGeneration": 0,
                       "scanError": "", "version": VERSION}
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

    def _run(self):
        system = stream = noise = None
        applied = None
        volume_applied = None
        power = (False, False)
        next_retry = next_devices = next_check = next_report = 0.0
        retry_delay = 1.0
        started_at = 0.0
        frames = buffers = empty = recoveries = 0
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
                    if stream and (not settings.enabled or settings.device != applied.device):
                        self._close_stream(stream, noise, smooth=True)
                        stream = noise = None
                    if not stream:
                        self._set_power()
                        power = (False, False)
                    self.logger.info("Settings enabled=%s volume=%d selected=%s systemAwake=%s displayAwake=%s batteryAllowed=%s debug=%s",
                                     settings.enabled, settings.volume, settings.device or "Windows default",
                                     settings.keep_system, settings.keep_display, settings.awake_on_battery, settings.debug)
                    applied = settings
                    next_retry = next_check = 0
                    retry_delay = 1
                    self._status(state=("Playing" if stream else "Starting") if settings.enabled else "Disabled")
                try:
                    if system is None and (settings.enabled or scan) and (scan or now >= next_retry):
                        system = self.backend.AudioSystem()
                        next_devices = 0
                    if system and (scan or (settings.enabled and now >= next_devices)):
                        try:
                            self._status(devices=system.devices())
                            self._status(scanError="")
                        except Exception:
                            # A property problem on an unrelated endpoint must not
                            # tear down a healthy active stream. Retry at scan cadence.
                            self.logger.warning("Output list refresh failed", exc_info=True)
                            self._status(scanError="Output list refresh failed; see log")
                        self._status(scanGeneration=self.snapshot()["scanGeneration"] + 1)
                        next_devices = now + 5
                    if settings.enabled and not stream and system and now >= next_retry:
                        stream = self.backend.RenderStream(system, settings.device)
                        # Set the stream gain before starting; never rebuild noise live.
                        stream.set_volume(settings.volume)
                        volume_applied = settings.volume
                        noise = Noise(stream.format, 100)
                        stream.write(noise.take(stream.capacity))
                        frames += stream.capacity
                        buffers += 1
                        stream.start()
                        started_at = now
                        recoveries += 1
                        self.logger.info("Stream started output=%s id=%s format=%s bufferFrames=%d",
                                         stream.name, stream.device_id, stream.format, stream.capacity)
                        layout = ", ".join(stream.format.channel_names)
                        self.logger.info("All-channel independent noise; channel layout: %s", layout)
                        self._status(state="Playing", device=stream.name, format=str(stream.format),
                                     channelLayout=layout, lastError="", recoveries=max(0, recoveries - 1))
                    if stream:
                        if volume_applied != settings.volume:
                            stream.set_volume(settings.volume)
                            volume_applied = settings.volume
                        available = stream.available()
                        if available:
                            if available == stream.capacity:
                                empty += 1
                                self.logger.debug("Render buffer empty at refill; total=%d", empty)
                            stream.write(noise.take(available))
                            frames += available
                            buffers += 1
                        self._status(frames=frames, buffers=buffers, emptyBuffers=empty)
                        if now >= next_check:
                            if not settings.device and system.default_id() != stream.device_id:
                                self.logger.info("Windows default output changed; reopening")
                                self._close_stream(stream, noise, smooth=True)
                                stream = noise = None
                            allow_power = settings.awake_on_battery or not self.backend.on_battery()
                            wanted = (settings.keep_system and allow_power and stream is not None,
                                      settings.keep_display and allow_power and stream is not None)
                            if wanted != power:
                                if self._set_power(*wanted):
                                    power = wanted
                                    self.logger.info("Power request system=%s display=%s", *power)
                            next_check = now + 2
                        if now - started_at >= 60:
                            retry_delay = 1
                        if now >= next_report:
                            self.logger.info("Activity frames=%d buffers=%d emptyRefills=%d recoveries=%d",
                                             frames, buffers, empty, max(0, recoveries - 1))
                            next_report = now + (10 if settings.debug else 60)
                    if system:
                        pump = getattr(self.backend, "pump_messages", None)
                        if pump:
                            pump()
                    if system and not settings.enabled:
                        system.close()
                        system = None
                except Exception as exc:
                    self.logger.exception("Audio operation failed; retry in %.0f seconds", retry_delay)
                    self._status(state="Waiting to recover" if settings.enabled else "Disabled (device scan unavailable)",
                                 lastError=str(exc))
                    if stream:
                        self._close_stream(stream, noise, smooth=False)
                        stream = noise = None
                    self._set_power()
                    power = (False, False)
                    if system:
                        system.close()
                        system = None
                    next_retry = now + retry_delay
                    retry_delay = min(30, retry_delay * 2)
                self.wake.wait(0.02 if stream else 0.5)
        except Exception as exc:
            self._status(state="Stopped after unexpected error", lastError=str(exc))
            self.logger.exception("Audio worker stopped unexpectedly")
        finally:
            if stream:
                self._close_stream(stream, noise, smooth=False)
            self._set_power()
            if system:
                system.close()
            self._status(state="Stopped")
            self.logger.info("Worker stopped; final frames=%d buffers=%d", frames, buffers)

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

    def _close_stream(self, stream, noise, smooth):
        try:
            if smooth and noise and stream.started:
                # Fade the next available block then let queued audio drain, bounded.
                available = stream.available()
                if available:
                    stream.write(noise.take(available, fade_out=True))
                    time.sleep(min(0.25, stream.capacity / stream.format.rate))
        except Exception:
            self.logger.debug("Fade unavailable during device teardown", exc_info=True)
        finally:
            try:
                stream.close()
            except Exception:
                self.logger.exception("Render stream teardown reported an error")


def summary(status):
    return "\n".join(f"{key}: {value}" for key, value in status.items() if key != "devices")
