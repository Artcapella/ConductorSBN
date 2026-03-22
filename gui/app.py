"""
ConductorSBN – Main GUI Application
Provides a sidebar to switch between views: Keywords, Soundboard,
Gestures, Voice FX, and Adaptive Mixer.
"""

import customtkinter as ctk
from pygame import mixer

from gui.keyword_view import KeywordView
from gui.soundboard_view import SoundboardView
from gui.gesture_view import GestureView
from gui.effects_view import EffectsView
from gui.adaptive_mixer_view import AdaptiveMixerView

from core.music_controller import create_music_controller, MusicBindingManager
from core.gesture_detector import GestureDetector, GestureEvent, HAS_MEDIAPIPE
from core.voice_effects import VoiceEffectsProcessor

# Adaptive mixer — optional, gracefully disabled if dependencies missing
try:
    from adaptive_mixer import (
        AdaptiveMixer, SceneManager,
        MixerGestureController, MixerKeyboardController,
    )
    _ADAPTIVE_MIXER_AVAILABLE = True
except ImportError as _e:
    print(f"[App] Adaptive mixer unavailable: {_e}")
    _ADAPTIVE_MIXER_AVAILABLE = False

CONFIG = "config/sound_config.yaml"


class ConductorApp(ctk.CTk):
    """Root application window with sidebar navigation."""

    _ACTIVE_COLOR = ("#3a7ebf", "#1f538d")
    _INACTIVE_COLOR = "transparent"

    def __init__(self):
        super().__init__()
        self.title("ConductorSBN")
        self.geometry("1150x700")
        self.minsize(920, 520)

        mixer.init()
        mixer.set_num_channels(32)

        # ── Shared subsystems ──────────────────────────────────────
        self.music_controller = create_music_controller()
        self.music_controller.load_library("music/")

        self.music_bindings = MusicBindingManager()

        self.effects_processor = VoiceEffectsProcessor()

        self.gesture_detector = GestureDetector(
            on_gesture=lambda e: self.after(0, lambda ev=e: self._handle_gesture(ev)),
            cooldown_seconds=1.0,
        ) if HAS_MEDIAPIPE else _NoOpDetector()

        # ── Adaptive Mixer ─────────────────────────────────────────
        self.adaptive_mixer = None
        self._mixer_gesture_ctrl = None
        self._mixer_keyboard_ctrl = None
        if _ADAPTIVE_MIXER_AVAILABLE:
            self._init_adaptive_mixer()

        # ── Layout ─────────────────────────────────────────────────
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

        self._current: str | None = None
        self._show_keywords()

        # Global hotkey binding — active on all views
        self.bind("<KeyPress>", self._sb_view._on_key, add="+")
        # Ctrl+key binding for adaptive mixer controls
        if self._mixer_keyboard_ctrl:
            self.bind("<Control-KeyPress>", self._on_mixer_ctrl_key, add="+")
            self.bind("<KeyPress>", self._on_mixer_function_key, add="+")

        # Start gesture status poller
        self.after(2000, self._update_gesture_status)

    # ── Sidebar ───────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=185, corner_radius=0,
                          fg_color=("gray88", "gray14"))
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(
            sb, text="ConductorSBN",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(26, 24))

        self._kw_btn = ctk.CTkButton(
            sb, text="\U0001F3B5  Keywords", width=155, height=38,
            anchor="w", command=self._show_keywords,
        )
        self._kw_btn.grid(row=1, column=0, padx=15, pady=4)

        self._sb_btn = ctk.CTkButton(
            sb, text="\U0001F3B9  Soundboard", width=155, height=38,
            anchor="w", command=self._show_soundboard,
        )
        self._sb_btn.grid(row=2, column=0, padx=15, pady=4)

        self._gesture_btn = ctk.CTkButton(
            sb, text="\U0001F44B  Gestures", width=155, height=38,
            anchor="w", command=self._show_gestures,
        )
        self._gesture_btn.grid(row=3, column=0, padx=15, pady=4)

        self._effects_btn = ctk.CTkButton(
            sb, text="\U0001F3A4  Voice FX", width=155, height=38,
            anchor="w", command=self._show_effects,
        )
        self._effects_btn.grid(row=4, column=0, padx=15, pady=4)

        self._mixer_btn = ctk.CTkButton(
            sb, text="\U0001F3BC  Adaptive Mixer", width=155, height=38,
            anchor="w", command=self._show_adaptive_mixer,
        )
        self._mixer_btn.grid(row=5, column=0, padx=15, pady=4)

        # Theme picker at bottom
        ctk.CTkLabel(sb, text="Theme:", font=ctk.CTkFont(size=11)).grid(
            row=7, column=0, padx=18, pady=(0, 2), sticky="w",
        )
        menu = ctk.CTkOptionMenu(
            sb, values=["Dark", "Light", "System"], width=145,
            command=lambda v: ctk.set_appearance_mode(v),
        )
        menu.set("Dark")
        menu.grid(row=8, column=0, padx=18, pady=(0, 20))

    # ── Content area ──────────────────────────────────────────────
    def _build_content(self):
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._kw_view = KeywordView(self._content, CONFIG)
        self._sb_view = SoundboardView(
            self._content, CONFIG,
            music_controller=self.music_controller,
            music_bindings=self.music_bindings,
        )
        self._gesture_view = GestureView(
            self._content,
            self.gesture_detector,
            dispatch_fn=self._handle_gesture_action,
        )
        self._effects_view = EffectsView(
            self._content,
            self.effects_processor,
        )

        # Adaptive Mixer view — always created; shows "unavailable" state if mixer is None
        self._mixer_view = AdaptiveMixerView(
            self._content,
            mixer=self.adaptive_mixer,
            scene_manager=getattr(self, "_mixer_scene_mgr", None) or _NoOpSceneManager(),
            music_controller=self.music_controller,
            music_bindings=self.music_bindings,
        )
        # Wire bidirectional gesture ↔ GUI sync
        if self._mixer_gesture_ctrl:
            self._mixer_gesture_ctrl.set_view(self._mixer_view)

        self._all_views = [
            self._kw_view, self._sb_view,
            self._gesture_view, self._effects_view, self._mixer_view,
        ]
        self._all_btns = [
            self._kw_btn, self._sb_btn,
            self._gesture_btn, self._effects_btn, self._mixer_btn,
        ]

    # ── Navigation ────────────────────────────────────────────────
    def _switch_to(self, view_id: str, view, btn):
        if self._current == view_id:
            return
        # Deactivate current view
        for v in self._all_views:
            try:
                v.deactivate()
            except Exception:
                pass
            v.grid_forget()
        # Activate new view
        self._current = view_id
        view.grid(row=0, column=0, sticky="nsew")
        try:
            view.activate()
        except Exception:
            pass
        # Update button highlights
        for b in self._all_btns:
            b.configure(fg_color=self._INACTIVE_COLOR)
        btn.configure(fg_color=self._ACTIVE_COLOR)

    def _show_keywords(self):
        self._kw_view.reload()
        self._switch_to("kw", self._kw_view, self._kw_btn)

    def _show_soundboard(self):
        self._switch_to("sb", self._sb_view, self._sb_btn)
        self._sb_view.activate()

    def _show_gestures(self):
        self._switch_to("gestures", self._gesture_view, self._gesture_btn)

    def _show_effects(self):
        self._switch_to("effects", self._effects_view, self._effects_btn)

    def _show_adaptive_mixer(self):
        self._switch_to("mixer", self._mixer_view, self._mixer_btn)

    # ── Adaptive Mixer init ───────────────────────────────────────
    def _init_adaptive_mixer(self):
        """Initialize the adaptive mixer subsystem."""
        try:
            import yaml as _yaml
            try:
                with open("config/mixer_config.yaml", "r") as _f:
                    _mcfg = _yaml.safe_load(_f)
                library_path = _mcfg.get("library_path", "assets/music/scenes")
            except Exception:
                library_path = "assets/music/scenes"

            self.adaptive_mixer = AdaptiveMixer(
                soundfont_path="assets/soundfonts/FluidR3_GM.sf2",
                leitmotif_config_path="assets/leitmotifs/leitmotifs.json",
            )
            self._mixer_scene_mgr = SceneManager(library_path)
            self._mixer_gesture_ctrl = MixerGestureController(self.adaptive_mixer)
            self._mixer_keyboard_ctrl = MixerKeyboardController(self.adaptive_mixer)
            self._mixer_keyboard_ctrl.set_available_scenes(
                self._mixer_scene_mgr.get_scene_paths()
            )
        except Exception as e:
            print(f"[App] Adaptive mixer init failed: {e}")
            self.adaptive_mixer = None
            self._mixer_scene_mgr = None
            self._mixer_gesture_ctrl = None
            self._mixer_keyboard_ctrl = None

    def _on_mixer_ctrl_key(self, event):
        """Handle Ctrl+key presses for adaptive mixer control."""
        if self._mixer_keyboard_ctrl:
            self._mixer_keyboard_ctrl.handle_ctrl_key(event.keysym)

    def _on_mixer_function_key(self, event):
        """Handle function key presses for scene loading."""
        if self._mixer_keyboard_ctrl and event.keysym.upper().startswith("F"):
            keysym = event.keysym.upper()
            if keysym[1:].isdigit():
                self._mixer_keyboard_ctrl.handle_function_key(event.keysym)

    # ── Gesture dispatcher ────────────────────────────────────────
    def _handle_gesture(self, event: GestureEvent):
        """Central gesture dispatcher — runs on main thread."""
        if self._mixer_gesture_ctrl:
            self._mixer_gesture_ctrl.process_gesture(
                event.gesture.name, event.confidence
            )
        if self.adaptive_mixer:
            self._handle_mixer_action(event.action)

    def _update_gesture_status(self):
        """Push gesture detector on/off state to the mixer view status bar."""
        if hasattr(self, "_mixer_view"):
            try:
                self._mixer_view.set_gesture_active(self.gesture_detector.is_running)
            except Exception:
                pass
        self.after(2000, self._update_gesture_status)

    def _handle_mixer_action(self, action: str):
        """Route a gesture action directly to the adaptive mixer."""
        am = self.adaptive_mixer
        if action == "cut_all":
            am.panic()
        elif action == "resume_all":
            if not am._running and am._scene_config:
                am.start()
            elif am._running and self._mixer_gesture_ctrl:
                # Restore stems after a panic by re-applying current intensity
                am.set_intensity(self._mixer_gesture_ctrl._current_intensity)
        elif action == "volume_up":
            am.set_master_volume(min(am._master_volume + 0.1, 1.0))
        elif action == "volume_down":
            am.set_master_volume(max(am._master_volume - 0.1, 0.0))
        elif action == "fade_in":
            am.set_master_volume(min(am._master_volume + 0.15, 1.0))
        elif action == "fade_out":
            am.set_master_volume(max(am._master_volume - 0.15, 0.0))

    def _handle_gesture_action(self, action: str):
        """Preview a gesture action — used by GestureView for testing only."""
        if action == "cut_all":
            mixer.stop()

    # ── Voice command dispatcher (called from soundboard_view) ────
    def handle_music_voice_command(self, action: str):
        """Route a voice command to the music controller."""
        mc = self.music_controller
        if action == "resume":
            mc.resume()
        elif action == "pause":
            mc.pause()
        elif action == "stop":
            mc.stop()
        elif action == "next":
            mc.play_next()
        elif action == "previous":
            mc.play_previous()
        elif action == "fade_in":
            mc.fade_in()
        elif action == "fade_out":
            mc.fade_out()

    def handle_effect_voice_command(self, preset_name: str):
        """Switch voice effect preset by name."""
        from core.voice_effects import EffectPreset
        try:
            preset = EffectPreset[preset_name.upper()]
            self.effects_processor.set_preset(preset)
        except KeyError:
            pass

    def destroy(self):
        """Clean up all subsystems on exit."""
        if self.adaptive_mixer:
            try:
                self.adaptive_mixer.cleanup()
            except Exception:
                pass
        super().destroy()


class _NoOpSceneManager:
    """Placeholder when adaptive mixer is unavailable."""
    def scan(self): pass
    def get_scene_list(self): return []
    def get_scene_paths(self): return []


class _NoOpDetector:
    """Placeholder when MediaPipe is unavailable."""
    is_running = False
    camera_index = 0
    cooldown_seconds = 1.0
    frame_callback = None

    def start(self): pass
    def stop(self): pass


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ConductorApp()
    app.mainloop()
