"""
gesture_detector.py — MediaPipe-based hand gesture detection for ConductorSBN.

Uses the MediaPipe Tasks API (mediapipe >= 0.10.30) with HandLandmarker.
Requires the hand_landmarker.task model file (auto-downloaded on first run).

Dependencies:
    pip install mediapipe opencv-python numpy

Gesture set (rule-based, no ML training required):
    - OPEN_PALM:    All 5 fingers extended          → Resume all sound
    - FIST:         All 5 fingers closed             → Cut all sound
    - THUMBS_UP:    Thumb extended upward            → Volume up
    - THUMBS_DOWN:  Thumb extended downward          → Volume down
    - SWIPE_RIGHT:  Palm moves right across frame    → Fade in
    - SWIPE_LEFT:   Palm moves left across frame     → Fade out
"""

import importlib.util
import os
import time
import urllib.request
from threading import Thread, Event, Lock
from enum import Enum, auto
from typing import Callable, Optional
from dataclasses import dataclass

# Check availability without importing — importing mediapipe triggers matplotlib
# which hangs on Python 3.13 due to a regex bug in matplotlib's docstring parser.
# The real import happens lazily inside start() so app startup is instant.
HAS_MEDIAPIPE = (
    importlib.util.find_spec("mediapipe") is not None
    and importlib.util.find_spec("cv2") is not None
)

# Module-level placeholders populated by _lazy_import()
cv2 = None
np = None
mp = None
mp_python = None
mp_vision = None


def _lazy_import() -> bool:
    """Import mediapipe and cv2 on first use. Returns True on success."""
    global cv2, np, mp, mp_python, mp_vision, HAS_MEDIAPIPE
    if mp is not None:
        return True
    try:
        import cv2 as _cv2
        import numpy as _np
        import mediapipe as _mp
        from mediapipe.tasks import python as _mp_python
        from mediapipe.tasks.python import vision as _mp_vision
        cv2 = _cv2
        np = _np
        mp = _mp
        mp_python = _mp_python
        mp_vision = _mp_vision
        return True
    except Exception as e:
        print(f"[GestureDetector] Import failed: {e}")
        HAS_MEDIAPIPE = False
        return False

MODEL_PATH = "models/hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)


def ensure_model() -> bool:
    """Download the hand landmarker model if it isn't already present."""
    if os.path.exists(MODEL_PATH):
        return True
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    print(f"[GestureDetector] Downloading hand landmarker model to {MODEL_PATH}")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("[GestureDetector] Model downloaded.")
        return True
    except Exception as e:
        print(f"[GestureDetector] Model download failed: {e}")
        return False


class Gesture(Enum):
    NONE = auto()
    OPEN_PALM = auto()
    FIST = auto()
    THUMBS_UP = auto()
    THUMBS_DOWN = auto()
    SWIPE_LEFT = auto()
    SWIPE_RIGHT = auto()


GESTURE_ACTIONS = {
    Gesture.OPEN_PALM:   "resume_all",
    Gesture.FIST:        "cut_all",
    Gesture.THUMBS_UP:   "volume_up",
    Gesture.THUMBS_DOWN: "volume_down",
    Gesture.SWIPE_LEFT:  "fade_out",
    Gesture.SWIPE_RIGHT: "fade_in",
}


@dataclass
class GestureEvent:
    gesture: Gesture
    action: str
    confidence: float
    timestamp: float


def list_cameras(max_check: int = 5) -> list[tuple[int, str]]:
    """Return list of (index, name) for available cameras."""
    if not HAS_MEDIAPIPE or not _lazy_import():
        return []
    import sys as _sys
    backend = cv2.CAP_DSHOW if _sys.platform == "win32" else cv2.CAP_ANY
    available = []
    for i in range(max_check):
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():
            available.append((i, f"Camera {i}"))
            cap.release()
    return available


