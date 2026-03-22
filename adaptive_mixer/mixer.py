"""
AdaptiveMixer — Main audio mixing engine for ConductorSBN.

Opens a sounddevice OutputStream with a callback that reads from StemPlayers,
optionally mixes in MIDI leitmotifs, applies effects, and outputs to hardware.
"""

import numpy as np
import sounddevice as sd
import json
import threading
from pathlib import Path
from typing import Optional

from .stem_player import StemPlayer
from .midi_generator import (
    MidiGenerator, PrerenderedMidiGenerator,
    FLUIDSYNTH_AVAILABLE, FLUIDSYNTH_EXE,
)
from .beat_clock import BeatClock

try:
    from pedalboard import Pedalboard, Reverb, LowpassFilter
    PEDALBOARD_AVAILABLE = True
except ImportError:
    PEDALBOARD_AVAILABLE = False


class AdaptiveMixer:
    SAMPLE_RATE = 44100
    CHANNELS = 2
    BLOCK_SIZE = 1024  # ~23ms latency @ 44100 Hz
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

        self.clock = BeatClock(bpm=120, time_signature=(4, 4))

        self._stems: dict = {}
        self._layer_groups: dict = {}
        self._scene_config: Optional[dict] = None

        # MIDI generator (optional — requires FluidSynth)
        self._midi_gen: Optional[MidiGenerator] = None
        sf_path = Path(soundfont_path)
        if sf_path.exists() and FLUIDSYNTH_AVAILABLE:
            try:
                self._midi_gen = MidiGenerator(str(sf_path), sample_rate=sample_rate)
                print("[AdaptiveMixer] MIDI generator initialized (direct).")
            except Exception as e:
                print(f"[AdaptiveMixer] Direct FluidSynth failed: {e}")
        # Fallback: subprocess-based pre-rendering via fluidsynth.exe
        if self._midi_gen is None and sf_path.exists() and FLUIDSYNTH_EXE:
            try:
                self._midi_gen = PrerenderedMidiGenerator(
                    str(sf_path), sample_rate=sample_rate
                )
                print("[AdaptiveMixer] MIDI generator initialized (subprocess).")
            except Exception as e:
                print(f"[AdaptiveMixer] Subprocess FluidSynth failed: {e}")
        if self._midi_gen is None:
            if not sf_path.exists():
                print(f"[AdaptiveMixer] SoundFont not found at {soundfont_path}. Leitmotifs disabled.")
            else:
                print("[AdaptiveMixer] No FluidSynth backend available. Leitmotifs disabled.")

        # Load leitmotifs
        lm_path = Path(leitmotif_config_path)
        if lm_path.exists() and self._midi_gen:
            with open(lm_path, "r") as f:
                lm_config = json.load(f)
            self._midi_gen.load_leitmotifs_from_config(lm_config)
            print(f"[AdaptiveMixer] Loaded {len(lm_config.get('leitmotifs', {}))} leitmotifs.")

        self._master_volume: float = 0.8

        # Master effects chain
        self._master_effects = None
        if PEDALBOARD_AVAILABLE:
            self._master_effects = Pedalboard([
                Reverb(room_size=0.3, wet_level=0.15, dry_level=0.85),
            ])

        self._stem_effects: dict = {}
        self._pending_actions: list = []

    # ── Scene Loading ──────────────────────────────────────────────

    def load_scene(self, scene_dir: str, crossfade_seconds: float = 2.0):
        """
        Load a scene from a directory containing scene.json and stem audio files.
        Fades out current scene before loading the new one.

        NOTE: This method blocks for crossfade_seconds when switching scenes.
        Call from a background thread if UI responsiveness is required.
        """
        import time

        scene_path = Path(scene_dir)
        config_path = scene_path / "scene.json"

        if not config_path.exists():
            raise FileNotFoundError(f"No scene.json found in {scene_dir}")

        with open(config_path, "r") as f:
            config = json.load(f)

        # Fade out current stems if playing
        was_playing = self._running
        if was_playing and self._stems:
            with self._lock:
                for stem in self._stems.values():
                    stem.mute(fade_seconds=crossfade_seconds)
            time.sleep(crossfade_seconds + 0.1)

        with self._lock:
            self._stems.clear()
            self._stem_effects.clear()

            self._scene_config = config
            self.clock.bpm = config.get("bpm", 120)
            ts = config.get("time_signature", [4, 4])
            self.clock.beats_per_bar = ts[0]
            self.clock.beat_unit = ts[1]

            for stem_id, stem_config in config.get("stems", {}).items():
                file_path = scene_path / stem_config["file"]
                if not file_path.exists():
                    print(f"[AdaptiveMixer] Warning: Stem file not found: {file_path}")
                    continue

                try:
                    stem = StemPlayer(
                        str(file_path),
                        sample_rate=self.SAMPLE_RATE,
                        channels=self.CHANNELS,
                    )
                    stem.loop = True

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
                    print(f"[AdaptiveMixer] Error loading stem '{stem_id}': {e}")

            self._layer_groups = config.get("layer_groups", {})

            # Per-stem effects
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
                        effects.append(LowpassFilter(
                            cutoff_frequency_hz=fx_config["low_pass_hz"]
                        ))
                    if effects:
                        self._stem_effects[stem_id] = Pedalboard(effects)

            for stem in self._stems.values():
                stem.reset_cursor()

        print(f"[AdaptiveMixer] Loaded scene: {config.get('name', scene_dir)}")

    def get_current_scene_name(self) -> str:
        if self._scene_config:
            return self._scene_config.get("name", "Unknown")
        return "No scene loaded"

    # ── Playback Control ───────────────────────────────────────────

    def start(self):
        """Start the audio output stream and beat clock."""
        if self._running:
            return

        self._running = True
        self.clock.start()
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
        print("[AdaptiveMixer] Audio stream started.")

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
        sounddevice OutputStream callback.
        Runs in a C-level thread — must be fast and must NOT do I/O.
        """
        if status:
            print(f"[AdaptiveMixer] Audio callback status: {status}")

        try:
            mix = np.zeros((frames, self.CHANNELS), dtype=np.float32)

            with self._lock:
                for stem_id, stem in self._stems.items():
                    chunk = stem.read_chunk(frames)

                    if stem_id in self._stem_effects and stem.is_audible:
                        fx = self._stem_effects[stem_id]
                        chunk_t = chunk.T.copy()
                        chunk_t = fx(chunk_t, self.SAMPLE_RATE, reset=False)
                        chunk = chunk_t.T

                    mix += chunk

            if self._midi_gen:
                midi_chunk = self._midi_gen.render_chunk(frames)
                mix += midi_chunk

            mix *= self._master_volume

            if self._master_effects and PEDALBOARD_AVAILABLE:
                mix_t = mix.T.copy()
                mix_t = self._master_effects(mix_t, self.SAMPLE_RATE, reset=False)
                mix = mix_t.T

            np.clip(mix, -1.0, 1.0, out=mix)
            outdata[:] = mix

        except Exception as e:
            outdata.fill(0)
            print(f"[AdaptiveMixer] Audio callback error: {e}")

    # ── Layer / Stem Control ───────────────────────────────────────

    def set_layer_volume(self, layer_name: str, volume: float,
                         fade_seconds: float = DEFAULT_FADE_SECONDS,
                         quantized: bool = True):
        """Set volume for all stems in a layer group."""
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
        """Set volume for a specific stem."""
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
        Set overall intensity level.
        level 0 = base only, 1 = + peaceful, 2 = + tension, 3 = + combat
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

    # ── Leitmotif Control ─────────────────────────────────────────

    def trigger_leitmotif(self, leitmotif_id: str):
        """Trigger a leitmotif to play over the current mix."""
        if self._midi_gen:
            self._midi_gen.trigger_leitmotif(leitmotif_id, self.clock.bpm)

    def stop_leitmotif(self):
        """Stop any playing leitmotif."""
        if self._midi_gen:
            self._midi_gen.stop_leitmotif()

    # ── Master Controls ────────────────────────────────────────────

    def set_master_volume(self, volume: float):
        self._master_volume = max(0.0, min(1.0, volume))

    def panic(self, fade_seconds: float = 1.0):
        """Emergency: fade everything to silence."""
        with self._lock:
            for stem in self._stems.values():
                stem.mute(fade_seconds)
        if self._midi_gen:
            self._midi_gen.stop_leitmotif()

    # ── Quantized Action Processing ────────────────────────────────

    def _process_pending_actions(self, bar_number: int):
        """Called by BeatClock on each bar boundary."""
        actions = self._pending_actions.copy()
        self._pending_actions.clear()
        for action in actions:
            if action["type"] == "set_layer_volume":
                self._apply_layer_volume(
                    action["layer"], action["volume"], action["fade_seconds"]
                )

    # ── Status ─────────────────────────────────────────────────────

    def get_playback_position(self) -> tuple:
        """Return (current_seconds, total_seconds) from the first loaded stem."""
        with self._lock:
            if not self._stems:
                return 0.0, 0.0
            stem = next(iter(self._stems.values()))
            return stem._cursor / self.SAMPLE_RATE, stem._total_frames / self.SAMPLE_RATE

    def seek(self, position_seconds: float):
        """Seek all stems to position_seconds (clamped to valid range)."""
        with self._lock:
            for stem in self._stems.values():
                frame = int(position_seconds * self.SAMPLE_RATE)
                stem._cursor = max(0, min(frame, stem._total_frames - 1))

    def get_stem_status(self) -> dict:
        """Return current volume/mute status of all stems."""
        status = {}
        for stem_id, stem in self._stems.items():
            status[stem_id] = {
                "volume": stem.current_volume,
                "target_volume": stem._target_volume,
                "is_audible": stem.is_audible,
                "muted": stem._muted,
            }
        return status

    def get_layer_names(self) -> list:
        return list(self._layer_groups.keys())

    def get_stem_names(self) -> list:
        return list(self._stems.keys())

    def get_leitmotif_names(self) -> list:
        if self._midi_gen:
            return list(self._midi_gen._leitmotifs.keys())
        return []

    # ── Cleanup ────────────────────────────────────────────────────

    def cleanup(self):
        """Release all resources."""
        self.stop()
        if self._midi_gen:
            self._midi_gen.cleanup()
