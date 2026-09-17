"""Small, format-aware noise generator. No audio capture or external packages."""
from dataclasses import dataclass
from array import array
import random
import struct


@dataclass(frozen=True)
class AudioFormat:
    rate: int
    channels: int
    bits: int
    floating: bool
    channel_mask: int = 0
    valid_bits: int = 0

    def __post_init__(self):
        if not 8000 <= self.rate <= 384000 or not 1 <= self.channels <= 32:
            raise ValueError("Unsupported device rate or channel count")
        if self.bits not in ((32, 64) if self.floating else (16, 24, 32)):
            raise ValueError("Unsupported device sample format")
        if self.valid_bits and not 1 <= self.valid_bits <= self.bits:
            raise ValueError("Invalid valid-bits value")

    @property
    def frame_bytes(self):
        return self.channels * (self.bits // 8)

    @property
    def channel_names(self):
        speakers = ("Front left", "Front right", "Front center", "Low-frequency effects",
                    "Back left", "Back right", "Front left of center", "Front right of center",
                    "Back center", "Side left", "Side right", "Top center", "Top front left",
                    "Top front center", "Top front right", "Top back left", "Top back center", "Top back right")
        bits = [bit for bit in range(32) if self.channel_mask & (1 << bit)]
        if len(bits) != self.channels:
            return tuple(f"Channel {index + 1} (layout unspecified)" for index in range(self.channels))
        return tuple(speakers[bit] if bit < len(speakers) else f"Speaker bit {bit}" for bit in bits)


class Noise:
    """Bounded circular pool with separately generated noise for every channel."""
    def __init__(self, fmt, volume, seed=None):
        self.fmt = fmt
        self.volume = max(0, min(100, int(volume)))
        # 100 is deliberately limited to one percent peak digital full scale.
        gain = self.volume / 10000.0
        self._integer_peak = int(gain * ((1 << ((fmt.valid_bits or fmt.bits) - 1)) - 1))
        rng = random.Random(seed)
        self.rng = rng
        # Bound both preparation cost and memory by total samples, not just frames.
        self.pool_frames = min(fmt.rate, 48000, 192000 // fmt.channels)
        self.samples = []
        for channel in range(fmt.channels):
            samples = array("d", (rng.uniform(-gain, gain) for _ in range(self.pool_frames)))
            mean = sum(samples) / self.pool_frames
            for index in range(self.pool_frames):
                samples[index] = max(-gain, min(gain, samples[index] - mean))
            self.samples.append(samples)
        self.position = 0
        self.ramp_frames = max(1, int(fmt.rate * 0.05))
        self.frames_sent = 0
        self._float_packer = struct.Struct("<" + ("f" if fmt.bits == 32 else "d") * fmt.channels)
        self.pool = b"".join(self._frame(index) for index in range(self.pool_frames))

    def _frame(self, index, scale=1.0):
        f = self.fmt
        values = [samples[index] * scale for samples in self.samples]
        if f.floating:
            # Canonical positive zero, including fade-out/silence.
            return self._float_packer.pack(*(value if value != 0 else 0.0 for value in values))
        valid = f.valid_bits or f.bits
        frame = bytearray()
        for value in values:
            integer = round(value * ((1 << (valid - 1)) - 1))
            integer = max(-self._integer_peak, min(self._integer_peak, integer)) << (f.bits - valid)
            frame.extend(integer.to_bytes(f.bits // 8, "little", signed=True))
        return bytes(frame)

    def take(self, frames, fade_out=False):
        if not 0 <= frames <= self.fmt.rate * 2:
            raise ValueError("Requested audio block is out of bounds")
        start = self.position
        position = start
        count = self.pool_frames
        if fade_out or self.frames_sent < self.ramp_frames:
            data = bytearray()
            for i in range(frames):
                ramp = min(1.0, (self.frames_sent + i + 1) / self.ramp_frames)
                if fade_out:
                    ramp *= max(0.0, 1.0 - (i + 1) / max(1, frames))
                data.extend(self._frame(position, ramp))
                position += 1
                if position == count:
                    position = self._next_cycle_start()
            result = bytes(data)
        else:
            size = self.fmt.frame_bytes
            chunks = []
            remaining = frames
            while remaining:
                chunk = min(remaining, count - position)
                chunks.append(self.pool[position * size:(position + chunk) * size])
                remaining -= chunk
                position += chunk
                if position == count:
                    position = self._next_cycle_start()
            result = b"".join(chunks)
        self.position = position
        self.frames_sent += frames
        return result

    def _next_cycle_start(self):
        # Vary wrap positions so a short high-rate pool is not a fixed-period buzz.
        # White-noise sample discontinuities are expected; no silence is inserted.
        return self.rng.randrange(max(1, self.pool_frames // 2))
