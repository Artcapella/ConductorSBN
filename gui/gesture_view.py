"""
ConductorSBN – Gesture View
Webcam preview with MediaPipe hand gesture detection controls.
"""

import tkinter as tk
from threading import Thread
from typing import Optional

import customtkinter as ctk

try:
    import cv2
    from PIL import Image
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from core.gesture_detector import (
    Gesture, GESTURE_ACTIONS, list_cameras, HAS_MEDIAPIPE,
)


AVAILABLE_ACTIONS = [
    "none", "cut_all", "resume_all", "volume_up", "volume_down",
    "fade_in", "fade_out", "play_music", "pause_music",
    "next_track", "prev_track",
]

GESTURE_NAMES = [g.name for g in Gesture if g != Gesture.NONE]


class GestureView(ctk.CTkFrame):
    """Gesture detection control panel with webcam preview."""

    PREVIEW_W = 480
    PREVIEW_H = 360

    def __init__(self, parent, gesture_detector, dispatch_fn):
        super().__init__(parent, fg_color="transparent")
        self.detector = gesture_detector
        self.dispatch = dispatch_fn  # callable(action: str)
        self._gesture_action_map: dict[str, str] = {
            g: GESTURE_ACTIONS[Gesture[g]].value if hasattr(GESTURE_ACTIONS[Gesture[g]], 'value')
               else GESTURE_ACTIONS[Gesture[g]]
            for g in GESTURE_NAMES
        }
        self._preview_job = None
        self._latest_frame = None
        self._build_ui()

        # Discover cameras in background so the GUI thread never blocks
        if HAS_MEDIAPIPE:
            Thread(target=self._populate_cameras, daemon=True).start()

    def activate(self):
        pass

    def deactivate(self):
        self._cancel_preview()

    # ── Layout ────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_preview_panel()
        self._build_controls_panel()

    def _build_preview_panel(self):
        panel = ctk.CTkFrame(self, corner_radius=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="Webcam Preview",
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        if not HAS_MEDIAPIPE or not HAS_CV2:
            ctk.CTkLabel(
                panel,
                text="MediaPipe / OpenCV not installed.\n\nInstall with:\n  pip install mediapipe opencv-python Pillow",
                font=ctk.CTkFont(size=12), text_color="orange",
                justify="center",
            ).grid(row=1, column=0, padx=20, pady=40)
            return

        self._preview_label = ctk.CTkLabel(
            panel, text="Click 'Start Detection' to begin",
            width=self.PREVIEW_W, height=self.PREVIEW_H)
        self._preview_label.grid(row=1, column=0, padx=12, pady=(0, 8))

        # Gesture status
        self._gesture_var = tk.StringVar(value="No gesture")
        ctk.CTkLabel(panel, textvariable=self._gesture_var,
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=("#3a7ebf", "#5ba3e0")
                     ).grid(row=2, column=0, pady=(0, 12))

    def _build_controls_panel(self):
        panel = ctk.CTkFrame(self, corner_radius=10, width=240)
        panel.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="Controls",
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")

        # Camera selector — default "Camera 0", updated by background thread
        ctk.CTkLabel(panel, text="Camera:", font=ctk.CTkFont(size=12)
                     ).grid(row=1, column=0, padx=12, sticky="w")

        self._cam_var = ctk.StringVar(value="Camera 0")
        self._cam_menu = ctk.CTkOptionMenu(
            panel, values=["Camera 0"], variable=self._cam_var,
            width=200, command=self._on_camera_change)
        self._cam_menu.grid(row=2, column=0, padx=12, pady=(2, 8))

        # Start/Stop button
        self._toggle_btn = ctk.CTkButton(
            panel, text="▶ Start Detection", width=200, height=40,
            command=self._toggle_detection)
        self._toggle_btn.grid(row=3, column=0, padx=12, pady=4)

        # Cooldown slider
        ctk.CTkLabel(panel, text="Cooldown (seconds):",
                     font=ctk.CTkFont(size=12)
                     ).grid(row=4, column=0, padx=12, pady=(12, 0), sticky="w")

        self._cooldown_var = tk.DoubleVar(value=1.0)
        self._cooldown_slider = ctk.CTkSlider(
            panel, from_=0.5, to=3.0, width=200,
            variable=self._cooldown_var,
            command=self._on_cooldown_change)
        self._cooldown_slider.grid(row=5, column=0, padx=12, pady=(2, 0))

        self._cooldown_label = ctk.CTkLabel(
            panel, text="1.0s", font=ctk.CTkFont(size=11))
        self._cooldown_label.grid(row=6, column=0, padx=12, pady=(0, 8))

        # Gesture→Action mapping
        ctk.CTkLabel(panel, text="Gesture Bindings:",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=7, column=0, padx=12, pady=(12, 4), sticky="w")

        scroll = ctk.CTkScrollableFrame(panel, height=200)
        scroll.grid(row=8, column=0, sticky="ew", padx=8, pady=(0, 12))
        scroll.grid_columnconfigure(1, weight=1)

        self._action_vars: dict[str, ctk.StringVar] = {}
        for i, gname in enumerate(GESTURE_NAMES):
            ctk.CTkLabel(scroll, text=gname.replace("_", " ").title(),
                         font=ctk.CTkFont(size=11), anchor="w"
                         ).grid(row=i, column=0, padx=4, pady=2, sticky="w")

            default_action = self._gesture_action_map.get(gname, "none")
            var = ctk.StringVar(value=default_action)
            self._action_vars[gname] = var
            menu = ctk.CTkOptionMenu(
                scroll, values=AVAILABLE_ACTIONS, variable=var,
                width=120, font=ctk.CTkFont(size=10),
                command=lambda a, g=gname: self._on_action_change(g, a))
            menu.grid(row=i, column=1, padx=4, pady=2)

    # ── Camera discovery (background) ─────────────────────────────
    def _populate_cameras(self):
        """Runs in background thread — calls list_cameras() which triggers lazy import."""
        cameras = list_cameras()
        cam_names = [name for _, name in cameras] if cameras else ["Camera 0"]
        self.after(0, lambda: self._cam_menu.configure(values=cam_names))

    # ── Detection toggle ──────────────────────────────────────────
    def _toggle_detection(self):
        if self.detector.is_running:
            self._stop_detection()
        else:
            self._start_detection()

    def _start_detection(self):
        if not HAS_MEDIAPIPE:
            return
        # Disable button and show loading — import can take several seconds
        self._toggle_btn.configure(text="⏳ Loading...", state="disabled")
        Thread(target=self._start_detection_bg, daemon=True).start()

    def _start_detection_bg(self):
        """Background thread: lazy-imports mediapipe then starts the detector."""
        from core.gesture_detector import _lazy_import
        if not _lazy_import():
            self.after(0, lambda: self._toggle_btn.configure(
                text="Import failed", state="normal"))
            return

        # Parse camera index from the selected name ("Camera 0" → 0)
        cam_name = self._cam_var.get()
        try:
            cam_idx = int(cam_name.split()[-1])
        except (ValueError, IndexError):
            cam_idx = 0
        self.detector.camera_index = cam_idx
        self.detector.frame_callback = self._on_frame
        self.detector.start()
        self.after(0, self._on_detection_started)

    def _on_detection_started(self):
        if self.detector.is_running:
            self._toggle_btn.configure(
                text="⏹ Stop Detection", state="normal",
                fg_color="#c62828", hover_color="#b71c1c")
            self._schedule_preview()
        else:
            self._toggle_btn.configure(
                text="▶ Start Detection", state="normal")
            if hasattr(self, "_preview_label"):
                self._preview_label.configure(
                    text="Could not open camera")

    def _stop_detection(self):
        self.detector.frame_callback = None
        self.detector.stop()
        self._cancel_preview()
        self._toggle_btn.configure(
            text="▶ Start Detection",
            fg_color=("#3a7ebf", "#1f538d"),
            hover_color=("#325882", "#14375e"))
        if hasattr(self, "_preview_label"):
            self._preview_label.configure(image=None, text="Camera stopped")

    def _schedule_preview(self):
        self._update_preview()
        self._preview_job = self.after(33, self._schedule_preview)

    def _cancel_preview(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
            self._preview_job = None

    def _on_frame(self, frame, gesture_name: str):
        """Called from detector thread — just store the frame."""
        self._latest_frame = (frame, gesture_name)

    def _update_preview(self):
        """Called on main thread — update the preview label."""
        if self._latest_frame is None:
            return
        frame, gesture_name = self._latest_frame
        if not HAS_CV2:
            return
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            ctk_image = ctk.CTkImage(
                light_image=pil_image,
                dark_image=pil_image,
                size=(self.PREVIEW_W, self.PREVIEW_H),
            )
            if hasattr(self, "_preview_label"):
                self._preview_label.configure(image=ctk_image, text="")
                self._preview_label._image = ctk_image  # keep reference

            display = gesture_name.replace("_", " ").title()
            if gesture_name != "NONE":
                action = self._action_vars.get(gesture_name, ctk.StringVar()).get()
                self._gesture_var.set(f"{display} → {action}")
            else:
                self._gesture_var.set("No gesture")
        except Exception:
            pass

    # ── Control handlers ──────────────────────────────────────────
    def _on_camera_change(self, cam_name: str):
        if self.detector.is_running:
            self._stop_detection()
        try:
            self.detector.camera_index = int(cam_name.split()[-1])
        except (ValueError, IndexError):
            self.detector.camera_index = 0

    def _on_cooldown_change(self, value):
        val = float(value)
        self.detector.cooldown_seconds = val
        self._cooldown_label.configure(text=f"{val:.1f}s")

    def _on_action_change(self, gesture_name: str, action: str):
        """Update the gesture→action mapping."""
        from core.gesture_detector import GESTURE_ACTIONS as GA
        try:
            g = Gesture[gesture_name]
            GA[g] = action
        except KeyError:
            pass
