"""
BeatClock — Tempo-aware clock for synchronizing adaptive music transitions.

Tracks the current beat and bar position based on a configurable BPM.
Provides methods to schedule callbacks on beat/bar boundaries.
Thread-safe: runs its own timing thread, exposes position via atomic reads.
"""

import threading
import time
from typing import Callable, Optional


class BeatClock:
    def __init__(self, bpm: float = 120.0, time_signature: tuple = (4, 4)):
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

        self._start_time: float = 0.0
        self._total_beats: float = 0.0

        self._beat_callbacks: list = []  # (beat_in_bar, bar_number)
        self._bar_callbacks: list = []   # (bar_number)

    @property
    def beat_duration(self) -> float:
        """Duration of one beat in seconds."""
        return 60.0 / self.bpm

    @property
    def bar_duration(self) -> float:
        """Duration of one bar in seconds."""
        return self.beat_duration * self.beats_per_bar

    def get_position(self) -> tuple:
        """
        Returns (bar_number, beat_in_bar, fractional_beat) — all zero-indexed.
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

    def on_beat(self, callback: Callable):
        """Register a callback fired on every beat: callback(beat_in_bar, bar_number)."""
        self._beat_callbacks.append(callback)

    def on_bar(self, callback: Callable):
        """Register a callback fired on every bar: callback(bar_number)."""
        self._bar_callbacks.append(callback)

    def set_bpm(self, bpm: float):
        """Change BPM. Takes effect immediately. Thread-safe."""
        with self._lock:
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
                        print(f"[BeatClock] Beat callback error: {e}")
                last_beat = beat
            if bar != last_bar:
                for cb in self._bar_callbacks:
                    try:
                        cb(bar)
                    except Exception as e:
                        print(f"[BeatClock] Bar callback error: {e}")
                last_bar = bar
            time.sleep(self.beat_duration * 0.25)
