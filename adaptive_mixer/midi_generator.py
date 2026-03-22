"""
MidiGenerator — FluidSynth-based MIDI renderer for leitmotifs and procedural music.

Renders MIDI notes to audio buffers via FluidSynth, which can be mixed alongside
audio stems in the AdaptiveMixer.
"""

import numpy as np
import threading
import time
from typing import Optional

try:
    import fluidsynth
    FLUIDSYNTH_AVAILABLE = True
except ImportError:
    FLUIDSYNTH_AVAILABLE = False


class LeitmotifSequence:
    """A stored MIDI note sequence for a character leitmotif."""
    def __init__(self, data: dict):
        self.name = data.get("name", "Unnamed")
        self.instrument = data.get("instrument", 0)
        self.channel = data.get("channel", 5)
        self.notes = data.get("notes", [])
        self.total_beats = data.get("total_beats", 4)
        self.loop = data.get("loop", False)
        self.transpose = data.get("transpose_to_scene_key", False)


class MidiGenerator:
    def __init__(self, soundfont_path: str, sample_rate: int = 44100):
        """
        Initialize FluidSynth with the given SoundFont.

        Args:
            soundfont_path: Path to a .sf2 SoundFont file.
            sample_rate: Must match the AdaptiveMixer's sample rate.
        """
        if not FLUIDSYNTH_AVAILABLE:
            raise ImportError(
                "pyfluidsynth is required for MIDI generation. "
                "Install with: pip install pyfluidsynth"
            )

        self._sample_rate = sample_rate
        self._lock = threading.Lock()

        # Initialize FluidSynth without starting audio driver
        self._synth = fluidsynth.Synth(samplerate=float(sample_rate))
        self._sfid = self._synth.sfload(str(soundfont_path))

        if self._sfid == -1:
            raise FileNotFoundError(f"Failed to load SoundFont: {soundfont_path}")

        self._leitmotifs: dict = {}

        self._active_notes: list = []
        self._playback_start: float = 0.0
        self._current_bpm: float = 120.0
        self._is_playing: bool = False
        self._current_leitmotif: Optional[str] = None
        self._restart_pending: bool = False

        self._volume: float = 0.5

    def load_leitmotif(self, leitmotif_id: str, data: dict):
        """Register a leitmotif sequence."""
        self._leitmotifs[leitmotif_id] = LeitmotifSequence(data)

    def load_leitmotifs_from_config(self, config: dict):
        """Load all leitmotifs from a leitmotifs.json config dict."""
        for lid, ldata in config.get("leitmotifs", {}).items():
            self.load_leitmotif(lid, ldata)

    def trigger_leitmotif(self, leitmotif_id: str, bpm: float = 120.0):
        """
        Start playing a leitmotif. Stops any currently playing leitmotif first.
        Safe to call from outside the audio callback.
        """
        with self._lock:
            self._schedule_leitmotif(leitmotif_id, bpm)

    def _schedule_leitmotif(self, leitmotif_id: str, bpm: float):
        """Internal: set up leitmotif playback. Must be called with self._lock held."""
        self._stop_all_notes_locked()

        if leitmotif_id not in self._leitmotifs:
            print(f"[MidiGenerator] Warning: Leitmotif '{leitmotif_id}' not found")
            return

        lm = self._leitmotifs[leitmotif_id]
        self._synth.program_select(lm.channel, self._sfid, 0, lm.instrument)

        self._current_bpm = bpm
        self._current_leitmotif = leitmotif_id
        self._playback_start = time.monotonic()
        self._active_notes = []
        self._is_playing = True

        beat_duration = 60.0 / bpm
        for note in lm.notes:
            self._active_notes.append({
                "pitch": note["pitch"],
                "velocity": note["velocity"],
                "channel": lm.channel,
                "start_time": self._playback_start + (note["start_beat"] * beat_duration),
                "end_time": self._playback_start + (
                    (note["start_beat"] + note["duration_beats"]) * beat_duration
                ),
                "started": False,
                "stopped": False,
            })

    def stop_leitmotif(self):
        """Stop the currently playing leitmotif."""
        with self._lock:
            self._stop_all_notes_locked()
            self._is_playing = False
            self._current_leitmotif = None

    def set_volume(self, volume: float):
        """Set MIDI output volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, volume))

    def render_chunk(self, num_frames: int) -> np.ndarray:
        """
        Render the next chunk of MIDI audio.
        Called from the audio callback thread.

        Returns numpy array of shape (num_frames, 2), dtype float32.
        """
        with self._lock:
            now = time.monotonic()

            if self._is_playing:
                all_done = True
                for note in self._active_notes:
                    if not note["started"] and now >= note["start_time"]:
                        self._synth.noteon(note["channel"], note["pitch"], note["velocity"])
                        note["started"] = True
                    if note["started"] and not note["stopped"] and now >= note["end_time"]:
                        self._synth.noteoff(note["channel"], note["pitch"])
                        note["stopped"] = True
                    if not note["stopped"]:
                        all_done = False

                if all_done and self._active_notes:
                    lm = self._leitmotifs.get(self._current_leitmotif)
                    if lm and lm.loop:
                        # Restart without re-acquiring lock (already held)
                        self._schedule_leitmotif(self._current_leitmotif, self._current_bpm)
                    else:
                        self._is_playing = False
                        self._current_leitmotif = None

            raw_samples = self._synth.get_samples(num_frames)

            # FluidSynth returns interleaved int16 stereo: shape (num_frames * 2,)
            audio = np.frombuffer(raw_samples, dtype=np.int16).astype(np.float32)
            audio = audio / 32768.0
            audio = audio.reshape(-1, 2)

            audio *= self._volume

            if audio.shape[0] < num_frames:
                pad = np.zeros((num_frames - audio.shape[0], 2), dtype=np.float32)
                audio = np.vstack([audio, pad])
            elif audio.shape[0] > num_frames:
                audio = audio[:num_frames]

            return audio

    def _stop_all_notes_locked(self):
        """Send note-off for all active notes. Must be called with self._lock held."""
        for note in self._active_notes:
            if note["started"] and not note["stopped"]:
                try:
                    self._synth.noteoff(note["channel"], note["pitch"])
                except Exception:
                    pass
                note["stopped"] = True
        self._active_notes = []

    def cleanup(self):
        """Release FluidSynth resources."""
        with self._lock:
            self._stop_all_notes_locked()
        try:
            self._synth.delete()
        except Exception:
            pass
