"""
MidiGenerator — FluidSynth-based MIDI renderer for leitmotifs and procedural music.

Renders MIDI notes to audio buffers via FluidSynth, which can be mixed alongside
audio stems in the AdaptiveMixer.

Two backends:
  1. MidiGenerator — uses pyfluidsynth in-process (best quality, real-time).
  2. PrerenderedMidiGenerator — uses fluidsynth.exe as a subprocess to pre-render
     leitmotifs to WAV, then plays back cached audio.  Used as a fallback when
     in-process FluidSynth fails due to DLL conflicts (e.g. vosk vs FluidSynth
     shipping incompatible MinGW runtime DLLs on Windows).
"""

import numpy as np
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Optional

# Ensure FluidSynth DLL directory is on the search path before importing.
# On Windows, Python 3.8+ changed DLL search to require explicit directories.
# We must also pre-load dependency DLLs because os.add_dll_directory alone
# is insufficient when other packages (e.g. pygame) have already loaded
# conflicting or overlapping shared libraries into the process.
_FLUIDSYNTH_DLL_DIRS = [
    Path(r"C:\tools\fluidsynth\bin"),
    Path(r"C:\tools\fluidsynth\lib"),
    Path(sys.prefix) / "Library" / "bin",           # conda environments
    Path(__file__).resolve().parent.parent / "bin",  # bundled alongside project
]
if sys.platform == "win32":
    import ctypes as _ctypes
    for _d in _FLUIDSYNTH_DLL_DIRS:
        if _d.is_dir():
            os.add_dll_directory(str(_d))
            if str(_d) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(_d) + ";" + os.environ.get("PATH", "")
            # Pre-load all DLLs so libfluidsynth can find its dependencies
            for _dll in sorted(_d.glob("*.dll")):
                if _dll.stem != "libfluidsynth-3":
                    try:
                        _ctypes.CDLL(str(_dll))
                    except OSError:
                        pass

try:
    import fluidsynth
    FLUIDSYNTH_AVAILABLE = True
except (ImportError, OSError) as _e:
    FLUIDSYNTH_AVAILABLE = False
    print(f"[MidiGenerator] FluidSynth unavailable: {_e}")


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


# ── Subprocess fallback ───────────────────────────────────────────────────────

