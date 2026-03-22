"""
StemPlayer — Reads audio from a WAV/OGG file and provides sample chunks with gain envelope.

Each StemPlayer holds a pre-loaded numpy array of audio data and a read cursor.
Supports looping, volume control with smooth ramping (vectorized), and mute/unmute.
"""

import numpy as np
import soundfile as sf
from pathlib import Path


class StemPlayer:
    def __init__(self, file_path: str, sample_rate: int = 44100, channels: int = 2):
        """
        Load an audio file into memory.

        Args:
            file_path: Path to WAV or OGG file.
            sample_rate: Expected sample rate. Raises ValueError if file differs.
            channels: Expected number of channels (2 for stereo).
        """
        self.file_path = Path(file_path)
        self.name = self.file_path.stem

        data, file_sr = sf.read(str(file_path), dtype='float32', always_2d=True)

        if file_sr != sample_rate:
            raise ValueError(
                f"Stem '{self.name}' has sample rate {file_sr}, expected {sample_rate}. "
                f"Pre-convert all stems to {sample_rate} Hz."
            )

        if data.shape[1] != channels:
            if data.shape[1] == 1 and channels == 2:
                data = np.column_stack([data[:, 0], data[:, 0]])
            else:
                raise ValueError(
                    f"Stem '{self.name}' has {data.shape[1]} channels, expected {channels}."
                )

        self._data: np.ndarray = data
        self._cursor: int = 0
        self._total_frames: int = data.shape[0]
        self._channels: int = channels
        self._sample_rate: int = sample_rate

        self._current_volume: float = 0.0
        self._target_volume: float = 0.0
        self._volume_ramp_per_sample: float = 0.0
        self._muted: bool = True

        self.loop: bool = True

    @property
    def current_volume(self) -> float:
        return self._current_volume

    @property
    def is_audible(self) -> bool:
        return self._current_volume > 0.001 or self._target_volume > 0.001

    def set_target_volume(self, volume: float, fade_seconds: float = 1.0):
        """Set volume target with fade duration. Volume is 0.0 to 1.0."""
        self._target_volume = max(0.0, min(1.0, volume))
        if fade_seconds <= 0:
            self._current_volume = self._target_volume
            self._volume_ramp_per_sample = 0.0
        else:
            total_samples = int(fade_seconds * self._sample_rate)
            if total_samples > 0:
                self._volume_ramp_per_sample = (
                    (self._target_volume - self._current_volume) / total_samples
                )
            else:
                self._current_volume = self._target_volume
                self._volume_ramp_per_sample = 0.0

    def mute(self, fade_seconds: float = 1.0):
        """Fade to silence."""
        self._muted = True
        self.set_target_volume(0.0, fade_seconds)

    def unmute(self, volume: float = 0.5, fade_seconds: float = 1.0):
        """Fade in to specified volume."""
        self._muted = False
        self.set_target_volume(volume, fade_seconds)

    def reset_cursor(self):
        """Reset playback to the beginning."""
        self._cursor = 0

    def read_chunk(self, num_frames: int) -> np.ndarray:
        """
        Read the next chunk of audio with volume envelope applied.

        Returns numpy array of shape (num_frames, channels), dtype float32.
        """
        if not self.is_audible and self._volume_ramp_per_sample == 0.0:
            return np.zeros((num_frames, self._channels), dtype=np.float32)

        output = np.empty((num_frames, self._channels), dtype=np.float32)
        frames_written = 0

        while frames_written < num_frames:
            remaining = num_frames - frames_written
            available = self._total_frames - self._cursor

            if available <= 0:
                if self.loop:
                    self._cursor = 0
                    available = self._total_frames
                else:
                    output[frames_written:] = 0.0
                    break

            to_read = min(remaining, available)
            chunk = self._data[self._cursor: self._cursor + to_read]
            self._cursor += to_read

            if self._volume_ramp_per_sample != 0.0:
                # Vectorized ramp
                start_vol = self._current_volume
                end_vol = start_vol + self._volume_ramp_per_sample * to_read
                lo = min(start_vol, self._target_volume)
                hi = max(start_vol, self._target_volume)
                end_vol = max(lo, min(hi, end_vol))

                gains = np.linspace(start_vol, end_vol, to_read, dtype=np.float32)
                self._current_volume = float(end_vol)

                # Stop ramping if we've reached the target
                if abs(self._current_volume - self._target_volume) < 1e-6:
                    self._current_volume = self._target_volume
                    self._volume_ramp_per_sample = 0.0

                output[frames_written: frames_written + to_read] = chunk * gains[:, np.newaxis]
            else:
                output[frames_written: frames_written + to_read] = chunk * self._current_volume

            frames_written += to_read

        return output
