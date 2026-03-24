# ConductorSBN — Adaptive Music Mixer: Implementation Spec

## Purpose of This Document

This document is a complete implementation specification for adding a **dynamic adaptive music mixing system** to ConductorSBN, a Python-based speech-reactive soundboard for tabletop RPG game masters. It is written to be handed directly to Claude Code as an instruction set. The system allows the GM to layer, fade, and mix themed musical stems and procedurally generated leitmotifs in real time using hand gestures (MediaPipe) and keyboard hotkeys.

---

## Table of Contents

1. [Context: Existing App Architecture](#1-context-existing-app-architecture)
2. [Feature Overview](#2-feature-overview)
3. [New Dependencies](#3-new-dependencies)
4. [Directory Structure for Music Assets](#4-directory-structure-for-music-assets)
5. [Scene Pack JSON Schema](#5-scene-pack-json-schema)
6. [Module 1: BeatClock](#6-module-1-beatclock)
7. [Module 2: StemPlayer](#7-module-2-stemplayer)
8. [Module 3: MidiGenerator](#8-module-3-midigenerator)
9. [Module 4: AdaptiveMixer](#9-module-4-adaptivemixer)
10. [Module 5: MixerGestureController](#10-module-5-mixergesturecontroller)
11. [Module 6: MixerKeyboardController](#11-module-6-mixerkeyboardcontroller)
12. [Module 7: SceneManager](#12-module-7-scenemanager)
13. [Integration Points with Existing App](#13-integration-points-with-existing-app)
14. [Audio Pipeline Architecture](#14-audio-pipeline-architecture)
15. [Stem Preparation Utility](#15-stem-preparation-utility)
16. [Testing Strategy](#16-testing-strategy)
17. [Phased Implementation Order](#17-phased-implementation-order)
18. [Important Technical Constraints](#18-important-technical-constraints)

---

## 1. Context: Existing App Architecture

ConductorSBN is an existing Python application with these relevant components already built:

- **Hand gesture detection** via MediaPipe (webcam-based, detects hand landmarks)
- **Background music playback** from files with start/stop and fade in/fade out controlled by gestures
- **Keyboard hotkey system** for triggering sounds and controlling playback
- **Real-time voice effects** via Spotify's `pedalboard` library
- **Speech reactivity** — the soundboard reacts to speech input

The app likely uses `pygame.mixer` or a similar library for its current music playback. The new adaptive mixer system should be built as a **parallel module** that can coexist with or replace the existing single-track music playback, not rip out the existing system.

**IMPORTANT**: Before implementing anything, read through the existing codebase to understand:
- How gestures are currently detected and dispatched (what callback/event system is used)
- How keyboard hotkeys are currently registered and handled
- How audio is currently played (pygame.mixer? sounddevice? something else?)
- The main application loop structure (tkinter? pygame event loop? asyncio?)
- Where configuration/settings are stored

Adapt all integration code to match the existing patterns. Do NOT introduce a new event system if one already exists.

---

## 2. Feature Overview

The adaptive music system provides:

1. **Scene Packs**: Themed collections of audio stems (WAV/OGG files) organized by mood layer (base, peaceful, tension, combat, etc.)
2. **Vertical Layering**: All stems in a scene play simultaneously from the same start point; the GM controls which layers are audible by adjusting per-stem volume
3. **Procedural Leitmotifs**: Character themes defined as MIDI sequences, rendered in real time via FluidSynth and mixed into the audio output alongside the audio stems
4. **Gesture Control**: MediaPipe hand gestures mapped to intensity changes, stem toggles, and leitmotif triggers
5. **Keyboard Control**: Hotkeys for precise stem toggling, scene switching, and leitmotif triggers
6. **Beat-Quantized Transitions**: Fade-ins and fade-outs are quantized to bar boundaries for musical coherence
7. **Per-Stem Effects**: Optional reverb, filter, and other effects via pedalboard applied per-stem

---

## 3. New Dependencies

Add these to `requirements.txt` (or equivalent):

```
sounddevice>=0.5.0
soundfile>=0.12.0
numpy>=1.24.0
pyfluidsynth>=1.3.4
```

System-level dependencies (must be installed on the OS):

```bash
# Ubuntu/Debian
sudo apt-get install libportaudio2 portaudio19-dev fluidsynth libfluidsynth3

# macOS (Homebrew)
brew install portaudio fluid-synth

# Windows
# portaudio is bundled with sounddevice wheel
# FluidSynth: download from https://github.com/FluidSynth/fluidsynth/releases
# Add fluidsynth bin directory to PATH
```

Also download a General MIDI SoundFont file:

```bash
# Ubuntu — may already be installed
sudo apt-get install fluid-soundfont-gm
# File will be at: /usr/share/sounds/sf2/FluidR3_GM.sf2

# Or download manually from:
# https://member.keymusician.com/Member/FluidR3_GM/index.html
# Place in: assets/soundfonts/FluidR3_GM.sf2
```

The app already has `pedalboard` installed. The app already has `mediapipe` installed.

---

## 4. Directory Structure for Music Assets

Create this directory structure inside the project root:

```
assets/
├── music/
│   └── scenes/
│       ├── enchanted_forest/
│       │   ├── scene.json           # Scene metadata (see schema below)
│       │   ├── base_pad.wav         # Always-on ambient foundation
│       │   ├── peaceful_melody.wav  # Gentle exploration layer
│       │   ├── tension_strings.wav  # Rising danger layer
│       │   ├── combat_percussion.wav # Battle layer
│       │   └── combat_brass.wav     # Battle layer 2
│       ├── dark_dungeon/
│       │   ├── scene.json
│       │   ├── base_drone.wav
│       │   ├── drip_atmosphere.wav
│       │   ├── tension_choir.wav
│       │   └── combat_drums.wav
│       └── tavern/
│           ├── scene.json
│           └── ...
├── leitmotifs/
│   ├── leitmotifs.json              # Leitmotif definitions (see schema below)
│   └── README.md
└── soundfonts/
    └── FluidR3_GM.sf2               # General MIDI SoundFont
```

**ALL audio stems within a single scene MUST be**:
- The same sample rate (44100 Hz recommended)
- The same number of channels (stereo / 2 channels recommended)
- The same duration (pad shorter stems with silence)
- The same key and tempo (authored constraint)
- WAV format (16-bit or 32-bit float) or OGG

---

## 5. Scene Pack JSON Schema

### `scene.json`

```json
{
    "name": "Enchanted Forest",
    "bpm": 90,
    "key": "Dm",
    "time_signature": [4, 4],
    "stems": {
        "base_pad": {
            "file": "base_pad.wav",
            "layer": "base",
            "default_volume": 0.6,
            "always_on": true,
            "description": "Ambient pad foundation"
        },
        "peaceful_melody": {
            "file": "peaceful_melody.wav",
            "layer": "peaceful",
            "default_volume": 0.4,
            "always_on": false,
            "description": "Gentle harp arpeggios"
        },
        "tension_strings": {
            "file": "tension_strings.wav",
            "layer": "tension",
            "default_volume": 0.5,
            "always_on": false,
            "description": "Low tremolo strings"
        },
        "combat_percussion": {
            "file": "combat_percussion.wav",
            "layer": "combat",
            "default_volume": 0.7,
            "always_on": false,
            "description": "War drums"
        },
        "combat_brass": {
            "file": "combat_brass.wav",
            "layer": "combat",
            "default_volume": 0.5,
            "always_on": false,
            "description": "Brass stabs"
        }
    },
    "layer_groups": {
        "base": {"stems": ["base_pad"], "intensity": 0},
        "peaceful": {"stems": ["peaceful_melody"], "intensity": 1},
        "tension": {"stems": ["tension_strings"], "intensity": 2},
        "combat": {"stems": ["combat_percussion", "combat_brass"], "intensity": 3}
    },
    "effects": {
        "base_pad": {"reverb_room_size": 0.8, "low_pass_hz": 2000},
        "tension_strings": {"reverb_room_size": 0.5}
    }
}
```

### `leitmotifs.json`

```json
{
    "leitmotifs": {
        "aria_theme": {
            "name": "Aria's Theme",
            "description": "Elven ranger — ethereal and flowing",
            "instrument": 73,
            "channel": 5,
            "notes": [
                {"pitch": 74, "velocity": 80, "start_beat": 0.0, "duration_beats": 1.0},
                {"pitch": 76, "velocity": 85, "start_beat": 1.0, "duration_beats": 0.5},
                {"pitch": 78, "velocity": 90, "start_beat": 1.5, "duration_beats": 1.5},
                {"pitch": 76, "velocity": 75, "start_beat": 3.0, "duration_beats": 0.5},
                {"pitch": 74, "velocity": 70, "start_beat": 3.5, "duration_beats": 0.5}
            ],
            "total_beats": 4,
            "loop": false,
            "transpose_to_scene_key": true
        },
        "grimjaw_theme": {
            "name": "Grimjaw's Theme",
            "description": "Orc warlord — heavy and ominous",
            "instrument": 58,
            "channel": 6,
            "notes": [
                {"pitch": 36, "velocity": 110, "start_beat": 0.0, "duration_beats": 2.0},
                {"pitch": 38, "velocity": 100, "start_beat": 2.0, "duration_beats": 1.0},
                {"pitch": 36, "velocity": 105, "start_beat": 3.0, "duration_beats": 1.0}
            ],
            "total_beats": 4,
            "loop": false,
            "transpose_to_scene_key": false
        },
        "mystery_motif": {
            "name": "Mystery Motif",
            "description": "Generic suspense sting",
            "instrument": 48,
            "channel": 7,
            "notes": [
                {"pitch": 60, "velocity": 60, "start_beat": 0.0, "duration_beats": 0.25},
                {"pitch": 63, "velocity": 65, "start_beat": 0.5, "duration_beats": 0.25},
                {"pitch": 66, "velocity": 70, "start_beat": 1.0, "duration_beats": 0.25},
                {"pitch": 69, "velocity": 80, "start_beat": 1.5, "duration_beats": 2.5}
            ],
            "total_beats": 4,
            "loop": false,
            "transpose_to_scene_key": true
        }
    }
}
```

**`instrument`** is a General MIDI program number (0-127). Reference: https://www.midi.org/specifications-old/item/gm-level-1-sound-set

**`channel`** is the MIDI channel (0-15) to use for this leitmotif. Channels 5-9 are recommended (channel 9 is percussion in GM). Each leitmotif should use a unique channel to allow simultaneous playback.

**`pitch`** is a MIDI note number (0-127). Middle C = 60.

**`transpose_to_scene_key`**: If true, the MidiGenerator should transpose the leitmotif to match the current scene's key signature. This requires knowing the original key of the leitmotif (assumed C major / A minor unless specified).

---

## 6. Module 1: BeatClock

**File**: `adaptive_mixer/beat_clock.py`

A thread-safe tempo clock that provides beat/bar position tracking and event callbacks for quantized transitions.

```python
"""
BeatClock — Tempo-aware clock for synchronizing adaptive music transitions.

Tracks the current beat and bar position based on a configurable BPM.
Provides methods to schedule callbacks on beat/bar boundaries.
Thread-safe: runs its own timing thread, exposes position via atomic reads.

Usage:
    clock = BeatClock(bpm=90, time_signature=(4, 4))
    clock.on_bar(my_bar_callback)
    clock.start()
    ...
    next_bar_time = clock.next_bar_boundary()
    clock.stop()
"""

import threading
import time
from typing import Callable, Optional

class BeatClock:
    def __init__(self, bpm: float = 120.0, time_signature: tuple[int, int] = (4, 4)):
        """
        Args:
            bpm: Beats per minute.
            time_signature: Tuple of (beats_per_bar, beat_unit). E.g., (4, 4) for 4/4 time.
        """
        self.bpm = bpm
        self.beats_per_bar = time_signature[0]
        self.beat_unit = time_signature[1]

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Current position
        self._start_time: float = 0.0
        self._total_beats: float = 0.0

        # Callbacks
        self._beat_callbacks: list[Callable[[int, int], None]] = []  # (beat_in_bar, bar_number)
        self._bar_callbacks: list[Callable[[int], None]] = []        # (bar_number)

    @property
    def beat_duration(self) -> float:
        """Duration of one beat in seconds."""
        return 60.0 / self.bpm

    @property
    def bar_duration(self) -> float:
        """Duration of one bar in seconds."""
        return self.beat_duration * self.beats_per_bar

    def get_position(self) -> tuple[int, int, float]:
        """
        Returns:
            (bar_number, beat_in_bar, fractional_beat) — all zero-indexed.
            bar_number: Which bar we're in (0, 1, 2, ...)
            beat_in_bar: Which beat within the bar (0 to beats_per_bar-1)
            fractional_beat: Sub-beat position (0.0 to 1.0)
        """
        with self._lock:
            elapsed = time.monotonic() - self._start_time if self._running else 0.0
            total_beats = elapsed / self.beat_duration
            bar = int(total_beats // self.beats_per_bar)
            beat = int(total_beats % self.beats_per_bar)
            frac = total_beats % 1.0
            return bar, beat, frac

    def samples_to_next_bar(self, sample_rate: int) -> int:
        """How many audio samples until the next bar boundary."""
        bar, beat, frac = self.get_position()
        beats_remaining = self.beats_per_bar - beat - frac
        seconds_remaining = beats_remaining * self.beat_duration
        return int(seconds_remaining * sample_rate)

    def next_bar_boundary(self) -> float:
        """Time in seconds (monotonic) of the next bar boundary."""
        bar, beat, frac = self.get_position()
        beats_remaining = self.beats_per_bar - beat - frac
        return time.monotonic() + (beats_remaining * self.beat_duration)

    def on_beat(self, callback: Callable[[int, int], None]):
        """Register a callback fired on every beat: callback(beat_in_bar, bar_number)."""
        self._beat_callbacks.append(callback)

    def on_bar(self, callback: Callable[[int], None]):
        """Register a callback fired on every bar: callback(bar_number)."""
        self._bar_callbacks.append(callback)

    def set_bpm(self, bpm: float):
        """Change BPM. Takes effect on next beat. Thread-safe."""
        with self._lock:
            # Record current position before changing BPM
            if self._running:
                elapsed = time.monotonic() - self._start_time
                self._total_beats = elapsed / self.beat_duration
                self._start_time = time.monotonic() - (self._total_beats * (60.0 / bpm))
            self.bpm = bpm

    def start(self):
        """Start the clock. Resets position to beat 0, bar 0."""
        with self._lock:
            self._running = True
            self._start_time = time.monotonic()
            self._total_beats = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the clock."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self):
        """Internal loop that fires beat/bar callbacks."""
        last_beat = -1
        last_bar = -1
        while self._running:
            bar, beat, frac = self.get_position()
            if beat != last_beat:
                for cb in self._beat_callbacks:
                    try:
                        cb(beat, bar)
                    except Exception as e:
                        print(f"BeatClock beat callback error: {e}")
                last_beat = beat
            if bar != last_bar:
                for cb in self._bar_callbacks:
                    try:
                        cb(bar)
                    except Exception as e:
                        print(f"BeatClock bar callback error: {e}")
                last_bar = bar
            # Sleep for roughly 1/4 of a beat to catch transitions
            time.sleep(self.beat_duration * 0.25)
```

---

## 7. Module 2: StemPlayer

**File**: `adaptive_mixer/stem_player.py`

Represents a single audio stem that can be read sample-by-sample with volume envelope.

```python
"""
StemPlayer — Reads audio from a WAV/OGG file and provides sample chunks with gain envelope.

Each StemPlayer holds a pre-loaded numpy array of audio data and a read cursor.
It supports looping, volume control with smooth ramping, and mute/unmute.

The AdaptiveMixer will call read_chunk() on each active StemPlayer during its
audio callback, sum the results, and write to the output buffer.

Usage:
    stem = StemPlayer("base_pad.wav", sample_rate=44100)
    stem.set_target_volume(0.8, fade_seconds=2.0)
    chunk = stem.read_chunk(1024)  # Returns numpy array of shape (1024, 2)
"""

import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Optional

class StemPlayer:
    def __init__(self, file_path: str, sample_rate: int = 44100, channels: int = 2):
        """
        Load an audio file into memory.

        Args:
            file_path: Path to WAV or OGG file.
            sample_rate: Expected sample rate. If file differs, this will raise an error.
                         (Pre-process files to match. Do NOT resample at runtime in the callback.)
            channels: Expected number of channels (2 for stereo).
        """
        self.file_path = Path(file_path)
        self.name = self.file_path.stem

        # Load entire file into memory as float32 numpy array
        data, file_sr = sf.read(str(file_path), dtype='float32', always_2d=True)

        if file_sr != sample_rate:
            raise ValueError(
                f"Stem '{self.name}' has sample rate {file_sr}, expected {sample_rate}. "
                f"Pre-convert all stems to {sample_rate} Hz."
            )

        if data.shape[1] != channels:
            # Convert mono to stereo by duplicating
            if data.shape[1] == 1 and channels == 2:
                data = np.column_stack([data[:, 0], data[:, 0]])
            else:
                raise ValueError(
                    f"Stem '{self.name}' has {data.shape[1]} channels, expected {channels}."
                )

        self._data: np.ndarray = data          # shape: (total_frames, channels)
        self._cursor: int = 0                  # Current read position
        self._total_frames: int = data.shape[0]
        self._channels: int = channels
        self._sample_rate: int = sample_rate

        # Volume envelope
        self._current_volume: float = 0.0      # Current instantaneous volume
        self._target_volume: float = 0.0       # Where we're fading to
        self._volume_ramp_per_sample: float = 0.0  # How much volume changes per sample
        self._muted: bool = True               # Start muted; scene loading will unmute as needed

        # Loop control
        self.loop: bool = True                 # Whether to loop when reaching end

    @property
    def current_volume(self) -> float:
        return self._current_volume

    @property
    def is_audible(self) -> bool:
        return self._current_volume > 0.001 or self._target_volume > 0.001

    def set_target_volume(self, volume: float, fade_seconds: float = 1.0):
        """
        Set volume target with fade duration. Volume is 0.0 to 1.0.
        The volume will ramp smoothly during read_chunk() calls.

        Args:
            volume: Target volume (0.0 = silent, 1.0 = full).
            fade_seconds: Duration of the fade in seconds. 0 = instant.
        """
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

        Args:
            num_frames: Number of frames to read.

        Returns:
            numpy array of shape (num_frames, channels), dtype float32.
            Zeros if stem is silent and not ramping.
        """
        # Fast path: if completely silent and not ramping, return zeros
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
                    # Pad with silence
                    output[frames_written:] = 0.0
                    break

            to_read = min(remaining, available)
            chunk = self._data[self._cursor : self._cursor + to_read]
            self._cursor += to_read

            # Apply volume envelope with per-sample ramping
            if self._volume_ramp_per_sample != 0.0:
                # Generate per-sample gain ramp
                gains = np.empty(to_read, dtype=np.float32)
                for i in range(to_read):
                    gains[i] = self._current_volume
                    self._current_volume += self._volume_ramp_per_sample
                    # Clamp and stop ramping when target reached
                    if self._volume_ramp_per_sample > 0 and self._current_volume >= self._target_volume:
                        self._current_volume = self._target_volume
                        self._volume_ramp_per_sample = 0.0
                    elif self._volume_ramp_per_sample < 0 and self._current_volume <= self._target_volume:
                        self._current_volume = self._target_volume
                        self._volume_ramp_per_sample = 0.0
                output[frames_written : frames_written + to_read] = chunk * gains[:, np.newaxis]
            else:
                output[frames_written : frames_written + to_read] = chunk * self._current_volume

            frames_written += to_read

        return output
```

**Performance note on the per-sample loop**: The inner for-loop in the ramping path will be slow for large chunks in pure Python. For Phase 1 this is acceptable since fades are brief. If profiling shows this is a bottleneck, replace it with vectorized numpy:

```python
# Vectorized alternative for the ramping section:
gains = np.arange(to_read, dtype=np.float32) * self._volume_ramp_per_sample + self._current_volume
gains = np.clip(gains, min(self._current_volume, self._target_volume),
                max(self._current_volume, self._target_volume))
self._current_volume = float(gains[-1]) + self._volume_ramp_per_sample
# ... clamp logic ...
output[frames_written : frames_written + to_read] = chunk * gains[:, np.newaxis]
```

Use the vectorized version from the start if feasible.

---

## 8. Module 3: MidiGenerator

**File**: `adaptive_mixer/midi_generator.py`

Handles FluidSynth initialization, leitmotif playback, and procedural MIDI generation, rendering to numpy audio buffers.

```python
"""
MidiGenerator — FluidSynth-based MIDI renderer for leitmotifs and procedural music.

Renders MIDI notes to audio buffers via FluidSynth, which can be mixed alongside
audio stems in the AdaptiveMixer. Uses a SoundFont (.sf2) for instrument sounds.

Usage:
    gen = MidiGenerator(soundfont_path="assets/soundfonts/FluidR3_GM.sf2")
    gen.load_leitmotif("aria_theme", leitmotif_data)
    gen.trigger_leitmotif("aria_theme", bpm=90)
    chunk = gen.render_chunk(1024)  # Returns numpy array (1024, 2)
"""

import numpy as np
import threading
import time
from typing import Optional
from pathlib import Path

try:
    import fluidsynth
    FLUIDSYNTH_AVAILABLE = True
except ImportError:
    FLUIDSYNTH_AVAILABLE = False

class LeitmotifSequence:
    """A stored MIDI note sequence for a character leitmotif."""
    def __init__(self, data: dict):
        self.name = data.get("name", "Unnamed")
        self.instrument = data.get("instrument", 0)      # GM program number
        self.channel = data.get("channel", 5)             # MIDI channel
        self.notes = data.get("notes", [])                # List of note dicts
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

        # Initialize FluidSynth — do NOT call .start(), we'll use get_samples()
        self._synth = fluidsynth.Synth(samplerate=float(sample_rate))
        self._sfid = self._synth.sfload(str(soundfont_path))

        if self._sfid == -1:
            raise FileNotFoundError(f"Failed to load SoundFont: {soundfont_path}")

        # Leitmotif storage
        self._leitmotifs: dict[str, LeitmotifSequence] = {}

        # Active playback state
        self._active_notes: list[dict] = []  # Notes currently scheduled/playing
        self._playback_start: float = 0.0    # When current leitmotif started (monotonic)
        self._current_bpm: float = 120.0
        self._is_playing: bool = False
        self._current_leitmotif: Optional[str] = None

        # Volume
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

        Args:
            leitmotif_id: ID matching a loaded leitmotif.
            bpm: Current scene BPM for timing note durations.
        """
        with self._lock:
            self._stop_all_notes()

            if leitmotif_id not in self._leitmotifs:
                print(f"Warning: Leitmotif '{leitmotif_id}' not found")
                return

            lm = self._leitmotifs[leitmotif_id]

            # Set up the instrument on the leitmotif's channel
            self._synth.program_select(lm.channel, self._sfid, 0, lm.instrument)

            # Schedule notes
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
                    "end_time": self._playback_start + ((note["start_beat"] + note["duration_beats"]) * beat_duration),
                    "started": False,
                    "stopped": False,
                })

    def stop_leitmotif(self):
        """Stop the currently playing leitmotif."""
        with self._lock:
            self._stop_all_notes()
            self._is_playing = False
            self._current_leitmotif = None

    def set_volume(self, volume: float):
        """Set MIDI output volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, volume))

    def render_chunk(self, num_frames: int) -> np.ndarray:
        """
        Render the next chunk of MIDI audio.

        This method processes note on/off events based on timing, then asks
        FluidSynth to synthesize the corresponding audio.

        Args:
            num_frames: Number of stereo frames to render.

        Returns:
            numpy array of shape (num_frames, 2), dtype float32.
        """
        with self._lock:
            now = time.monotonic()

            # Process note events
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

                if all_done:
                    # Check for looping
                    lm = self._leitmotifs.get(self._current_leitmotif)
                    if lm and lm.loop:
                        self.trigger_leitmotif(self._current_leitmotif, self._current_bpm)
                    else:
                        self._is_playing = False
                        self._current_leitmotif = None

            # Render audio from FluidSynth
            raw_samples = self._synth.get_samples(num_frames)

            # FluidSynth returns interleaved int16 stereo
            # Convert to float32 numpy array of shape (num_frames, 2)
            audio = np.frombuffer(raw_samples, dtype=np.int16).astype(np.float32)
            audio = audio / 32768.0  # Normalize to -1.0 to 1.0
            audio = audio.reshape(-1, 2)

            # Apply volume
            audio *= self._volume

            # Ensure correct shape even if FluidSynth returns different length
            if audio.shape[0] < num_frames:
                pad = np.zeros((num_frames - audio.shape[0], 2), dtype=np.float32)
                audio = np.vstack([audio, pad])
            elif audio.shape[0] > num_frames:
                audio = audio[:num_frames]

            return audio

    def _stop_all_notes(self):
        """Send note-off for all active notes."""
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
        self._stop_all_notes()
        try:
            self._synth.delete()
        except Exception:
            pass
```

**Note on `get_samples()` return format**: pyFluidSynth's `get_samples(n)` returns `n` stereo frames as a byte buffer of interleaved int16 values. The total byte length is `n * 4` (2 channels × 2 bytes per int16 sample). The reshape to `(-1, 2)` after converting to float32 gives us `(n, 2)`.

If you encounter issues with the return format, test with:
```python
raw = synth.get_samples(1024)
arr = np.frombuffer(raw, dtype=np.int16)
print(f"Expected {1024 * 2} samples, got {len(arr)}")
# Should print: Expected 2048 samples, got 2048
```

---

## 9. Module 4: AdaptiveMixer

**File**: `adaptive_mixer/mixer.py`

The central audio engine that mixes stems + MIDI into a single output stream.

```python
"""
AdaptiveMixer — Main audio mixing engine.

Opens a sounddevice OutputStream with a callback that:
1. Reads chunks from all active StemPlayers
2. Reads a chunk from the MidiGenerator
3. Sums them together with master gain
4. Optionally applies master effects (via pedalboard)
5. Writes to the hardware output buffer

Usage:
    mixer = AdaptiveMixer(sample_rate=44100)
    mixer.load_scene("assets/music/scenes/enchanted_forest/")
    mixer.start()
    mixer.set_layer_volume("combat", 0.8, fade_seconds=2.0)
    mixer.trigger_leitmotif("aria_theme")
    ...
    mixer.stop()
"""

import numpy as np
import sounddevice as sd
import json
import threading
from pathlib import Path
from typing import Optional

from .stem_player import StemPlayer
from .midi_generator import MidiGenerator
from .beat_clock import BeatClock

# Optional pedalboard import for effects
try:
    from pedalboard import Pedalboard, Reverb, LowpassFilter
    PEDALBOARD_AVAILABLE = True
except ImportError:
    PEDALBOARD_AVAILABLE = False


class AdaptiveMixer:
    SAMPLE_RATE = 44100
    CHANNELS = 2
    BLOCK_SIZE = 1024  # Frames per callback. 1024 @ 44100 = ~23ms latency.
    DEFAULT_FADE_SECONDS = 2.0

    def __init__(
        self,
        sample_rate: int = 44100,
        soundfont_path: str = "assets/soundfonts/FluidR3_GM.sf2",
        leitmotif_config_path: str = "assets/leitmotifs/leitmotifs.json",
    ):
        self.SAMPLE_RATE = sample_rate
        self._lock = threading.Lock()
        self._stream: Optional[sd.OutputStream] = None
        self._running = False

        # Beat clock
        self.clock = BeatClock(bpm=120, time_signature=(4, 4))

        # Stems
        self._stems: dict[str, StemPlayer] = {}
        self._layer_groups: dict[str, dict] = {}
        self._scene_config: Optional[dict] = None

        # MIDI generator
        self._midi_gen: Optional[MidiGenerator] = None
        sf_path = Path(soundfont_path)
        if sf_path.exists():
            try:
                self._midi_gen = MidiGenerator(str(sf_path), sample_rate=sample_rate)
            except Exception as e:
                print(f"Warning: MIDI generator init failed: {e}")
                print("Leitmotif playback will be disabled.")

        # Load leitmotifs
        lm_path = Path(leitmotif_config_path)
        if lm_path.exists() and self._midi_gen:
            with open(lm_path, "r") as f:
                lm_config = json.load(f)
            self._midi_gen.load_leitmotifs_from_config(lm_config)

        # Master volume
        self._master_volume: float = 0.8

        # Master effects chain (optional)
        self._master_effects: Optional[object] = None
        if PEDALBOARD_AVAILABLE:
            self._master_effects = Pedalboard([
                Reverb(room_size=0.3, wet_level=0.15, dry_level=0.85),
            ])

        # Per-stem effects (loaded from scene config)
        self._stem_effects: dict[str, object] = {}

        # Pending actions queue (for quantized transitions)
        self._pending_actions: list[dict] = []

    # ─── Scene Loading ───

    def load_scene(self, scene_dir: str, crossfade_seconds: float = 3.0):
        """
        Load a scene from a directory containing scene.json and stem audio files.

        If a scene is already playing, fades it out before loading the new one.

        Args:
            scene_dir: Path to scene directory.
            crossfade_seconds: Fade-out time for current scene before loading new one.
        """
        scene_path = Path(scene_dir)
        config_path = scene_path / "scene.json"

        if not config_path.exists():
            raise FileNotFoundError(f"No scene.json found in {scene_dir}")

        with open(config_path, "r") as f:
            config = json.load(f)

        # Fade out current stems
        was_playing = self._running
        if was_playing:
            for stem in self._stems.values():
                stem.mute(fade_seconds=crossfade_seconds)
            # Wait for fade to complete (non-blocking approach: schedule the load)
            import time
            time.sleep(crossfade_seconds + 0.1)

        with self._lock:
            # Clear old stems
            self._stems.clear()
            self._stem_effects.clear()

            # Load new scene config
            self._scene_config = config
            self.clock.bpm = config.get("bpm", 120)
            ts = config.get("time_signature", [4, 4])
            self.clock.beats_per_bar = ts[0]
            self.clock.beat_unit = ts[1]

            # Load stems
            for stem_id, stem_config in config.get("stems", {}).items():
                file_path = scene_path / stem_config["file"]
                if not file_path.exists():
                    print(f"Warning: Stem file not found: {file_path}")
                    continue

                try:
                    stem = StemPlayer(
                        str(file_path),
                        sample_rate=self.SAMPLE_RATE,
                        channels=self.CHANNELS,
                    )
                    stem.loop = True

                    # Set initial volume
                    if stem_config.get("always_on", False):
                        stem.unmute(
                            volume=stem_config.get("default_volume", 0.5),
                            fade_seconds=2.0 if was_playing else 0.0,
                        )
                    else:
                        stem._muted = True
                        stem._current_volume = 0.0
                        stem._target_volume = 0.0

                    self._stems[stem_id] = stem
                except Exception as e:
                    print(f"Error loading stem '{stem_id}': {e}")

            # Load layer groups
            self._layer_groups = config.get("layer_groups", {})

            # Load per-stem effects
            if PEDALBOARD_AVAILABLE:
                for stem_id, fx_config in config.get("effects", {}).items():
                    effects = []
                    if "reverb_room_size" in fx_config:
                        effects.append(Reverb(
                            room_size=fx_config["reverb_room_size"],
                            wet_level=fx_config.get("reverb_wet", 0.3),
                            dry_level=fx_config.get("reverb_dry", 0.7),
                        ))
                    if "low_pass_hz" in fx_config:
                        effects.append(LowpassFilter(cutoff_frequency_hz=fx_config["low_pass_hz"]))
                    if effects:
                        self._stem_effects[stem_id] = Pedalboard(effects)

            # Sync all stem cursors to 0
            for stem in self._stems.values():
                stem.reset_cursor()

    def get_current_scene_name(self) -> str:
        if self._scene_config:
            return self._scene_config.get("name", "Unknown")
        return "No scene loaded"

    # ─── Playback Control ───

    def start(self):
        """Start the audio output stream and beat clock."""
        if self._running:
            return

        self._running = True
        self.clock.start()

        # Register bar callback for pending actions
        self.clock.on_bar(self._process_pending_actions)

        self._stream = sd.OutputStream(
            samplerate=self.SAMPLE_RATE,
            blocksize=self.BLOCK_SIZE,
            channels=self.CHANNELS,
            dtype='float32',
            callback=self._audio_callback,
            latency='low',
        )
        self._stream.start()

    def stop(self):
        """Stop audio output and clock."""
        self._running = False
        self.clock.stop()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        """
        sounddevice OutputStream callback. Called from a C thread — must be fast
        and must NOT allocate large objects, do I/O, or acquire contested locks.
        """
        if status:
            print(f"Audio callback status: {status}")

        try:
            mix = np.zeros((frames, self.CHANNELS), dtype=np.float32)

            # Mix all stems
            with self._lock:
                for stem_id, stem in self._stems.items():
                    chunk = stem.read_chunk(frames)

                    # Apply per-stem effects (if pedalboard available)
                    if stem_id in self._stem_effects and stem.is_audible:
                        fx = self._stem_effects[stem_id]
                        # pedalboard expects (channels, frames) layout
                        chunk_t = chunk.T.copy()
                        chunk_t = fx(chunk_t, self.SAMPLE_RATE, reset=False)
                        chunk = chunk_t.T

                    mix += chunk

            # Mix MIDI generator output
            if self._midi_gen:
                midi_chunk = self._midi_gen.render_chunk(frames)
                mix += midi_chunk

            # Apply master volume
            mix *= self._master_volume

            # Apply master effects
            if self._master_effects and PEDALBOARD_AVAILABLE:
                mix_t = mix.T.copy()
                mix_t = self._master_effects(mix_t, self.SAMPLE_RATE, reset=False)
                mix = mix_t.T

            # Clip to prevent distortion
            np.clip(mix, -1.0, 1.0, out=mix)

            outdata[:] = mix

        except Exception as e:
            # Never let an exception kill the audio thread
            outdata.fill(0)
            print(f"Audio callback error: {e}")

    # ─── Layer / Stem Control ───

    def set_layer_volume(self, layer_name: str, volume: float,
                         fade_seconds: float = DEFAULT_FADE_SECONDS,
                         quantized: bool = True):
        """
        Set volume for all stems in a layer group.

        Args:
            layer_name: Name of the layer group from scene.json (e.g., "combat").
            volume: Target volume (0.0 to 1.0).
            fade_seconds: Fade duration.
            quantized: If True, defer the change to the next bar boundary.
        """
        if quantized:
            self._pending_actions.append({
                "type": "set_layer_volume",
                "layer": layer_name,
                "volume": volume,
                "fade_seconds": fade_seconds,
            })
        else:
            self._apply_layer_volume(layer_name, volume, fade_seconds)

    def _apply_layer_volume(self, layer_name: str, volume: float, fade_seconds: float):
        group = self._layer_groups.get(layer_name, {})
        for stem_id in group.get("stems", []):
            if stem_id in self._stems:
                if volume > 0:
                    self._stems[stem_id].unmute(volume, fade_seconds)
                else:
                    self._stems[stem_id].mute(fade_seconds)

    def set_stem_volume(self, stem_id: str, volume: float,
                        fade_seconds: float = DEFAULT_FADE_SECONDS):
        """Set volume for a specific stem (non-quantized, immediate fade start)."""
        if stem_id in self._stems:
            if volume > 0:
                self._stems[stem_id].unmute(volume, fade_seconds)
            else:
                self._stems[stem_id].mute(fade_seconds)

    def toggle_stem(self, stem_id: str, fade_seconds: float = DEFAULT_FADE_SECONDS):
        """Toggle a stem on/off."""
        if stem_id in self._stems:
            stem = self._stems[stem_id]
            default_vol = 0.5
            if self._scene_config:
                stem_cfg = self._scene_config.get("stems", {}).get(stem_id, {})
                default_vol = stem_cfg.get("default_volume", 0.5)
            if stem.is_audible:
                stem.mute(fade_seconds)
            else:
                stem.unmute(default_vol, fade_seconds)

    def set_intensity(self, level: int, fade_seconds: float = DEFAULT_FADE_SECONDS):
        """
        Set overall intensity level. Activates all layers at or below this level
        and deactivates layers above it.

        Args:
            level: 0 = base only, 1 = + peaceful, 2 = + tension, 3 = + combat
        """
        for layer_name, group in self._layer_groups.items():
            group_intensity = group.get("intensity", 0)
            for stem_id in group.get("stems", []):
                if stem_id in self._stems:
                    if group_intensity <= level:
                        default_vol = 0.5
                        if self._scene_config:
                            stem_cfg = self._scene_config.get("stems", {}).get(stem_id, {})
                            default_vol = stem_cfg.get("default_volume", 0.5)
                        self._stems[stem_id].unmute(default_vol, fade_seconds)
                    else:
                        self._stems[stem_id].mute(fade_seconds)

    # ─── Leitmotif Control ───

    def trigger_leitmotif(self, leitmotif_id: str):
        """Trigger a leitmotif to play over the current mix."""
        if self._midi_gen:
            self._midi_gen.trigger_leitmotif(leitmotif_id, self.clock.bpm)

    def stop_leitmotif(self):
        """Stop any playing leitmotif."""
        if self._midi_gen:
            self._midi_gen.stop_leitmotif()

    # ─── Master Controls ───

    def set_master_volume(self, volume: float):
        self._master_volume = max(0.0, min(1.0, volume))

    def panic(self, fade_seconds: float = 1.0):
        """Emergency: fade everything to silence."""
        for stem in self._stems.values():
            stem.mute(fade_seconds)
        if self._midi_gen:
            self._midi_gen.stop_leitmotif()

    # ─── Quantized Action Processing ───

    def _process_pending_actions(self, bar_number: int):
        """Called by BeatClock on each bar boundary."""
        actions = self._pending_actions.copy()
        self._pending_actions.clear()
        for action in actions:
            if action["type"] == "set_layer_volume":
                self._apply_layer_volume(
                    action["layer"], action["volume"], action["fade_seconds"]
                )

    # ─── Status ───

    def get_stem_status(self) -> dict[str, dict]:
        """Return current volume/mute status of all stems for UI display."""
        status = {}
        for stem_id, stem in self._stems.items():
            status[stem_id] = {
                "volume": stem.current_volume,
                "target_volume": stem._target_volume,
                "is_audible": stem.is_audible,
                "muted": stem._muted,
            }
        return status

    def get_layer_names(self) -> list[str]:
        return list(self._layer_groups.keys())

    def get_stem_names(self) -> list[str]:
        return list(self._stems.keys())

    def get_leitmotif_names(self) -> list[str]:
        if self._midi_gen:
            return list(self._midi_gen._leitmotifs.keys())
        return []

    # ─── Cleanup ───

    def cleanup(self):
        """Release all resources."""
        self.stop()
        if self._midi_gen:
            self._midi_gen.cleanup()
```

---

## 10. Module 5: MixerGestureController

**File**: `adaptive_mixer/gesture_controller.py`

Maps MediaPipe hand gestures to AdaptiveMixer commands. This module should be **adapted to match the existing gesture detection callback system** in ConductorSBN.

```python
"""
MixerGestureController — Maps hand gestures to adaptive mixer commands.

IMPORTANT: This module provides the LOGIC for gesture-to-mixer mapping.
The actual MediaPipe detection loop and callback dispatch already exist
in ConductorSBN. You need to INTEGRATE this by calling the appropriate
method from the existing gesture handler.

The gestures below are suggestions. Adjust based on what gestures are
already used in the app and what's ergonomically available.
"""

from typing import Optional
from .mixer import AdaptiveMixer

class MixerGestureController:
    """
    Translates hand gesture events into AdaptiveMixer commands.

    The existing gesture detection system should call process_gesture()
    with the detected gesture name whenever a gesture is recognized.
    """

    # Gesture-to-action mapping. Customize these strings to match
    # whatever gesture labels your existing system produces.
    INTENSITY_UP_GESTURES = {"open_palm_raise", "palm_up", "swipe_up"}
    INTENSITY_DOWN_GESTURES = {"open_palm_lower", "palm_down", "swipe_down"}
    COMBAT_GESTURES = {"fist", "closed_fist", "fist_clench"}
    CALM_GESTURES = {"open_hand", "flat_hand", "peace"}
    PANIC_GESTURES = {"two_hands_close", "both_fists"}
    CRESCENDO_GESTURES = {"two_hands_spread", "spread"}

    # Finger count to leitmotif index mapping
    # When a "finger_count_N" gesture is detected, trigger leitmotif N-1
    FINGER_LEITMOTIF_PREFIX = "finger_count_"

    def __init__(self, mixer: AdaptiveMixer):
        self._mixer = mixer
        self._current_intensity: int = 0
        self._max_intensity: int = 3

    def process_gesture(self, gesture_name: str, confidence: float = 1.0):
        """
        Process a detected gesture and send the appropriate command to the mixer.

        Args:
            gesture_name: The name/label of the detected gesture.
            confidence: Detection confidence (0.0 to 1.0). Ignore low-confidence detections.
        """
        if confidence < 0.7:
            return

        gesture = gesture_name.lower().strip()

        # Intensity up
        if gesture in self.INTENSITY_UP_GESTURES:
            self._current_intensity = min(self._current_intensity + 1, self._max_intensity)
            self._mixer.set_intensity(self._current_intensity)
            return

        # Intensity down
        if gesture in self.INTENSITY_DOWN_GESTURES:
            self._current_intensity = max(self._current_intensity - 1, 0)
            self._mixer.set_intensity(self._current_intensity)
            return

        # Combat mode (jump to max intensity)
        if gesture in self.COMBAT_GESTURES:
            self._current_intensity = self._max_intensity
            self._mixer.set_intensity(self._current_intensity)
            return

        # Calm mode (drop to base)
        if gesture in self.CALM_GESTURES:
            self._current_intensity = 0
            self._mixer.set_intensity(self._current_intensity)
            return

        # Panic (silence everything)
        if gesture in self.PANIC_GESTURES:
            self._mixer.panic()
            self._current_intensity = 0
            return

        # Finger count -> leitmotif trigger
        if gesture.startswith(self.FINGER_LEITMOTIF_PREFIX):
            try:
                finger_count = int(gesture[len(self.FINGER_LEITMOTIF_PREFIX):])
                leitmotifs = self._mixer.get_leitmotif_names()
                if 0 < finger_count <= len(leitmotifs):
                    self._mixer.trigger_leitmotif(leitmotifs[finger_count - 1])
            except (ValueError, IndexError):
                pass
            return

    def reset(self):
        """Reset intensity to base level."""
        self._current_intensity = 0
```

---

## 11. Module 6: MixerKeyboardController

**File**: `adaptive_mixer/keyboard_controller.py`

```python
"""
MixerKeyboardController — Maps keyboard hotkeys to adaptive mixer commands.

IMPORTANT: Integrate this with the existing hotkey system in ConductorSBN.
This module provides a handle_key() method that should be called from
whatever keyboard event handler already exists.

If the app uses tkinter, register these in the bind() calls.
If it uses pygame events, add to the event loop.
If it uses pynput or keyboard library, add to the existing listener.
"""

from typing import Optional
from .mixer import AdaptiveMixer

class MixerKeyboardController:
    def __init__(self, mixer: AdaptiveMixer):
        self._mixer = mixer
        self._current_scene_index: int = 0
        self._available_scenes: list[str] = []  # Populated by SceneManager

    def set_available_scenes(self, scene_dirs: list[str]):
        """Set the list of available scene directories for cycling."""
        self._available_scenes = scene_dirs

    def handle_key(self, key: str):
        """
        Process a key press. Call this from the existing keyboard handler.

        Key mapping:
            1-9:        Toggle stems by index
            F1-F10:     Load scene by index
            Up/Down:    Adjust master volume
            Left/Right: Adjust intensity
            Space:      Panic (fade all to silence)
            Tab:        Cycle and trigger next leitmotif
            L:          Stop current leitmotif
            [:          Decrease BPM by 5
            ]:          Increase BPM by 5

        Args:
            key: Key identifier string. Format depends on your UI framework.
                 Examples: "1", "F1", "Up", "Down", "space", "Tab", etc.
        """
        key_lower = key.lower() if isinstance(key, str) else str(key)

        # Number keys 1-9: toggle stem by index
        if key_lower.isdigit() and key_lower != "0":
            idx = int(key_lower) - 1
            stems = self._mixer.get_stem_names()
            if idx < len(stems):
                self._mixer.toggle_stem(stems[idx])
            return

        # F-keys: load scene by index
        if key_lower.startswith("f") and key_lower[1:].isdigit():
            scene_idx = int(key_lower[1:]) - 1
            if 0 <= scene_idx < len(self._available_scenes):
                self._mixer.load_scene(self._available_scenes[scene_idx])
            return

        # Arrow keys: volume and intensity
        if key_lower in ("up", "arrow_up"):
            vol = min(self._mixer._master_volume + 0.05, 1.0)
            self._mixer.set_master_volume(vol)
            return
        if key_lower in ("down", "arrow_down"):
            vol = max(self._mixer._master_volume - 0.05, 0.0)
            self._mixer.set_master_volume(vol)
            return
        if key_lower in ("right", "arrow_right"):
            # Increase intensity
            current = 0
            for lg in self._mixer._layer_groups.values():
                for sid in lg.get("stems", []):
                    if sid in self._mixer._stems and self._mixer._stems[sid].is_audible:
                        current = max(current, lg.get("intensity", 0))
            self._mixer.set_intensity(min(current + 1, 3))
            return
        if key_lower in ("left", "arrow_left"):
            current = 3
            for lg in self._mixer._layer_groups.values():
                for sid in lg.get("stems", []):
                    if sid in self._mixer._stems and self._mixer._stems[sid].is_audible:
                        current = min(current, lg.get("intensity", 0))
            self._mixer.set_intensity(max(current - 1, 0))
            return

        # Space: panic
        if key_lower in ("space", " "):
            self._mixer.panic()
            return

        # Tab: cycle leitmotifs
        if key_lower == "tab":
            leitmotifs = self._mixer.get_leitmotif_names()
            if leitmotifs:
                if not hasattr(self, "_leitmotif_cycle_idx"):
                    self._leitmotif_cycle_idx = 0
                self._mixer.trigger_leitmotif(leitmotifs[self._leitmotif_cycle_idx])
                self._leitmotif_cycle_idx = (self._leitmotif_cycle_idx + 1) % len(leitmotifs)
            return

        # L: stop leitmotif
        if key_lower == "l":
            self._mixer.stop_leitmotif()
            return

        # BPM adjustment
        if key_lower in ("[", "bracketleft"):
            self._mixer.clock.set_bpm(max(60, self._mixer.clock.bpm - 5))
            return
        if key_lower in ("]", "bracketright"):
            self._mixer.clock.set_bpm(min(200, self._mixer.clock.bpm + 5))
            return
```

---

## 12. Module 7: SceneManager

**File**: `adaptive_mixer/scene_manager.py`

```python
"""
SceneManager — Discovers and manages available scene packs.
"""

import json
from pathlib import Path
from typing import Optional

class SceneManager:
    def __init__(self, scenes_dir: str = "assets/music/scenes"):
        self._scenes_dir = Path(scenes_dir)
        self._scenes: dict[str, dict] = {}  # scene_id -> {"path": ..., "config": ...}
        self.scan()

    def scan(self):
        """Scan the scenes directory for valid scene packs."""
        self._scenes.clear()
        if not self._scenes_dir.exists():
            return

        for scene_dir in sorted(self._scenes_dir.iterdir()):
            if scene_dir.is_dir():
                config_path = scene_dir / "scene.json"
                if config_path.exists():
                    try:
                        with open(config_path, "r") as f:
                            config = json.load(f)
                        scene_id = scene_dir.name
                        self._scenes[scene_id] = {
                            "path": str(scene_dir),
                            "config": config,
                            "name": config.get("name", scene_id),
                        }
                    except Exception as e:
                        print(f"Warning: Invalid scene config in {scene_dir}: {e}")

    def get_scene_list(self) -> list[dict]:
        """Return list of available scenes with id, name, path."""
        return [
            {"id": sid, "name": s["name"], "path": s["path"]}
            for sid, s in self._scenes.items()
        ]

    def get_scene_paths(self) -> list[str]:
        """Return list of scene directory paths (for keyboard controller)."""
        return [s["path"] for s in self._scenes.values()]

    def get_scene_path(self, scene_id: str) -> Optional[str]:
        if scene_id in self._scenes:
            return self._scenes[scene_id]["path"]
        return None
```

---

## 13. Integration Points with Existing App

**File**: `adaptive_mixer/__init__.py`

```python
"""
adaptive_mixer — Dynamic adaptive music mixing system for ConductorSBN.

Import and wire up in the main application like this:

    from adaptive_mixer import AdaptiveMixer, MixerGestureController, \
        MixerKeyboardController, SceneManager

    # Initialize
    scene_mgr = SceneManager("assets/music/scenes")
    mixer = AdaptiveMixer(
        soundfont_path="assets/soundfonts/FluidR3_GM.sf2",
        leitmotif_config_path="assets/leitmotifs/leitmotifs.json",
    )

    gesture_ctrl = MixerGestureController(mixer)
    keyboard_ctrl = MixerKeyboardController(mixer)
    keyboard_ctrl.set_available_scenes(scene_mgr.get_scene_paths())

    # Load first scene and start
    scenes = scene_mgr.get_scene_list()
    if scenes:
        mixer.load_scene(scenes[0]["path"])
    mixer.start()

    # In your existing gesture callback:
    def on_gesture_detected(gesture_name, confidence):
        # ... your existing gesture handling ...
        gesture_ctrl.process_gesture(gesture_name, confidence)

    # In your existing keyboard handler:
    def on_key_press(key):
        # ... your existing key handling ...
        keyboard_ctrl.handle_key(key)

    # On app shutdown:
    mixer.cleanup()
"""

from .mixer import AdaptiveMixer
from .beat_clock import BeatClock
from .stem_player import StemPlayer
from .midi_generator import MidiGenerator
from .gesture_controller import MixerGestureController
from .keyboard_controller import MixerKeyboardController
from .scene_manager import SceneManager

__all__ = [
    "AdaptiveMixer",
    "BeatClock",
    "StemPlayer",
    "MidiGenerator",
    "MixerGestureController",
    "MixerKeyboardController",
    "SceneManager",
]
```

### Integration Checklist

When integrating with the existing app, you need to:

1. **Find the existing gesture callback** — wherever MediaPipe results are processed, add a call to `gesture_ctrl.process_gesture(gesture_name, confidence)`. This should be ADDITIVE, not replacing the existing gesture handling.

2. **Find the existing keyboard handler** — add `keyboard_ctrl.handle_key(key)` to the existing key event processing. Be careful about key conflicts — if keys 1-9 are already used for soundboard slots, use a modifier (e.g., Ctrl+1-9 for stem toggles) or remap.

3. **Find the app shutdown/cleanup path** — add `mixer.cleanup()` to ensure FluidSynth and sounddevice resources are released.

4. **Check for audio device conflicts** — if the existing app already opens an audio output device (e.g., via pygame.mixer), there may be a conflict with sounddevice trying to open the same device. Solutions:
   - Use sounddevice's `device` parameter to specify a different output device
   - Replace the existing pygame.mixer usage with the new AdaptiveMixer for music (keep pygame.mixer for short sound effects only)
   - On Linux, PulseAudio/PipeWire typically allows multiple simultaneous streams

5. **Thread safety** — the AdaptiveMixer audio callback runs in a C-level thread. The gesture and keyboard controllers call mixer methods from the main/UI thread. The `threading.Lock` in the mixer handles this, but be aware that `load_scene()` blocks for the crossfade duration and should NOT be called from the audio callback.

---

## 14. Audio Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    sounddevice OutputStream                      │
│                    (callback every 1024 frames)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ StemPlayer 0 │  │ StemPlayer 1 │  │ StemPlayer N │   ...    │
│  │ (base_pad)   │  │ (peaceful)   │  │ (combat)     │          │
│  │ vol: 0.6     │  │ vol: 0.0→0.4 │  │ vol: 0.0     │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │ read_chunk()    │                  │                   │
│         ▼                 ▼                  ▼                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Per-stem FX  │  │ Per-stem FX  │  │ (no FX)      │          │
│  │ (optional)   │  │ (optional)   │  │              │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                   │
│         └────────┬────────┴──────────────────┘                  │
│                  ▼                                               │
│           ┌──────────────┐                                      │
│           │   SUM (np +) │ ◄──── MidiGenerator.render_chunk()  │
│           └──────┬───────┘                                      │
│                  ▼                                               │
│           ┌──────────────┐                                      │
│           │ Master Volume│                                      │
│           └──────┬───────┘                                      │
│                  ▼                                               │
│           ┌──────────────┐                                      │
│           │ Master FX    │                                      │
│           │ (pedalboard) │                                      │
│           └──────┬───────┘                                      │
│                  ▼                                               │
│           ┌──────────────┐                                      │
│           │  np.clip()   │                                      │
│           └──────┬───────┘                                      │
│                  ▼                                               │
│              outdata[:]                                          │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌────────────────────┐                   │
│  │  BeatClock   │────▶│ Pending Actions     │                   │
│  │  (thread)    │     │ (quantized fades)   │                   │
│  └──────────────┘     └────────────────────┘                   │
│                                                                  │
│  ┌──────────────────┐  ┌─────────────────────┐                 │
│  │ GestureController│  │ KeyboardController   │                 │
│  │ (from UI thread) │  │ (from UI thread)     │                 │
│  └──────────────────┘  └─────────────────────┘                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 15. Stem Preparation Utility

**File**: `tools/prepare_stems.py`

A utility script for preparing stem files from various sources. NOT part of the runtime app — run this beforehand to prepare content.

```python
"""
Stem preparation utility. Run standalone to:
1. Verify all stems in a scene have matching sample rate, channels, and duration
2. Convert/pad stems to match
3. Run Demucs on a full track to extract stems

Usage:
    python tools/prepare_stems.py verify assets/music/scenes/enchanted_forest/
    python tools/prepare_stems.py normalize assets/music/scenes/enchanted_forest/ --sr 44100
    python tools/prepare_stems.py split input_track.mp3 --output assets/music/scenes/new_scene/ --model htdemucs_ft
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def verify_scene(scene_dir: str):
    """Check that all stems in a scene have matching properties."""
    scene_path = Path(scene_dir)
    config_path = scene_path / "scene.json"

    if not config_path.exists():
        print(f"ERROR: No scene.json in {scene_dir}")
        return False

    with open(config_path, "r") as f:
        config = json.load(f)

    issues = []
    properties = {}

    for stem_id, stem_config in config.get("stems", {}).items():
        file_path = scene_path / stem_config["file"]
        if not file_path.exists():
            issues.append(f"  MISSING: {stem_config['file']}")
            continue

        info = sf.info(str(file_path))
        props = {
            "samplerate": info.samplerate,
            "channels": info.channels,
            "frames": info.frames,
            "duration": info.duration,
            "format": info.format,
            "subtype": info.subtype,
        }
        properties[stem_id] = props

        print(f"  {stem_id}: {info.samplerate}Hz, {info.channels}ch, "
              f"{info.duration:.1f}s, {info.subtype}")

    if not properties:
        print("No stems found!")
        return False

    # Check consistency
    srs = set(p["samplerate"] for p in properties.values())
    chs = set(p["channels"] for p in properties.values())
    durs = set(round(p["duration"], 1) for p in properties.values())

    if len(srs) > 1:
        issues.append(f"  MISMATCH sample rates: {srs}")
    if len(chs) > 1:
        issues.append(f"  MISMATCH channel counts: {chs}")
    if len(durs) > 1:
        issues.append(f"  MISMATCH durations: {durs}")
        print(f"  (Shortest: {min(p['duration'] for p in properties.values()):.1f}s, "
              f"Longest: {max(p['duration'] for p in properties.values()):.1f}s)")

    if issues:
        print("\nISSUES FOUND:")
        for issue in issues:
            print(issue)
        return False
    else:
        print("\nAll stems OK!")
        return True


def normalize_scene(scene_dir: str, target_sr: int = 44100, target_channels: int = 2):
    """Convert all stems to matching sample rate, channels, and pad to same duration."""
    scene_path = Path(scene_dir)
    config_path = scene_path / "scene.json"

    with open(config_path, "r") as f:
        config = json.load(f)

    # First pass: find max duration
    max_duration = 0
    for stem_config in config.get("stems", {}).values():
        file_path = scene_path / stem_config["file"]
        if file_path.exists():
            info = sf.info(str(file_path))
            max_duration = max(max_duration, info.duration)

    target_frames = int(max_duration * target_sr)
    print(f"Normalizing to: {target_sr}Hz, {target_channels}ch, {max_duration:.1f}s ({target_frames} frames)")

    # Second pass: convert each stem
    for stem_id, stem_config in config.get("stems", {}).items():
        file_path = scene_path / stem_config["file"]
        if not file_path.exists():
            continue

        data, sr = sf.read(str(file_path), dtype="float32", always_2d=True)

        changed = False

        # Resample if needed (simple approach — for production use librosa.resample)
        if sr != target_sr:
            print(f"  {stem_id}: Resampling {sr} -> {target_sr} Hz")
            # Simple linear interpolation resample (use librosa for better quality)
            ratio = target_sr / sr
            new_length = int(data.shape[0] * ratio)
            indices = np.linspace(0, data.shape[0] - 1, new_length)
            new_data = np.zeros((new_length, data.shape[1]), dtype=np.float32)
            for ch in range(data.shape[1]):
                new_data[:, ch] = np.interp(indices, np.arange(data.shape[0]), data[:, ch])
            data = new_data
            changed = True

        # Convert channels
        if data.shape[1] != target_channels:
            print(f"  {stem_id}: Converting {data.shape[1]}ch -> {target_channels}ch")
            if data.shape[1] == 1 and target_channels == 2:
                data = np.column_stack([data[:, 0], data[:, 0]])
            elif data.shape[1] == 2 and target_channels == 1:
                data = np.mean(data, axis=1, keepdims=True)
            changed = True

        # Pad or trim to target length
        if data.shape[0] != target_frames:
            if data.shape[0] < target_frames:
                print(f"  {stem_id}: Padding {data.shape[0]} -> {target_frames} frames")
                pad = np.zeros((target_frames - data.shape[0], target_channels), dtype=np.float32)
                data = np.vstack([data, pad])
            else:
                print(f"  {stem_id}: Trimming {data.shape[0]} -> {target_frames} frames")
                data = data[:target_frames]
            changed = True

        if changed:
            # Write back (backup original first)
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            if not backup_path.exists():
                file_path.rename(backup_path)
            sf.write(str(file_path), data, target_sr, subtype="PCM_16")
            print(f"  {stem_id}: Saved (backup at {backup_path.name})")
        else:
            print(f"  {stem_id}: No changes needed")


def split_with_demucs(input_file: str, output_dir: str, model: str = "htdemucs_ft"):
    """Run Demucs stem separation on an input audio file."""
    try:
        import demucs.separate
    except ImportError:
        print("ERROR: Demucs not installed. Install with: pip install demucs")
        sys.exit(1)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Running Demucs ({model}) on {input_file}...")
    args = [
        "--name", model,
        "--out", str(output_path / "demucs_output"),
        "--mp3",  # Output as MP3 (use --wav for WAV)
        input_file,
    ]
    demucs.separate.main(args)
    print(f"Stems saved to {output_path / 'demucs_output'}")
    print("You'll need to create scene.json and rename stems to match the schema.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stem preparation utility")
    sub = parser.add_subparsers(dest="command")

    verify_p = sub.add_parser("verify", help="Verify scene stems consistency")
    verify_p.add_argument("scene_dir")

    norm_p = sub.add_parser("normalize", help="Normalize stems to match")
    norm_p.add_argument("scene_dir")
    norm_p.add_argument("--sr", type=int, default=44100)
    norm_p.add_argument("--channels", type=int, default=2)

    split_p = sub.add_parser("split", help="Split a track with Demucs")
    split_p.add_argument("input_file")
    split_p.add_argument("--output", default="assets/music/scenes/new_scene/")
    split_p.add_argument("--model", default="htdemucs_ft")

    args = parser.parse_args()

    if args.command == "verify":
        verify_scene(args.scene_dir)
    elif args.command == "normalize":
        normalize_scene(args.scene_dir, args.sr, args.channels)
    elif args.command == "split":
        split_with_demucs(args.input_file, args.output, args.model)
    else:
        parser.print_help()
```

---

## 16. Testing Strategy

### Unit Tests

Create `tests/test_adaptive_mixer.py`:

```python
"""
Tests for the adaptive mixer system.
Run with: pytest tests/test_adaptive_mixer.py -v
"""
import numpy as np
import pytest
import tempfile
import json
import os
import soundfile as sf

# Test StemPlayer with a generated test tone
class TestStemPlayer:
    def _make_test_wav(self, duration=2.0, sr=44100, freq=440.0):
        """Generate a test sine wave WAV file."""
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        mono = (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)
        stereo = np.column_stack([mono, mono])
        path = tempfile.mktemp(suffix=".wav")
        sf.write(path, stereo, sr)
        return path

    def test_load_and_read(self):
        from adaptive_mixer.stem_player import StemPlayer
        path = self._make_test_wav()
        try:
            stem = StemPlayer(path, sample_rate=44100)
            stem.unmute(volume=1.0, fade_seconds=0)
            chunk = stem.read_chunk(1024)
            assert chunk.shape == (1024, 2)
            assert np.max(np.abs(chunk)) > 0.1  # Should have audio
        finally:
            os.unlink(path)

    def test_muted_returns_silence(self):
        from adaptive_mixer.stem_player import StemPlayer
        path = self._make_test_wav()
        try:
            stem = StemPlayer(path, sample_rate=44100)
            # Default is muted
            chunk = stem.read_chunk(1024)
            assert np.allclose(chunk, 0.0)
        finally:
            os.unlink(path)

    def test_volume_fade(self):
        from adaptive_mixer.stem_player import StemPlayer
        path = self._make_test_wav()
        try:
            stem = StemPlayer(path, sample_rate=44100)
            stem.unmute(volume=0.5, fade_seconds=0.1)
            # Read enough chunks to complete the fade
            for _ in range(10):
                chunk = stem.read_chunk(4410)  # 0.1 seconds
            # Volume should be at target now
            assert abs(stem.current_volume - 0.5) < 0.01
        finally:
            os.unlink(path)

    def test_loop(self):
        from adaptive_mixer.stem_player import StemPlayer
        path = self._make_test_wav(duration=0.1)  # Very short
        try:
            stem = StemPlayer(path, sample_rate=44100)
            stem.loop = True
            stem.unmute(volume=1.0, fade_seconds=0)
            # Read more frames than the file contains
            chunk = stem.read_chunk(44100)  # 1 second > 0.1 second file
            assert chunk.shape == (44100, 2)
            assert np.max(np.abs(chunk)) > 0  # Should have looped audio
        finally:
            os.unlink(path)


class TestBeatClock:
    def test_position_tracking(self):
        from adaptive_mixer.beat_clock import BeatClock
        import time
        clock = BeatClock(bpm=120, time_signature=(4, 4))
        clock.start()
        time.sleep(0.55)  # Just over 1 beat at 120 BPM
        bar, beat, frac = clock.get_position()
        assert bar == 0
        assert beat >= 1  # Should be on beat 1 or later
        clock.stop()

    def test_bar_boundary(self):
        from adaptive_mixer.beat_clock import BeatClock
        clock = BeatClock(bpm=120, time_signature=(4, 4))
        clock.start()
        boundary = clock.next_bar_boundary()
        import time
        assert boundary > time.monotonic()
        clock.stop()
```

### Manual Integration Test

Create `tools/test_mixer_standalone.py`:

```python
"""
Standalone test of the adaptive mixer without the full ConductorSBN app.
Creates test stems, loads them, and allows keyboard control.

Run: python tools/test_mixer_standalone.py

Controls:
    1-4: Toggle stems
    Up/Down: Master volume
    Space: Panic
    q: Quit
"""
import sys
import os
import tempfile
import json
import numpy as np
import soundfile as sf

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adaptive_mixer import AdaptiveMixer

def generate_test_scene():
    """Generate a temporary test scene with synthesized stems."""
    scene_dir = tempfile.mkdtemp(prefix="test_scene_")
    sr = 44100
    duration = 10.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)

    stems = {
        "base_pad": np.sin(2 * np.pi * 110 * t) * 0.3,   # Low A drone
        "peaceful": np.sin(2 * np.pi * 440 * t) * 0.2 * (1 + np.sin(2 * np.pi * 0.5 * t)) * 0.5,  # Tremolo A
        "tension": np.sin(2 * np.pi * 233 * t) * 0.25,    # Bb (dissonant)
        "combat": np.sign(np.sin(2 * np.pi * 2 * t)) * 0.4 * (np.random.rand(len(t)) * 0.5 + 0.5),  # Noisy pulse
    }

    config = {
        "name": "Test Scene",
        "bpm": 120,
        "key": "Am",
        "time_signature": [4, 4],
        "stems": {},
        "layer_groups": {
            "base": {"stems": ["base_pad"], "intensity": 0},
            "peaceful": {"stems": ["peaceful"], "intensity": 1},
            "tension": {"stems": ["tension"], "intensity": 2},
            "combat": {"stems": ["combat"], "intensity": 3},
        }
    }

    for name, audio in stems.items():
        stereo = np.column_stack([audio, audio]).astype(np.float32)
        filename = f"{name}.wav"
        sf.write(os.path.join(scene_dir, filename), stereo, sr)
        config["stems"][name] = {
            "file": filename,
            "layer": name,
            "default_volume": 0.5,
            "always_on": name == "base_pad",
        }

    with open(os.path.join(scene_dir, "scene.json"), "w") as f:
        json.dump(config, f, indent=2)

    return scene_dir

def main():
    print("Generating test scene...")
    scene_dir = generate_test_scene()
    print(f"Test scene at: {scene_dir}")

    # Create mixer without FluidSynth (no soundfont needed for this test)
    mixer = AdaptiveMixer(
        soundfont_path="nonexistent.sf2",  # Will print a warning but continue
    )

    print("Loading scene...")
    mixer.load_scene(scene_dir)

    print("Starting mixer...")
    mixer.start()

    print("\nControls:")
    print("  1-4: Toggle stems (base_pad, peaceful, tension, combat)")
    print("  u/d: Master volume up/down")
    print("  space: Panic (silence all)")
    print("  q: Quit")
    print(f"\nPlaying: {mixer.get_current_scene_name()}")
    print(f"Stems: {mixer.get_stem_names()}")

    try:
        import msvcrt  # Windows
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getch().decode("utf-8", errors="ignore")
                if key == "q":
                    break
                elif key in "1234":
                    stems = mixer.get_stem_names()
                    idx = int(key) - 1
                    if idx < len(stems):
                        mixer.toggle_stem(stems[idx])
                        status = mixer.get_stem_status()
                        print(f"  {stems[idx]}: {'ON' if status[stems[idx]]['is_audible'] else 'fading...'}")
                elif key == "u":
                    mixer.set_master_volume(min(mixer._master_volume + 0.1, 1.0))
                    print(f"  Master volume: {mixer._master_volume:.1f}")
                elif key == "d":
                    mixer.set_master_volume(max(mixer._master_volume - 0.1, 0.0))
                    print(f"  Master volume: {mixer._master_volume:.1f}")
                elif key == " ":
                    mixer.panic()
                    print("  PANIC — all silent")
    except ImportError:
        # Unix — use simpler approach
        import select
        import tty
        import termios
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while True:
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    key = sys.stdin.read(1)
                    if key == "q":
                        break
                    elif key in "1234":
                        stems = mixer.get_stem_names()
                        idx = int(key) - 1
                        if idx < len(stems):
                            mixer.toggle_stem(stems[idx])
                            print(f"  Toggled: {stems[idx]}")
                    elif key == "u":
                        mixer.set_master_volume(min(mixer._master_volume + 0.1, 1.0))
                        print(f"  Master volume: {mixer._master_volume:.1f}")
                    elif key == "d":
                        mixer.set_master_volume(max(mixer._master_volume - 0.1, 0.0))
                        print(f"  Master volume: {mixer._master_volume:.1f}")
                    elif key == " ":
                        mixer.panic()
                        print("  PANIC")
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    print("\nStopping...")
    mixer.cleanup()

    # Cleanup temp files
    import shutil
    shutil.rmtree(scene_dir, ignore_errors=True)
    print("Done.")

if __name__ == "__main__":
    main()
```

---

## 17. Phased Implementation Order

Implement in this order. Each phase should be tested before moving to the next.

### Phase 1: Core Audio Engine (Do this first)
1. Create the `adaptive_mixer/` package directory with `__init__.py`
2. Implement `beat_clock.py`
3. Implement `stem_player.py`
4. Implement `mixer.py` (without MidiGenerator integration — just stems)
5. Implement `scene_manager.py`
6. Create `tools/prepare_stems.py`
7. Create a test scene with simple generated tones
8. Create `tools/test_mixer_standalone.py`
9. **Test**: Run the standalone test, verify stems can be toggled and faded

### Phase 2: Keyboard & Gesture Integration
1. Implement `keyboard_controller.py`
2. Implement `gesture_controller.py`
3. Wire both controllers into the existing ConductorSBN app
4. **Test**: Verify keyboard hotkeys toggle stems, gestures change intensity

### Phase 3: MIDI Leitmotifs
1. Implement `midi_generator.py`
2. Enable MidiGenerator in `mixer.py` (it's already coded, just needs a valid soundfont)
3. Create `assets/leitmotifs/leitmotifs.json` with test leitmotifs
4. Download and place a SoundFont file
5. **Test**: Trigger leitmotifs via keyboard (Tab key), verify they mix with audio stems

### Phase 4: Content Pipeline
1. Create real scene packs (either compose, use AI generation + Demucs, or find royalty-free stems)
2. Use `tools/prepare_stems.py verify` and `normalize` to ensure consistency
3. Create multiple scenes for different RPG environments
4. Define character leitmotifs in `leitmotifs.json`

---

## 18. Important Technical Constraints

### Audio Callback Rules
The `_audio_callback` in `AdaptiveMixer` runs in a **real-time C thread** managed by PortAudio. Inside this callback you MUST NOT:
- Allocate large objects or call `malloc` (numpy operations that create new arrays are OK for small sizes but be cautious)
- Do file I/O
- Acquire locks that are heavily contended (the `self._lock` is acquired briefly per callback and should be fine)
- Call `print()` in production (acceptable for debugging)
- Sleep or wait

### StemPlayer Memory
Each stem is loaded entirely into memory as a float32 numpy array. A 4-minute stereo stem at 44100 Hz occupies about 84 MB. With 5 stems, that's ~420 MB. This is manageable on modern systems but be aware of it. If memory is a concern, stems can be shortened (2-minute loops instead of 4-minute) or compressed to 16-bit integer representation and converted on-the-fly.

### FluidSynth Thread Safety
`pyfluidsynth`'s `get_samples()` is called from the audio callback thread. FluidSynth is generally thread-safe for this use case, but `program_select()` and `sfload()` should only be called from the main thread (which they are, since `trigger_leitmotif` is called from gesture/keyboard handlers, not the callback).

### pedalboard in the Audio Callback
The pedalboard documentation notes that Python's garbage collector can cause audio glitches in real-time contexts. For the master effects chain, this is acceptable since we're processing buffered audio, not strict real-time. If you experience clicks/pops, try:
- Increasing `BLOCK_SIZE` to 2048 or 4096
- Disabling per-stem effects (use only master effects)
- Pre-allocating the numpy arrays used in the callback

### Platform Notes
- **Windows**: sounddevice uses WASAPI by default. If you experience latency issues, try `latency='low'` or specify `device` explicitly.
- **macOS**: CoreAudio works well. Use `latency='low'`.
- **Linux**: PulseAudio/PipeWire may add latency. For lowest latency, install JACK and configure sounddevice to use it: `sd.default.hostapi = 'jack'`.
