import importlib.util
import logging
from pathlib import Path
import struct
import math
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon/globalPlugins/angelAudioKeeper"
pkg = types.ModuleType("aak")
pkg.__path__ = [str(PACKAGE)]
sys.modules["aak"] = pkg
from aak.noise import AudioFormat, Noise
from aak.engine import (Engine, Settings, MAX_STREAMS, make_logger, summary,
                        RotatingLogHandler)
from aak.storage import MODE_ALL, MODE_DEFAULT, MODE_DEVICE, MODE_DEVICES, MODE_NVDA


def wait_until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class SignalTests(unittest.TestCase):
    def test_all_float_channels(self):
        for channels in (1, 2, 6, 8, 32):
            with self.subTest(channels=channels):
                fmt = AudioFormat(48000, channels, 32, True)
                noise = Noise(fmt, 5, seed=42)
                values = struct.unpack("<" + "f" * 4000 * channels, noise.take(4000))
                streams = [values[channel::channels] for channel in range(channels)]
                self.assertTrue(all(any(value != 0 for value in stream) for stream in streams))
                for channel in range(1, channels):
                    self.assertNotEqual(streams[0], streams[channel])
                    covariance = sum(a * b for a, b in zip(streams[0], streams[channel]))
                    energy = math.sqrt(sum(a*a for a in streams[0]) * sum(b*b for b in streams[channel]))
                    self.assertLess(abs(covariance / energy), 0.1)
                self.assertLessEqual(max(abs(value) for value in values), 0.000501)

    def test_surround_layout_names_and_order(self):
        self.assertEqual(AudioFormat(48000, 2, 32, True, 3).channel_names, ("Front left", "Front right"))
        names = AudioFormat(48000, 6, 32, True, 0x3f).channel_names
        self.assertEqual(names, ("Front left", "Front right", "Front center", "Low-frequency effects", "Back left", "Back right"))
        names = AudioFormat(48000, 8, 32, True, 0x63f).channel_names
        self.assertEqual(names[-2:], ("Side left", "Side right"))
        self.assertIn("layout unspecified", AudioFormat(48000, 2, 32, True).channel_names[0])

    def test_hdmi_71_center_lfe_and_side_channels_active(self):
        fmt = AudioFormat(48000, 8, 32, True, 0x63f)
        noise = Noise(fmt, 30, seed=123)
        values = struct.unpack("<" + "f" * 8000 * 8, noise.take(8000))
        for channel in range(8):
            stream = values[channel::8]
            self.assertGreater(sum(x*x for x in stream), 0)
            for other in range(channel):
                self.assertNotEqual(stream, values[other::8])

    def test_high_rate_many_channel_pool_stays_bounded(self):
        fmt = AudioFormat(384000, 32, 32, True)
        noise = Noise(fmt, 5, seed=2)
        self.assertLessEqual(sum(len(channel) for channel in noise.samples), 192000)
        self.assertLessEqual(len(noise.pool), 192000 * 4)
        self.assertEqual(len(noise.take(10000)), 10000 * fmt.frame_bytes)

    def test_pcm_and_valid_bits(self):
        for bits, valid in ((16, 16), (24, 24), (32, 24), (32, 32)):
            fmt = AudioFormat(44100, 6, bits, False, valid_bits=valid)
            data = Noise(fmt, 100, seed=1).take(3000)
            self.assertEqual(len(data), 3000 * fmt.frame_bytes)
            values = [int.from_bytes(data[i:i + bits // 8], "little", signed=True)
                      for i in range(0, len(data), bits // 8)]
            self.assertLessEqual(max(abs(v) for v in values), 0.010001 * (1 << (bits - 1)))
            if bits == 32 and valid == 24:
                self.assertTrue(all(v & 255 == 0 for v in values))
            streams = [values[channel::6] for channel in range(6)]
            self.assertTrue(all(any(value for value in channel) for channel in streams))
            self.assertTrue(all(streams[channel] != streams[0] for channel in range(1, 6)))

    def test_surround_float64_and_fade_all_channels(self):
        fmt = AudioFormat(48000, 8, 64, True, 0x63f)
        noise = Noise(fmt, 10, seed=8)
        values = struct.unpack("<" + "d" * 3000 * 8, noise.take(3000))
        streams = [values[channel::8] for channel in range(8)]
        self.assertTrue(all(any(channel) for channel in streams))
        self.assertTrue(all(streams[channel] != streams[0] for channel in range(1, 8)))
        self.assertEqual(noise.take(300, fade_out=True)[-fmt.frame_bytes:], bytes(fmt.frame_bytes))

    def test_silence(self):
        for floating, bits in ((True, 32), (True, 64), (False, 16), (False, 24)):
            data = Noise(AudioFormat(8000, 2, bits, floating), 0).take(500)
            self.assertFalse(any(data))

    def test_circular_reads_and_constant_pool(self):
        fmt = AudioFormat(8000, 2, 32, True)
        noise = Noise(fmt, 50, seed=3)
        noise._next_cycle_start = lambda: 0
        noise.take(8000)
        pool_id = id(noise.pool)
        for count in (1, 15999, 8001, 400, 0, 16000):
            position = noise.position
            data = noise.take(count)
            doubled = noise.pool * 3
            self.assertEqual(data, doubled[position * 8:(position + count) * 8])
            self.assertEqual(id(noise.pool), pool_id)

    def test_multichannel_pcm_pool_wrap_and_channel_order(self):
        fmt = AudioFormat(48000, 8, 32, False, 0x63f, 24)
        noise = Noise(fmt, 30, seed=9)
        noise.frames_sent = noise.ramp_frames
        noise.position = noise.pool_frames - 3
        noise._next_cycle_start = lambda: 123
        expected = b"".join(noise._frame(index) for index in range(noise.pool_frames - 3, noise.pool_frames))
        expected += b"".join(noise._frame(index) for index in range(123, 130))
        self.assertEqual(noise.take(10), expected)
        self.assertEqual(noise.position, 130)

    def test_default_wrap_is_not_identical_repeated_loop(self):
        noise = Noise(AudioFormat(8000, 2, 32, True), 10, seed=42)
        noise.frames_sent = noise.ramp_frames
        first = noise.take(noise.pool_frames)
        second = noise.take(noise.pool_frames)
        self.assertNotEqual(first, second)

    def test_invalid_formats_and_limits(self):
        for args in ((0, 2, 32, True), (48000, 0, 32, True),
                     (48000, 33, 32, True), (48000, 2, 8, False)):
            with self.assertRaises(ValueError):
                AudioFormat(*args)
        fmt = AudioFormat(8000, 1, 16, False)
        self.assertEqual(Noise(fmt, -10).volume, 0)
        self.assertEqual(Noise(fmt, 1000).volume, 100)
        with self.assertRaises(ValueError):
            Noise(fmt, 5).take(16001)

    def test_fade_out_ends_at_zero(self):
        data = Noise(AudioFormat(8000, 2, 32, True), 100).take(400, fade_out=True)
        self.assertEqual(data[-8:], b"\0" * 8)


class FakeBackend:
    def __init__(self):
        self.opens = self.closes = self.writes = 0
        self.failures = 0
        self.device_failures = {}
        self.broken = set()
        self.entries = [("one", "Output one"), ("two", "Output two")]
        self.default = "one"
        self.scan_error = False
        self.battery = False
        self.power = []
        self.volumes = []
        self.opened = []
        self.writes_by = {}
        self.streams = {}
        self.worker_threads = set()
        owner = self

        class System:
            def devices(self):
                if owner.scan_error:
                    raise OSError("simulated property store failure")
                return list(owner.entries)

            def default_id(self):
                return owner.default

            def close(self):
                pass

        class Stream:
            def __init__(self, system, device=""):
                owner.opens += 1
                owner.worker_threads.add(threading.get_ident())
                target = device or owner.default
                owner.opened.append(target)
                if owner.failures:
                    owner.failures -= 1
                    raise OSError("simulated endpoint invalidated")
                if owner.device_failures.get(target):
                    owner.device_failures[target] -= 1
                    raise OSError(f"{target} is unavailable")
                if target not in [identifier for identifier, name in owner.entries]:
                    raise OSError(f"{target} is not connected")
                self.device_id = target
                self.name = dict(owner.entries)[target]
                self.format = AudioFormat(8000, 2, 32, True)
                self.capacity = 1600
                self.started = False
                owner.streams[target] = self

            def available(self):
                if self.device_id in owner.broken:
                    raise OSError("endpoint invalidated during playback")
                return 160

            def write(self, data):
                owner.writes += 1
                owner.writes_by[self.device_id] = owner.writes_by.get(self.device_id, 0) + 1
                assert len(data) % 8 == 0

            def start(self):
                self.started = True

            def set_volume(self, volume):
                owner.volumes.append(volume)

            def close(self):
                owner.closes += 1
                self.started = False

        self.AudioSystem = System
        self.RenderStream = Stream

    def add_device(self, identifier, name):
        self.entries.append((identifier, name))

    def remove_device(self, identifier):
        self.entries = [entry for entry in self.entries if entry[0] != identifier]

    def set_awake(self, system=False, display=False):
        self.power.append((system, display, threading.get_ident()))

    def on_battery(self):
        return self.battery


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.logger = logging.Logger("test")
        self.logger.addHandler(logging.NullHandler())
        self.engine = Engine(self.logger, self.backend)

    def tearDown(self):
        self.assertTrue(self.engine.stop())

    def test_disabled_never_opens_stream(self):
        self.engine.request_scan()
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["devices"]))
        self.assertEqual(self.backend.opens, 0)

    def test_continuous_stream_and_cleanup(self):
        self.engine.update(Settings(enabled=True))
        self.assertTrue(wait_until(lambda: self.backend.writes >= 10))
        self.assertEqual(self.backend.opens, 1)
        self.assertGreater(self.engine.snapshot()["frames"], 0)
        self.engine.update(Settings(enabled=False))
        self.assertTrue(wait_until(lambda: self.backend.closes == 1))
        self.assertEqual(self.backend.power[-1][:2], (False, False))
        self.assertNotIn(threading.get_ident(), self.backend.worker_threads)

    def test_live_settings_do_not_reopen_stream(self):
        self.engine.update(Settings(enabled=True))
        self.assertTrue(wait_until(lambda: self.backend.writes > 2))
        before = self.backend.writes
        with patch("aak.engine.Noise", side_effect=AssertionError("Noise must not regenerate live")):
            self.engine.update(Settings(enabled=True, volume=19, debug=True, keep_system=True))
            self.assertTrue(wait_until(lambda: self.backend.writes > before + 4))
        self.assertEqual(self.backend.opens, 1)
        self.assertEqual(self.backend.closes, 0)
        self.assertEqual(self.backend.volumes, [5, 19])

    def test_initial_gain_failure_never_starts_playback(self):
        with patch.object(self.backend.RenderStream, "set_volume", side_effect=OSError("gain unavailable")), patch.object(self.backend.RenderStream, "start") as start:
            self.engine.update(Settings(enabled=True, volume=0))
            self.assertTrue(wait_until(lambda: self.engine.snapshot()["lastError"] == "gain unavailable"))
            self.assertEqual(self.backend.writes, 0)
            start.assert_not_called()
            self.assertTrue(wait_until(lambda: self.backend.closes == 1))

    def test_volume_set_before_first_write(self):
        original = self.backend.RenderStream.write
        def checked_write(stream, data):
            self.assertEqual(self.backend.volumes, [0])
            original(stream, data)
        with patch.object(self.backend.RenderStream, "write", checked_write):
            self.engine.update(Settings(enabled=True, volume=0))
            self.assertTrue(wait_until(lambda: self.backend.writes > 2))
            self.assertEqual(self.engine.snapshot()["lastError"], "")

    def test_power_failure_does_not_stop_audio(self):
        def fail_power(*args):
            raise OSError("simulated power request failure")
        self.backend.set_awake = fail_power
        self.engine.update(Settings(enabled=True, keep_system=True))
        self.assertTrue(wait_until(lambda: self.backend.writes > 5))
        self.assertTrue(self.engine.thread.is_alive())

    def test_identical_settings_do_not_reopen(self):
        settings = Settings(enabled=True)
        self.engine.update(settings)
        self.assertTrue(wait_until(lambda: self.backend.writes > 1))
        for _ in range(100):
            self.engine.update(settings)
        time.sleep(0.1)
        self.assertEqual(self.backend.opens, 1)

    def test_failure_retries_then_recovers(self):
        self.backend.failures = 1
        self.engine.update(Settings(enabled=True))
        self.assertTrue(wait_until(lambda: self.backend.writes > 2))
        self.assertEqual(self.backend.opens, 2)
        self.assertEqual(self.engine.snapshot()["state"], "Playing")

    def test_backoff_and_stop_interrupts_wait(self):
        self.backend.failures = 100
        self.engine.update(Settings(enabled=True))
        self.assertTrue(wait_until(lambda: self.backend.opens == 1))
        time.sleep(0.3)
        self.assertEqual(self.backend.opens, 1)
        start = time.monotonic()
        self.assertTrue(self.engine.stop())
        self.assertLess(time.monotonic() - start, 1)

    def test_battery_does_not_request_awake_by_default(self):
        self.backend.battery = True
        self.engine.update(Settings(enabled=True, keep_system=True, keep_display=True))
        self.assertTrue(wait_until(lambda: self.backend.writes > 2))
        self.assertTrue(all(p[:2] == (False, False) for p in self.backend.power))

    def test_separate_power_flags(self):
        self.engine.update(Settings(enabled=True, keep_display=True))
        self.assertTrue(wait_until(lambda: any(p[:2] == (False, True) for p in self.backend.power)))
        self.engine.stop()
        self.assertEqual(self.backend.power[-1][:2], (False, False))

    def test_follow_default_reopens(self):
        self.engine.update(Settings(enabled=True))
        self.assertTrue(wait_until(lambda: self.backend.writes > 2))
        self.backend.default = "two"
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output two", 4))
        self.assertEqual(self.backend.opens, 2)

    def test_pinned_device_does_not_follow_default(self):
        self.engine.update(Settings(enabled=True, mode=MODE_DEVICE, device="one"))
        self.assertTrue(wait_until(lambda: self.backend.writes > 2))
        self.backend.default = "two"
        time.sleep(2.1)
        self.assertEqual(self.backend.opens, 1)
        self.assertEqual(self.engine.snapshot()["device"], "Output one")

    def test_missing_selected_device_never_falls_back(self):
        self.engine.update(Settings(enabled=True, mode=MODE_DEVICE, device="ghost"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["lastError"]))
        self.assertEqual(self.backend.writes, 0)
        self.assertEqual(set(self.backend.opened), {"ghost"})
        self.assertEqual(self.engine.snapshot()["state"], "Waiting to recover")

    def test_all_outputs_stream_independently(self):
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        self.assertTrue(wait_until(lambda: min(self.backend.writes_by.get(key, 0)
                                               for key in ("one", "two")) > 2))
        status = self.engine.snapshot()
        self.assertEqual(status["state"], "Playing")
        self.assertEqual(status["selectedOutputs"], 2)
        self.assertEqual(status["device"], "Output one; Output two")
        self.assertEqual(len(status["streams"]), 2)

    def test_all_outputs_follow_hotplug_both_ways(self):
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        self.backend.add_device("three", "Output three")
        self.engine.request_scan()
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 3))
        self.assertTrue(wait_until(lambda: self.backend.writes_by.get("three", 0) > 1))
        before = self.backend.writes_by["one"]
        self.backend.remove_device("three")
        self.engine.request_scan()
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        self.assertEqual(self.backend.closes, 1)
        # Removing one endpoint must not interrupt the others.
        self.assertGreater(self.backend.writes_by["one"], before)

    def test_all_outputs_are_bounded(self):
        for index in range(MAX_STREAMS + 4):
            self.backend.add_device(f"extra{index}", f"Extra output {index}")
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == MAX_STREAMS))
        time.sleep(0.3)
        status = self.engine.snapshot()
        self.assertEqual(status["selectedOutputs"], MAX_STREAMS)
        self.assertEqual(len(status["streams"]), MAX_STREAMS)
        self.assertIn("first", status["outputNote"])
        self.assertEqual(self.backend.opens, MAX_STREAMS)

    def test_one_failing_output_does_not_stop_the_others(self):
        self.engine.update(Settings(enabled=True, mode=MODE_DEVICES, devices=("one", "two")))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        healthy = self.backend.streams["one"]
        before = self.backend.writes_by["one"]
        self.backend.broken.add("two")
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 1))
        status = self.engine.snapshot()
        self.assertEqual(status["state"], "Playing on 1 of 2 outputs")
        self.assertIn("invalidated", status["lastError"])
        self.assertGreater(self.backend.writes_by["one"], before)
        self.assertIs(self.backend.streams["one"], healthy)
        self.assertTrue(healthy.started)
        # The broken output retries on its own, and recovers without reopening ours.
        self.backend.broken.clear()
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2, 4))
        self.assertIs(self.backend.streams["one"], healthy)
        self.assertEqual(self.engine.snapshot()["recoveries"], 1)

    def test_selected_output_reconnects_after_hotplug(self):
        self.backend.remove_device("two")
        self.engine.update(Settings(enabled=True, mode=MODE_DEVICES, devices=("one", "two")))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 1))
        self.assertIn("not connected", self.engine.snapshot()["lastError"])
        self.assertIn("not connected", self.engine.snapshot()["outputNote"])
        self.backend.add_device("two", "Output two")
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2, 6))
        self.assertTrue(wait_until(lambda: self.backend.writes_by.get("two", 0) > 1))

    def test_mode_change_closes_outputs_that_are_no_longer_selected(self):
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        self.engine.update(Settings(enabled=True, mode=MODE_DEVICE, device="two"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 1))
        self.assertTrue(wait_until(lambda: self.backend.closes == 1))
        time.sleep(0.2)
        self.assertEqual(self.engine.snapshot()["device"], "Output two")
        self.assertEqual(self.backend.closes, 1)

    def test_volume_change_reaches_every_output_without_reopening(self):
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        self.engine.update(Settings(enabled=True, mode=MODE_ALL, volume=22))
        self.assertTrue(wait_until(lambda: self.backend.volumes.count(22) == 2))
        self.assertEqual(self.backend.opens, 2)
        self.assertEqual(self.backend.closes, 0)

    def test_follow_nvda_uses_the_configured_endpoint(self):
        self.engine.update(Settings(enabled=True, mode=MODE_NVDA, nvda_device="two"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output two"))
        self.assertEqual(self.backend.opened, ["two"])

    def test_follow_nvda_profile_change_moves_the_stream(self):
        self.engine.update(Settings(enabled=True, mode=MODE_NVDA, nvda_device="two"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output two"))
        # An NVDA profile switch supplies a different configured output.
        self.engine.update(Settings(enabled=True, mode=MODE_NVDA, nvda_device="one"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output one"))
        self.assertEqual(self.backend.closes, 1)
        self.assertEqual(self.backend.opened, ["two", "one"])

    def test_follow_nvda_default_string_follows_windows_default(self):
        for value in ("default", "", "  Default  "):
            with self.subTest(value=value):
                self.backend.default = "two"
                self.engine.update(Settings(enabled=True, mode=MODE_NVDA, nvda_device=value))
                self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output two", 4))
                self.backend.default = "one"
                self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output one", 4))

    def test_follow_nvda_matches_an_older_friendly_name(self):
        self.engine.update(Settings(enabled=True, mode=MODE_NVDA, nvda_device="Output two"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output two"))
        self.assertEqual(self.backend.opened, ["two"])
        self.assertIn("name", self.engine.snapshot()["outputNote"])

    def test_follow_nvda_unknown_output_falls_back_like_nvda(self):
        self.engine.update(Settings(enabled=True, mode=MODE_NVDA, nvda_device="removed-headset"))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["device"] == "Output one"))
        self.assertIn("unavailable", self.engine.snapshot()["outputNote"])
        # The fake backend records the resolved default endpoint, not the
        # empty string passed to RenderStream.
        self.assertEqual(self.backend.opened, ["one"])

    def test_no_selected_outputs_reports_without_opening_anything(self):
        self.engine.update(Settings(enabled=True, mode=MODE_DEVICES, devices=()))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["state"] == "No output selected"))
        self.assertEqual(self.backend.opens, 0)
        self.assertIn("at least one", self.engine.snapshot()["outputNote"])

    def test_device_list_failure_does_not_stop_playback(self):
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        before = self.backend.writes
        self.backend.scan_error = True
        self.engine.request_scan()
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["scanError"]))
        self.assertTrue(wait_until(lambda: self.backend.writes > before + 4))
        self.assertEqual(self.engine.snapshot()["activeOutputs"], 2)
        self.assertEqual(self.backend.closes, 0)

    def test_summary_lists_every_output_without_raw_device_ids(self):
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == 2))
        text = summary(self.engine.snapshot())
        self.assertIn("outputs:", text)
        self.assertIn("Output one: Playing", text)
        self.assertIn("Output two: Playing", text)
        self.assertNotIn("devices:", text)

    def test_stop_with_every_output_open_stays_bounded(self):
        for index in range(MAX_STREAMS):
            self.backend.add_device(f"extra{index}", f"Extra output {index}")
        self.engine.update(Settings(enabled=True, mode=MODE_ALL))
        self.assertTrue(wait_until(lambda: self.engine.snapshot()["activeOutputs"] == MAX_STREAMS))
        start = time.monotonic()
        self.assertTrue(self.engine.stop())
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.backend.closes, MAX_STREAMS)
        self.assertEqual(self.backend.power[-1][:2], (False, False))

    def test_rotating_logs_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = make_logger(directory)
            for _ in range(120):
                logger.info("x" * 20000)
            for handler in logger.handlers:
                handler.close()
            files = list(Path(directory).glob("*.log*"))
            self.assertLessEqual(len(files), 4)
            self.assertTrue(all(f.stat().st_size < 512 * 1024 for f in files))

    def test_log_write_error_is_bounded_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = make_logger(directory)
            with patch("pathlib.Path.open", side_effect=OSError("file locked")), patch("aak.engine.sys.stderr") as stderr:
                for _ in range(50):
                    logger.info("test")
                self.assertEqual(stderr.write.call_count, 1)
                self.assertEqual(logger.handlers[0].last_error, "file locked")
            logger.info("recovered")
            self.assertEqual(logger.handlers[0].last_error, "")


if __name__ == "__main__":
    unittest.main()
