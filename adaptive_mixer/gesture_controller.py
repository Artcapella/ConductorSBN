"""
MixerGestureController — Maps hand gestures to adaptive mixer commands.

Integrates with the existing ConductorSBN gesture system by translating
gesture names (from the Gesture enum) into mixer intensity/control actions.

The existing app's gesture names are uppercase (OPEN_PALM, FIST, etc.).
This controller accepts both upper and lowercase gesture names.
"""

from typing import Optional
from .mixer import AdaptiveMixer


class MixerGestureController:
    """
    Translates hand gesture events into AdaptiveMixer commands.

    Wire into the existing gesture system by calling process_gesture()
    from _handle_gesture_action in app.py.

    Existing gesture → action mapping (from gesture_detector.py):
        OPEN_PALM   → resume_all     → also: calm mode (intensity 0)
        FIST        → cut_all        → also: combat mode (max intensity)
        INDEX_POINT → volume_up      → also: intensity up
        PINKY_UP    → volume_down    → also: intensity down
        SWIPE_LEFT  → fade_out       → also: intensity down
        SWIPE_RIGHT → fade_in        → also: intensity up

    These mappings are ADDITIVE — the existing behavior is not replaced.
    """

    def __init__(self, mixer: AdaptiveMixer):
        self._mixer = mixer
        self._current_intensity: int = 0
        self._max_intensity: int = 3
        self._view = None  # Set via set_view() after GUI is built

    def set_view(self, view):
        """Register the AdaptiveMixerView for bidirectional slider sync."""
        self._view = view

    def _notify_view(self):
        """Tell the view that gesture changed the mixer state so it can sync sliders."""
        if self._view is not None:
            try:
                self._view.on_gesture_changed()
            except Exception:
                pass

    def process_gesture(self, gesture_name: str, confidence: float = 1.0):
        """
        Process a detected gesture and send the appropriate command to the mixer.

        Args:
            gesture_name: Name of the detected gesture (e.g. "FIST", "OPEN_PALM").
            confidence: Detection confidence (0.0 to 1.0).
        """
        if confidence < 0.6:
            return

        gesture = gesture_name.upper().strip()

        changed = False

        if gesture == "FIST":
            self._current_intensity = self._max_intensity
            self._mixer.set_intensity(self._current_intensity)
            changed = True

        elif gesture == "OPEN_PALM":
            self._current_intensity = 0
            self._mixer.set_intensity(self._current_intensity)
            changed = True

        elif gesture in ("INDEX_POINT", "SWIPE_RIGHT"):
            self._current_intensity = min(self._current_intensity + 1, self._max_intensity)
            self._mixer.set_intensity(self._current_intensity)
            changed = True

        elif gesture in ("PINKY_UP", "SWIPE_LEFT"):
            self._current_intensity = max(self._current_intensity - 1, 0)
            self._mixer.set_intensity(self._current_intensity)
            changed = True

        if changed:
            self._notify_view()

    def set_intensity(self, level: int):
        """Directly set intensity level (0-3)."""
        self._current_intensity = max(0, min(level, self._max_intensity))
        self._mixer.set_intensity(self._current_intensity)

    def reset(self):
        """Reset intensity to base level."""
        self._current_intensity = 0
