"""
voice_effects.py — Real-time voice DSP processing for ConductorSBN.

Opens a full-duplex sounddevice stream and processes microphone audio
through a pedalboard effect chain in real time.

Dependencies:
    pip install pedalboard scipy sounddevice numpy

If pedalboard is not installed, falls back to simple numpy-based effects.
"""

import threading
import time
import numpy as np
from enum import Enum, auto
from typing import Optional, Callable

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

try:
    import pedalboard
    from pedalboard import (
        Pedalboard, Reverb, Delay, Chorus, PitchShift,
        Gain, LowpassFilter, Compressor, Limiter,
    )
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

try:
    import scipy.signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


class EffectPreset(Enum):
    NONE = auto()
    TUNNEL = auto()
    CATHEDRAL = auto()
    CHOIR = auto()
    DEMON = auto()
    WHISPER = auto()
    UNDERWATER = auto()


def _build_preset(preset: EffectPreset):
    """Build a pedalboard chain for the given preset."""
    if not HAS_PEDALBOARD:
        return None

    if preset == EffectPreset.TUNNEL:
        return Pedalboard([
            Reverb(room_size=0.4, damping=0.5, wet_level=0.6, dry_level=0.4),
            Delay(delay_seconds=0.08, feedback=0.3, mix=0.3),
        ])
    elif preset == EffectPreset.CATHEDRAL:
        return Pedalboard([
            Reverb(room_size=0.95, damping=0.1, wet_level=0.85, dry_level=0.15,
                   width=1.0),
            Gain(gain_db=2.0),
        ])
    elif preset == EffectPreset.CHOIR:
        # Three Chorus instances with different LFO rates simulate multiple
        # slightly-detuned voices blending together. Much cleaner than PitchShift
        # chains at real-time block sizes.
        return Pedalboard([
            Chorus(rate_hz=0.8,  depth=0.35, centre_delay_ms=7.0,  mix=0.5),
            Chorus(rate_hz=1.3,  depth=0.25, centre_delay_ms=11.0, mix=0.4),
            Chorus(rate_hz=2.1,  depth=0.15, centre_delay_ms=5.0,  mix=0.3),
            Reverb(room_size=0.8, damping=0.3, wet_level=0.6, dry_level=0.4,
                   width=1.0),
        ])
    elif preset == EffectPreset.DEMON:
        return Pedalboard([
            PitchShift(semitones=-6),
            Reverb(room_size=0.5, damping=0.7, wet_level=0.4, dry_level=0.6),
            Gain(gain_db=4.0),
        ])
    elif preset == EffectPreset.WHISPER:
        return Pedalboard([
            LowpassFilter(cutoff_frequency_hz=3500),
            Reverb(room_size=0.2, wet_level=0.3, dry_level=0.7),
            Gain(gain_db=-3.0),
        ])
    elif preset == EffectPreset.UNDERWATER:
        return Pedalboard([
            LowpassFilter(cutoff_frequency_hz=800),
            Chorus(rate_hz=0.5, depth=0.8, mix=0.6),
            Reverb(room_size=0.6, wet_level=0.5, dry_level=0.5),
        ])
    return None


# Simple numpy-based fallbacks when pedalboard is not available
def _numpy_reverb(audio: np.ndarray, wet: float = 0.5) -> np.ndarray:
    """Simple comb-filter reverb approximation."""
    delay_samples = 4410  # ~100ms at 44100Hz
    out = audio.copy()
    if len(audio) > delay_samples:
        out[delay_samples:] += audio[:-delay_samples] * 0.4 * wet
    return out


def _numpy_pitch_down(audio: np.ndarray, factor: float = 1.5) -> np.ndarray:
    """Very rough pitch-down via resampling (changes length)."""
    stretched = np.interp(
        np.linspace(0, len(audio) - 1, int(len(audio) * factor)),
        np.arange(len(audio)),
        audio,
    )
    return stretched[:len(audio)]