class GestureDetector:
    """
    Captures webcam frames, runs MediaPipe HandLandmarker (Tasks API),
    classifies gestures via landmark geometry, and calls
    on_gesture(GestureEvent) when detected.
    """

    def __init__(
        self,
        on_gesture: Callable[[GestureEvent], None],
        camera_index: int = 0,
        cooldown_seconds: float = 1.0,
        show_preview: bool = False,
        frame_callback: Optional[Callable] = None,
    ):
        self.on_gesture = on_gesture
        self.camera_index = camera_index
        self.cooldown_seconds = cooldown_seconds
        self.show_preview = show_preview
        self.frame_callback = frame_callback

        self._stop_event = Event()
        self._thread: Optional[Thread] = None

        self._wrist_history: list[tuple[float, float]] = []
        self._swipe_window = 0.4
        self._swipe_threshold = 0.25

        self._last_fired: dict[Gesture, float] = {}
        self._current_gesture: str = "NONE"

        self._latest_result = None
        self._result_lock = Lock()

    @property
    def current_gesture(self) -> str:
        return self._current_gesture

    def start(self):
        if not HAS_MEDIAPIPE or not _lazy_import():
            print("[GestureDetector] mediapipe/cv2 not available.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self):
        if not ensure_model():
            print("[GestureDetector] Cannot start without model file.")
            return

        # On Windows use DirectShow — avoids MSMF frames-not-reading issues
        # and suppresses depth-sensor probe errors from other backends.
        import sys as _sys
        backend = cv2.CAP_DSHOW if _sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.camera_index, backend)
        if not cap.isOpened():
            print(f"[GestureDetector] Cannot open camera {self.camera_index}")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        def _result_cb(result, image, timestamp_ms):
            with self._result_lock:
                self._latest_result = result

        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=mp_vision.RunningMode.LIVE_STREAM,
            num_hands=1,
            min_hand_detection_confidence=0.7,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.6,
            result_callback=_result_cb,
        )

        try:
            with mp_vision.HandLandmarker.create_from_options(options) as landmarker:
                while not self._stop_event.is_set():
                    ret, frame = cap.read()
                    if not ret:
                        continue

                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    landmarker.detect_async(mp_image, int(time.time() * 1000))

                    with self._result_lock:
                        result = self._latest_result

                    gesture = Gesture.NONE
                    confidence = 0.0

                    if result and result.hand_landmarks:
                        landmarks = result.hand_landmarks[0]
                        handedness = (
                            result.handedness[0][0].category_name
                            if result.handedness else "Right"
                        )
                        gesture, confidence = self._classify_gesture(landmarks, handedness)

                        if self.show_preview or self.frame_callback:
                            self._draw_landmarks(frame, landmarks)

                    self._current_gesture = gesture.name

                    if gesture != Gesture.NONE:
                        self._try_fire(gesture, confidence)

                    if self.frame_callback:
                        self.frame_callback(frame, gesture.name)
                    elif self.show_preview:
                        cv2.imshow("ConductorSBN - Gesture Preview", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
                    else:
                        time.sleep(0.03)
        finally:
            cap.release()
            if self.show_preview:
                cv2.destroyAllWindows()

    def _draw_landmarks(self, frame, landmarks):
        h, w = frame.shape[:2]
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
        connections = [
            (0,1),(1,2),(2,3),(3,4),
            (0,5),(5,6),(6,7),(7,8),
            (0,9),(9,10),(10,11),(11,12),
            (0,13),(13,14),(14,15),(15,16),
            (0,17),(17,18),(18,19),(19,20),
            (5,9),(9,13),(13,17),
        ]
        for a, b in connections:
            cv2.line(frame, pts[a], pts[b], (0, 220, 100), 2)
        for p in pts:
            cv2.circle(frame, p, 4, (255, 255, 255), -1)

    def _classify_gesture(self, landmarks, handedness: str) -> tuple[Gesture, float]:
        lm = landmarks

        tip_ids = [8, 12, 16, 20]
        pip_ids = [6, 10, 14, 18]
        fingers_extended = [lm[tip].y < lm[pip].y for tip, pip in zip(tip_ids, pip_ids)]

        thumb_tip = lm[4]
        thumb_ip  = lm[3]
        # Tasks API handedness is from person's perspective (opposite of mirrored camera).
        if handedness == "Right":
            thumb_extended = thumb_tip.x > thumb_ip.x
        else:
            thumb_extended = thumb_tip.x < thumb_ip.x

        all_closed = not any(fingers_extended)
        all_open   = all(fingers_extended)

        now = time.time()
        wrist_x = lm[0].x
        self._wrist_history.append((wrist_x, now))
        self._wrist_history = [(x, t) for x, t in self._wrist_history
                               if now - t < self._swipe_window]

        if len(self._wrist_history) >= 5:
            xs = [x for x, _ in self._wrist_history]
            delta = xs[-1] - xs[0]
            if abs(delta) > self._swipe_threshold:
                return (
                    Gesture.SWIPE_RIGHT if delta > 0 else Gesture.SWIPE_LEFT,
                    min(abs(delta) / 0.5, 1.0),
                )

        if thumb_extended and all_closed and thumb_tip.y < lm[2].y - 0.05:
            return Gesture.THUMBS_UP, 0.85

        if all_closed and not thumb_extended and thumb_tip.y > lm[2].y + 0.05:
            return Gesture.THUMBS_DOWN, 0.85

        if all_open and thumb_extended:
            return Gesture.OPEN_PALM, 0.9

        if all_closed and not thumb_extended:
            return Gesture.FIST, 0.9

        return Gesture.NONE, 0.0

    def _try_fire(self, gesture: Gesture, confidence: float):
        now = time.time()
        if now - self._last_fired.get(gesture, 0.0) < self.cooldown_seconds:
            return
        self._last_fired[gesture] = now
        action = GESTURE_ACTIONS.get(gesture, "unknown")
        event = GestureEvent(gesture=gesture, action=action,
                             confidence=confidence, timestamp=now)
        print(f"[Gesture] {gesture.name} -> {action} (conf={confidence:.2f})")
        self.on_gesture(event)


if __name__ == "__main__":
    def _print(event: GestureEvent):
        print(f"  >>> {event.action}")

    d = GestureDetector(on_gesture=_print, show_preview=True, cooldown_seconds=1.5)
    print("Starting (press Q in preview window to quit)...")
    d.start()
    try:
        while d.is_running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        d.stop()