def _find_fluidsynth_exe() -> Optional[str]:
    """Locate the fluidsynth CLI binary."""
    candidates = [
        Path(r"C:\tools\fluidsynth\bin\fluidsynth.exe"),
        Path(r"C:\tools\fluidsynth\fluidsynth.exe"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    found = shutil.which("fluidsynth")
    return found


FLUIDSYNTH_EXE = _find_fluidsynth_exe()


class PrerenderedMidiGenerator:
    """Subprocess-based fallback when in-process FluidSynth can't load.

    Pre-renders each leitmotif to an audio buffer using ``fluidsynth.exe``,
    then plays back the cached numpy arrays in ``render_chunk()``.
    """

    _REFERENCE_BPM = 120.0

    def __init__(self, soundfont_path: str, sample_rate: int = 44100):
        if not FLUIDSYNTH_EXE:
            raise FileNotFoundError("fluidsynth.exe not found on this system")
        sf = Path(soundfont_path)
        if not sf.exists():
            raise FileNotFoundError(f"SoundFont not found: {soundfont_path}")

        self._soundfont_path = str(sf.resolve())
        self._sample_rate = sample_rate
        self._lock = threading.Lock()

        self._leitmotifs: dict = {}
        self._cached_audio: dict = {}          # id → np.ndarray (reference BPM)

        self._current_audio: Optional[np.ndarray] = None
        self._playback_pos: int = 0
        self._is_playing: bool = False
        self._current_leitmotif: Optional[str] = None
        self._current_bpm: float = self._REFERENCE_BPM
        self._volume: float = 0.5

    # ── Leitmotif loading ──────────────────────────────────────────

    def load_leitmotif(self, leitmotif_id: str, data: dict):
        seq = LeitmotifSequence(data)
        self._leitmotifs[leitmotif_id] = seq
        try:
            audio = self._render_leitmotif(seq, self._REFERENCE_BPM)
            self._cached_audio[leitmotif_id] = audio
        except Exception as e:
            print(f"[PrerenderedMidi] Failed to render '{leitmotif_id}': {e}")

    def load_leitmotifs_from_config(self, config: dict):
        for lid, ldata in config.get("leitmotifs", {}).items():
            self.load_leitmotif(lid, ldata)

    # ── Playback ───────────────────────────────────────────────────

    def trigger_leitmotif(self, leitmotif_id: str, bpm: float = 120.0):
        with self._lock:
            self._is_playing = False

            if leitmotif_id not in self._cached_audio:
                print(f"[PrerenderedMidi] Warning: '{leitmotif_id}' not cached")
                return

            audio = self._cached_audio[leitmotif_id]

            # Resample if BPM differs from reference
            if abs(bpm - self._REFERENCE_BPM) > 1.0:
                speed = bpm / self._REFERENCE_BPM
                audio = self._resample(audio, speed)

            self._current_audio = audio
            self._current_bpm = bpm
            self._current_leitmotif = leitmotif_id
            self._playback_pos = 0
            self._is_playing = True

    def stop_leitmotif(self):
        with self._lock:
            self._is_playing = False
            self._current_leitmotif = None
            self._current_audio = None
            self._playback_pos = 0

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, volume))

    def render_chunk(self, num_frames: int) -> np.ndarray:
        with self._lock:
            output = np.zeros((num_frames, 2), dtype=np.float32)

            if not self._is_playing or self._current_audio is None:
                return output

            audio = self._current_audio
            pos = self._playback_pos
            remaining = len(audio) - pos

            if remaining <= 0:
                lm = self._leitmotifs.get(self._current_leitmotif)
                if lm and lm.loop:
                    self._playback_pos = 0
                    pos = 0
                    remaining = len(audio)
                else:
                    self._is_playing = False
                    self._current_leitmotif = None
                    return output

            n = min(num_frames, remaining)
            output[:n] = audio[pos : pos + n] * self._volume
            self._playback_pos = pos + n
            return output

    def cleanup(self):
        with self._lock:
            self._is_playing = False
            self._cached_audio.clear()

    # ── Internal rendering helpers ─────────────────────────────────

    def _render_leitmotif(self, seq: LeitmotifSequence, bpm: float) -> np.ndarray:
        """Render a single leitmotif to a numpy array via fluidsynth.exe."""
        import mido

        with tempfile.TemporaryDirectory() as tmpdir:
            midi_path = os.path.join(tmpdir, "lm.mid")
            wav_path = os.path.join(tmpdir, "lm.wav")

            # ── write MIDI file ──
            mid = mido.MidiFile(ticks_per_beat=480)
            track = mido.MidiTrack()
            mid.tracks.append(track)

            track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
            track.append(
                mido.Message(
                    "program_change", channel=0, program=seq.instrument, time=0
                )
            )

            events: list[tuple] = []
            for note in seq.notes:
                on_tick = int(note["start_beat"] * 480)
                off_tick = int((note["start_beat"] + note["duration_beats"]) * 480)
                events.append((on_tick, True, note["pitch"], note["velocity"]))
                events.append((off_tick, False, note["pitch"], 0))

            events.sort(key=lambda e: (e[0], not e[1]))

            prev = 0
            for tick, is_on, pitch, vel in events:
                dt = tick - prev
                kind = "note_on" if is_on else "note_off"
                track.append(
                    mido.Message(kind, channel=0, note=pitch, velocity=vel, time=dt)
                )
                prev = tick

            # Extra beat of silence for the last note's release tail
            track.append(mido.MetaMessage("end_of_track", time=480))
            mid.save(midi_path)

            # ── render via fluidsynth.exe ──
            cmd = [
                FLUIDSYNTH_EXE,
                "-ni",
                "-g", "0.5",
                "-R", "0",
                "-C", "0",
                "-r", str(self._sample_rate),
                "-F", wav_path,
                self._soundfont_path,
                midi_path,
            ]
            creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            result = subprocess.run(
                cmd, capture_output=True, timeout=30, creationflags=creation
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"fluidsynth.exe returned {result.returncode}: "
                    f"{result.stderr.decode(errors='replace')}"
                )

            # ── read WAV ──
            return self._read_wav(wav_path)

    @staticmethod
    def _read_wav(filepath: str) -> np.ndarray:
        with wave.open(filepath, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            sw = wf.getsampwidth()
            nc = wf.getnchannels()

        if sw == 2:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        audio = audio.reshape(-1, nc)
        if nc == 1:
            audio = np.column_stack([audio, audio])
        elif nc > 2:
            audio = audio[:, :2]

        # Trim trailing silence (keep 0.5 s tail for reverb / release)
        threshold = 0.001
        end = len(audio) - 1
        while end > 0 and np.max(np.abs(audio[end])) < threshold:
            end -= 1
        tail = min(int(44100 * 0.5), len(audio) - end - 1)
        audio = audio[: end + 1 + tail]
        return audio

    @staticmethod
    def _resample(audio: np.ndarray, speed: float) -> np.ndarray:
        if abs(speed - 1.0) < 0.01:
            return audio
        old_len = len(audio)
        new_len = max(1, int(old_len / speed))
        old_idx = np.arange(old_len)
        new_idx = np.linspace(0, old_len - 1, new_len)
        return np.column_stack(
            [np.interp(new_idx, old_idx, audio[:, c]) for c in range(2)]
        ).astype(np.float32)
