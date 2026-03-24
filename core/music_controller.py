"""
music_controller.py — Music playback controller for ConductorSBN.

Provides a unified interface for controlling background music tracks,
with a local file implementation via pygame.mixer.music and an optional
Spotify scaffold.
"""

import os
import time
import yaml
from abc import ABC, abstractmethod
from threading import Thread, Event
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum, auto


class PlaybackState(Enum):
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()
    FADING_IN = auto()
    FADING_OUT = auto()


@dataclass
class Track:
    name: str
    source: str
    duration_seconds: Optional[float] = None
    metadata: dict = field(default_factory=dict)


class MusicController(ABC):
    @abstractmethod
    def load_library(self, source: str) -> list[Track]: ...
    @abstractmethod
    def play(self, track: Track): ...
    @abstractmethod
    def pause(self): ...
    @abstractmethod
    def resume(self): ...
    @abstractmethod
    def stop(self): ...
    @abstractmethod
    def set_volume(self, level: float): ...
    @abstractmethod
    def get_volume(self) -> float: ...
    @abstractmethod
    def fade_in(self, duration_ms: int = 2000): ...
    @abstractmethod
    def fade_out(self, duration_ms: int = 2000): ...
    @abstractmethod
    def get_state(self) -> PlaybackState: ...
    @abstractmethod
    def get_current_track(self) -> Optional[Track]: ...


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".mp4", ".m4a"}


class LocalMusicController(MusicController):
    """Plays music from a local folder using pygame.mixer.music."""

    def __init__(self):
        from pygame import mixer as _mixer
        if not _mixer.get_init():
            _mixer.init()
        self._mixer_music = _mixer.music

        self._volume = 0.7
        self._state = PlaybackState.STOPPED
        self._current_track: Optional[Track] = None
        self._library: list[Track] = []
        self._library_index = 0

        self._fade_thread: Optional[Thread] = None
        self._fade_stop = Event()

    def load_library(self, source: str) -> list[Track]:
        if not os.path.isdir(source):
            print(f"[Music] Folder not found: {source}")
            return []

        tracks = []
        for fname in sorted(os.listdir(source)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                path = os.path.join(source, fname)
                name = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
                tracks.append(Track(name=name, source=path))

        self._library = tracks
        self._library_index = 0
        print(f"[Music] Loaded {len(tracks)} tracks from {source}")
        return tracks

    @property
    def library(self) -> list[Track]:
        return self._library

    def play(self, track: Track):
        self._fade_stop.set()
        try:
            self._mixer_music.load(track.source)
            self._mixer_music.set_volume(self._volume)
            self._mixer_music.play()
            self._current_track = track
            self._state = PlaybackState.PLAYING
            for i, t in enumerate(self._library):
                if t.source == track.source:
                    self._library_index = i
                    break
            print(f"[Music] Playing: {track.name}")
        except Exception as e:
            print(f"[Music] Error playing {track.name}: {e}")

    def play_by_index(self, index: int):
        if 0 <= index < len(self._library):
            self.play(self._library[index])

    def play_next(self):
        if not self._library:
            return
        self._library_index = (self._library_index + 1) % len(self._library)
        self.play(self._library[self._library_index])

    def play_previous(self):
        if not self._library:
            return
        self._library_index = (self._library_index - 1) % len(self._library)
        self.play(self._library[self._library_index])

    def pause(self):
        if self._state == PlaybackState.PLAYING:
            self._mixer_music.pause()
            self._state = PlaybackState.PAUSED

    def resume(self):
        if self._state == PlaybackState.PAUSED:
            self._mixer_music.unpause()
            self._state = PlaybackState.PLAYING
        elif self._state == PlaybackState.STOPPED and self._library:
            self.play(self._library[self._library_index])

    def stop(self):
        self._fade_stop.set()
        self._mixer_music.stop()
        self._state = PlaybackState.STOPPED
        self._current_track = None

    def set_volume(self, level: float):
        self._volume = max(0.0, min(1.0, level))
        if self._state in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            self._mixer_music.set_volume(self._volume)

    def get_volume(self) -> float:
        return self._volume

    def fade_in(self, duration_ms: int = 2000):
        self._fade_stop.set()
        time.sleep(0.05)
        self._fade_stop.clear()
        target = self._volume
        self._state = PlaybackState.FADING_IN

        def _fade():
            steps = max(1, duration_ms // 50)
            for i in range(steps + 1):
                if self._fade_stop.is_set():
                    return
                self._mixer_music.set_volume(target * (i / steps))
                time.sleep(0.05)
            self._state = PlaybackState.PLAYING

        self._fade_thread = Thread(target=_fade, daemon=True)
        self._fade_thread.start()

    def fade_out(self, duration_ms: int = 2000):
        self._fade_stop.set()
        time.sleep(0.05)
        self._fade_stop.clear()
        start_vol = self._mixer_music.get_volume()
        self._state = PlaybackState.FADING_OUT

        def _fade():
            steps = max(1, duration_ms // 50)
            for i in range(steps + 1):
                if self._fade_stop.is_set():
                    return
                self._mixer_music.set_volume(start_vol * (1 - i / steps))
                time.sleep(0.05)
            self._mixer_music.pause()
            self._state = PlaybackState.PAUSED

        self._fade_thread = Thread(target=_fade, daemon=True)
        self._fade_thread.start()

    def get_state(self) -> PlaybackState:
        if self._state == PlaybackState.PLAYING and not self._mixer_music.get_busy():
            self._state = PlaybackState.STOPPED
            self._current_track = None
        return self._state

    def get_current_track(self) -> Optional[Track]:
        return self._current_track


# ── Binding Manager ───────────────────────────────────────────────

MUSIC_CONFIG_PATH = "config/music_config.yaml"


class MusicBindingManager:
    """Manages key → track index mappings, persisted to YAML."""

    def __init__(self, config_path: str = MUSIC_CONFIG_PATH):
        self.config_path = config_path
        self._bindings: dict[str, int] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._bindings = data.get("key_bindings", {})
        else:
            self._bindings = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump({"key_bindings": self._bindings}, f, default_flow_style=False)

    def bind(self, key: str, track_index: int):
        self._bindings[key] = track_index
        self._save()

    def unbind(self, key: str):
        self._bindings.pop(key, None)
        self._save()

    def get_track_for_key(self, key: str) -> Optional[int]:
        return self._bindings.get(key)

    def get_all(self) -> dict[str, int]:
        return dict(self._bindings)


# ── Factory ───────────────────────────────────────────────────────

def create_music_controller() -> MusicController:
    """Return the best available music controller (local file by default)."""
    return LocalMusicController()