class VoiceEffectsProcessor:
    """
    Full-duplex audio processor. Opens a sounddevice stream that reads
    from the microphone, applies DSP effects, and writes to the output.

    If mic_buffer_callback is set, raw int16 mono audio at the stream
    sample rate is forwarded there (for use with Vosk speech recognition).
    """

    SAMPLE_RATE = 44100
    # 4096 samples = ~93ms latency. PitchShift needs a large enough window
    # to phase-vocode cleanly — 512 produced garbled output.
    BLOCK_SIZE = 4096
    CHANNELS = 1

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        block_size: int = BLOCK_SIZE,
        input_device=None,
        output_device=None,
        mic_buffer_callback: Optional[Callable[[bytes], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.input_device = input_device
        self.output_device = output_device
        self.mic_buffer_callback = mic_buffer_callback

        self._preset = EffectPreset.NONE
        self._chain = None
        self._chain_lock = threading.Lock()

        self._dry_wet = 0.7   # 0 = all dry, 1 = all wet
        self._enabled = False
        self._stream = None

        self.input_level = 0.0
        self.output_level = 0.0

    # ── Public API ────────────────────────────────────────────────

    def start(self):
        """Open the audio stream and begin processing."""
        if not HAS_SD:
            print("[VoiceFX] sounddevice not available.")
            return
        if self._stream and self._stream.active:
            return

        self._enabled = True
        try:
            self._stream = sd.Stream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                dtype="float32",
                channels=self.CHANNELS,
                device=(self.input_device, self.output_device),
                callback=self._audio_callback,
                latency="low",
            )
            self._stream.start()
            print("[VoiceFX] Stream started.")
        except Exception as e:
            print(f"[VoiceFX] Failed to start stream: {e}")
            self._enabled = False

    def stop(self):
        """Stop and close the audio stream."""
        self._enabled = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        print("[VoiceFX] Stream stopped.")

    @property
    def is_running(self) -> bool:
        return self._stream is not None and self._stream.active

    def set_preset(self, preset: EffectPreset):
        """Switch effect preset thread-safely."""
        chain = _build_preset(preset) if HAS_PEDALBOARD else None
        with self._chain_lock:
            self._preset = preset
            self._chain = chain
        print(f"[VoiceFX] Preset: {preset.name}")

    @property
    def preset(self) -> EffectPreset:
        return self._preset

    def set_dry_wet(self, mix: float):
        """Set dry/wet blend. 0.0 = all dry, 1.0 = all wet."""
        self._dry_wet = max(0.0, min(1.0, mix))

    @property
    def dry_wet(self) -> float:
        return self._dry_wet

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Audio Callback ────────────────────────────────────────────

    def _audio_callback(self, indata, outdata, frames, time_info, status):
        audio = indata[:, 0].copy()

        # Level metering
        self.input_level = float(np.abs(audio).mean())

        # Forward raw audio to Vosk if callback set
        if self.mic_buffer_callback:
            try:
                int16_bytes = (audio * 32767).astype(np.int16).tobytes()
                self.mic_buffer_callback(int16_bytes)
            except Exception:
                pass

        # Apply effects
        if self._enabled and self._preset != EffectPreset.NONE:
            with self._chain_lock:
                processed = self._apply_effects(audio)
            # Blend dry/wet
            result = audio * (1.0 - self._dry_wet) + processed * self._dry_wet
        else:
            result = audio

        # Noise gate — prevent feedback by cutting silence
        if np.abs(audio).max() < 0.01:
            result = np.zeros(frames, dtype=np.float32)

        self.output_level = float(np.abs(result).mean())
        outdata[:, 0] = np.clip(result, -1.0, 1.0)

    def _apply_effects(self, audio: np.ndarray) -> np.ndarray:
        """Apply the current effect chain to mono float32 audio."""
        if HAS_PEDALBOARD and self._chain is not None:
            try:
                shaped = audio.reshape(1, -1).astype(np.float32)
                processed = self._chain(shaped, self.sample_rate)
                return processed.flatten()
            except Exception:
                pass

        # Numpy fallbacks
        if self._preset == EffectPreset.TUNNEL:
            return _numpy_reverb(audio, wet=0.5)
        elif self._preset == EffectPreset.CATHEDRAL:
            return _numpy_reverb(audio, wet=0.8)
        elif self._preset == EffectPreset.DEMON:
            return _numpy_pitch_down(audio, factor=1.5)
        return audio

    @staticmethod
    def list_devices() -> list[dict]:
        """Return available audio devices."""
        if not HAS_SD:
            return []
        devices = sd.query_devices()
        result = []
        for i, d in enumerate(devices):
            result.append({
                "index": i,
                "name": d["name"],
                "inputs": d["max_input_channels"],
                "outputs": d["max_output_channels"],
            })
        return result
