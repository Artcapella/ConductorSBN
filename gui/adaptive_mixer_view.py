"""
ConductorSBN – Adaptive Mixer View

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │ Scene: [Enchanted Forest Theme ▼]  ⏵ Play  ⏹ Stop       │
  │ 📁 ./music_library/               [Browse]  [Rescan]     │
  ├──────────────────────────────────────────────────────────┤
  │  other   ████████████████████░░░░  0.85  [M]             │
  │  bass    ██████████░░░░░░░░░░░░░  0.40  [M]             │
  │  drums   ░░░░░░░░░░░░░░░░░░░░░░░  0.00  [M]             │
  │  vocals  ██████░░░░░░░░░░░░░░░░░  0.25  [M]             │
  ├──────────────────────────────────────────────────────────┤
  │ Intensity: [====●==========]  1 / 3                      │
  │ Master:    [===========●===]  0.80                       │
  ├──────────────────────────────────────────────────────────┤
  │ Leitmotifs: [Aria] [Grimjaw] [Mystery]        [Stop]     │
  │ BPM: 90  Key: Dm  Bar 1 | Beat 2  Gesture: ● ON  [Panic]│
  └──────────────────────────────────────────────────────────┘
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import yaml


MIXER_CONFIG_PATH = "config/mixer_config.yaml"
DEFAULT_LIBRARY_PATH = "assets/music/scenes"


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _load_library_path() -> str:
    try:
        with open(MIXER_CONFIG_PATH, "r") as f:
            return yaml.safe_load(f).get("library_path", DEFAULT_LIBRARY_PATH)
    except Exception:
        return DEFAULT_LIBRARY_PATH


def _save_library_path(path: str):
    try:
        with open(MIXER_CONFIG_PATH, "w") as f:
            yaml.dump({"library_path": path}, f, default_flow_style=False)
    except Exception as e:
        print(f"[MixerView] Could not save library path: {e}")


class AdaptiveMixerView(ctk.CTkFrame):
    """Full-featured GUI panel for the adaptive music mixing system."""

    POLL_MS = 100  # Slider/status refresh rate

    def __init__(self, parent, mixer, scene_manager,
                 music_controller=None, music_bindings=None):
        super().__init__(parent, fg_color="transparent")
        self._mixer = mixer
        self._scene_mgr = scene_manager
        self._mc = music_controller
        self._bm = music_bindings

        # Per-stem widget references
        self._stem_sliders: dict = {}   # stem_id -> CTkSlider
        self._stem_vol_labels: dict = {}
        self._stem_mute_btns: dict = {}

        # Scene list: display-string -> scene path
        self._scene_map: dict = {}

        # Bidirectional sync: suppress slider→mixer callbacks during programmatic updates
        self._updating_sliders = False
        # Which source last changed a stem volume: "user" | "gesture" | None
        self._last_control_source: str | None = None
        # Per-stem source tracking so only gesture-changed stems get synced
        self._stem_last_source: dict = {}  # stem_id -> "user"|"gesture"|None

        self._poll_job = None
        self._loading = False  # True while a scene is loading in background

        self._build_ui()

    # ── Public API (called from gesture controller) ───────────────

    def on_gesture_changed(self):
        """
        Called by MixerGestureController after it changes intensity.
        Marks all stems as gesture-controlled so the poll loop syncs sliders.
        """
        for stem_id in self._stem_sliders:
            self._stem_last_source[stem_id] = "gesture"

    # ── Lifecycle ─────────────────────────────────────────────────

    def activate(self):
        self._rescan_and_refresh()
        self._refresh_stems()
        self._refresh_leitmotifs()
        self._refresh_music_library()
        self._poll_job = self.after(self.POLL_MS, self._poll)

    def deactivate(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    # ── Layout ────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Stems panel expands

        self._build_scene_bar()      # row 0
        self._build_library_bar()    # row 1
        self._build_stems_panel()    # row 2
        self._build_controls_bar()   # row 3
        self._build_leitmotif_bar()  # row 4
        self._build_status_bar()     # row 5
        self._build_music_section()  # row 6

    def _build_scene_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 3))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            bar, text="Scene:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 6), pady=10)

        self._scene_var = tk.StringVar(value="— no scenes found —")
        self._scene_dropdown = ctk.CTkComboBox(
            bar,
            variable=self._scene_var,
            values=[],
            state="readonly",
            width=320,
            command=self._on_scene_dropdown,
        )
        self._scene_dropdown.grid(row=0, column=1, padx=6, pady=10, sticky="w")

        # Scene metadata label (BPM, key, stems)
        self._scene_meta_var = tk.StringVar(value="")
        ctk.CTkLabel(
            bar, textvariable=self._scene_meta_var,
            font=ctk.CTkFont(size=10), text_color="gray50",
        ).grid(row=0, column=2, padx=8)

        btn_frame = ctk.CTkFrame(bar, fg_color="transparent")
        btn_frame.grid(row=0, column=3, padx=(0, 14), pady=10)

        self._play_btn = ctk.CTkButton(
            btn_frame, text="⏵  Play", width=80, height=30,
            fg_color=("#2e7d32", "#1b5e20"), hover_color=("#1b5e20", "#0a3a00"),
            command=self._play,
        )
        self._play_btn.pack(side="left", padx=3)

        self._stop_btn = ctk.CTkButton(
            btn_frame, text="⏹  Stop", width=80, height=30,
            fg_color=("gray35", "gray25"), hover_color=("gray25", "gray15"),
            command=self._stop,
        )
        self._stop_btn.pack(side="left", padx=3)

        # Timeline row (row 1 of the scene bar frame)
        tl = ctk.CTkFrame(bar, fg_color="transparent")
        tl.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 10))
        tl.grid_columnconfigure(1, weight=1)

        self._timeline_pos_var = tk.StringVar(value="0:00")
        ctk.CTkLabel(
            tl, textvariable=self._timeline_pos_var,
            font=ctk.CTkFont(size=10, family="Courier"),
            width=36, anchor="e", text_color="gray55",
        ).grid(row=0, column=0, padx=(0, 6))

        self._timeline_slider = ctk.CTkSlider(
            tl, from_=0.0, to=1.0, height=16,
            command=self._on_timeline_seek,
        )
        self._timeline_slider.set(0.0)
        self._timeline_slider.grid(row=0, column=1, sticky="ew")

        self._timeline_dur_var = tk.StringVar(value="0:00")
        ctk.CTkLabel(
            tl, textvariable=self._timeline_dur_var,
            font=ctk.CTkFont(size=10, family="Courier"),
            width=36, anchor="w", text_color="gray55",
        ).grid(row=0, column=2, padx=(6, 0))

    def _build_library_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray90", "gray17"))
        bar.grid(row=1, column=0, sticky="ew", padx=8, pady=3)
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            bar, text="Library:",
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).grid(row=0, column=0, padx=(14, 6), pady=7)

        self._lib_path_var = tk.StringVar(value=_load_library_path())
        ctk.CTkLabel(
            bar, textvariable=self._lib_path_var,
            font=ctk.CTkFont(size=11), text_color="gray55", anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=7)

        ctk.CTkButton(
            bar, text="Browse", width=70, height=26,
            command=self._browse_library,
        ).grid(row=0, column=2, padx=4, pady=7)

        ctk.CTkButton(
            bar, text="Rescan", width=70, height=26,
            command=self._rescan_and_refresh,
        ).grid(row=0, column=3, padx=(0, 14), pady=7)

    def _build_stems_panel(self):
        outer = ctk.CTkFrame(self, corner_radius=10)
        outer.grid(row=2, column=0, sticky="nsew", padx=8, pady=3)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text="Stems",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            hdr, text="Ctrl+1–9 to mute/unmute",
            font=ctk.CTkFont(size=10), text_color="gray50",
        ).grid(row=0, column=1, sticky="e")

        self._stem_scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self._stem_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 8))
        self._stem_scroll.grid_columnconfigure(1, weight=1)

    def _build_controls_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.grid(row=3, column=0, sticky="ew", padx=8, pady=3)
        bar.grid_columnconfigure(2, weight=1)
        bar.grid_columnconfigure(5, weight=1)

        # Intensity
        ctk.CTkLabel(
            bar, text="Intensity:",
            font=ctk.CTkFont(size=12, weight="bold"), width=68,
        ).grid(row=0, column=0, padx=(14, 4), pady=12, sticky="w")

        self._intensity_var = tk.IntVar(value=0)
        self._intensity_slider = ctk.CTkSlider(
            bar, from_=0, to=3, number_of_steps=3,
            variable=self._intensity_var,
            command=self._on_intensity_slider,
            width=200,
        )
        self._intensity_slider.grid(row=0, column=1, padx=6, pady=12)

        self._intensity_label = ctk.CTkLabel(
            bar, text="0 / 3  (base)",
            font=ctk.CTkFont(size=11), width=90,
        )
        self._intensity_label.grid(row=0, column=2, padx=4)

        # Separator
        ctk.CTkLabel(bar, text="", width=20).grid(row=0, column=3)

        # Master volume
        ctk.CTkLabel(
            bar, text="Master:",
            font=ctk.CTkFont(size=12, weight="bold"), width=58,
        ).grid(row=0, column=4, padx=(8, 4), pady=12, sticky="w")

        self._master_slider = ctk.CTkSlider(
            bar, from_=0.0, to=1.0,
            command=self._on_master_slider,
            width=200,
        )
        self._master_slider.set(
            self._mixer._master_volume if self._mixer else 0.8
        )
        self._master_slider.grid(row=0, column=5, padx=6, pady=12)

        self._master_label = ctk.CTkLabel(
            bar, text=f"{int((self._mixer._master_volume if self._mixer else 0.8) * 100)}%",
            font=ctk.CTkFont(size=11), width=38,
        )
        self._master_label.grid(row=0, column=6, padx=(4, 14))

    def _build_leitmotif_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.grid(row=4, column=0, sticky="ew", padx=8, pady=3)
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            bar, text="Leitmotifs:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=(14, 8), pady=10)

        self._leitmotif_btn_frame = ctk.CTkFrame(bar, fg_color="transparent")
        self._leitmotif_btn_frame.grid(row=0, column=1, sticky="w", pady=10)

        ctk.CTkButton(
            bar, text="Stop", width=60, height=28,
            fg_color="#c62828", hover_color="#b71c1c",
            command=self._stop_leitmotif,
        ).grid(row=0, column=2, padx=(0, 14), pady=10)

    def _build_status_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray90", "gray17"))
        bar.grid(row=5, column=0, sticky="ew", padx=8, pady=(3, 8))
        bar.grid_columnconfigure(4, weight=1)

        self._bpm_var = tk.StringVar(value="BPM: —")
        ctk.CTkLabel(
            bar, textvariable=self._bpm_var,
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).grid(row=0, column=0, padx=(14, 8), pady=8)

        self._key_var = tk.StringVar(value="Key: —")
        ctk.CTkLabel(
            bar, textvariable=self._key_var,
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).grid(row=0, column=1, padx=8, pady=8)

        self._beat_var = tk.StringVar(value="Bar — | Beat —")
        ctk.CTkLabel(
            bar, textvariable=self._beat_var,
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).grid(row=0, column=2, padx=8, pady=8)

        self._gesture_var = tk.StringVar(value="Gesture: ○ OFF")
        self._gesture_lbl = ctk.CTkLabel(
            bar, textvariable=self._gesture_var,
            font=ctk.CTkFont(size=11), text_color="gray55",
        )
        self._gesture_lbl.grid(row=0, column=3, padx=8, pady=8)

        ctk.CTkButton(
            bar, text="⚠ Panic", width=80, height=26,
            fg_color="#c62828", hover_color="#b71c1c",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._panic,
        ).grid(row=0, column=5, padx=(0, 14), pady=8, sticky="e")

    # ── Scene population ──────────────────────────────────────────

    def _rescan_and_refresh(self):
        path = self._lib_path_var.get() if hasattr(self, "_lib_path_var") else _load_library_path()
        self._scene_mgr._scenes_dir = Path(path)
        self._scene_mgr.scan()
        self._populate_scene_dropdown()

    def _populate_scene_dropdown(self):
        self._scene_map.clear()
        scenes = self._scene_mgr.get_scene_list()

        if not scenes:
            self._scene_dropdown.configure(values=["— no scenes found —"])
            self._scene_var.set("— no scenes found —")
            self._scene_meta_var.set("")
            return

        display_values = []
        for scene in scenes:
            cfg = self._scene_mgr._scenes.get(scene["id"], {}).get("config", {})
            bpm = cfg.get("bpm", "?")
            key = cfg.get("key", "?")
            n_stems = len(cfg.get("stems", {}))
            display = f"{scene['name']}  —  {bpm} BPM  {key}  ({n_stems} stems)"
            self._scene_map[display] = scene["path"]
            display_values.append(display)

        self._scene_dropdown.configure(values=display_values)

        # Highlight current scene if loaded
        current_name = self._mixer.get_current_scene_name() if self._mixer else None
        if current_name and current_name != "No scene loaded":
            for disp in display_values:
                if disp.startswith(current_name):
                    self._scene_var.set(disp)
                    self._update_scene_meta(disp)
                    return
        self._scene_var.set(display_values[0])
        self._update_scene_meta(display_values[0])

    def _update_scene_meta(self, display: str):
        # The metadata is already embedded in the display string after "  —  "
        parts = display.split("  —  ", 1)
        self._scene_meta_var.set(parts[1] if len(parts) > 1 else "")

    # ── Stem population ───────────────────────────────────────────

    def _refresh_stems(self):
        for w in self._stem_scroll.winfo_children():
            w.destroy()
        self._stem_sliders.clear()
        self._stem_vol_labels.clear()
        self._stem_mute_btns.clear()
        self._stem_last_source.clear()

        if not self._mixer:
            ctk.CTkLabel(
                self._stem_scroll,
                text="Adaptive mixer not available.\nInstall soundfile and numpy.",
                font=ctk.CTkFont(size=12), text_color="gray50", justify="center",
            ).grid(row=0, column=0, columnspan=4, pady=30)
            return

        stems = self._mixer.get_stem_names()
        if not stems:
            ctk.CTkLabel(
                self._stem_scroll,
                text="No stems loaded — select a scene above and press Play.",
                font=ctk.CTkFont(size=12), text_color="gray50",
            ).grid(row=0, column=0, columnspan=4, pady=30)
            return

        scene_cfg = self._mixer._scene_config or {}

        for idx, stem_id in enumerate(stems):
            stem_cfg = scene_cfg.get("stems", {}).get(stem_id, {})
            default_vol = stem_cfg.get("default_volume", 0.5)
            stem_obj = self._mixer._stems.get(stem_id)
            target_vol = stem_obj._target_volume if stem_obj else default_vol
            is_muted = stem_obj._muted if stem_obj else True

            # Row: [name 10ch] [slider fills] [vol% 5ch] [M btn]
            row = ctk.CTkFrame(self._stem_scroll, fg_color="transparent")
            row.grid(row=idx, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(1, weight=1)

            # Name — left-aligned, fixed width
            ctk.CTkLabel(
                row,
                text=stem_id,
                font=ctk.CTkFont(size=12),
                width=90, anchor="e",
                text_color="gray70",
            ).grid(row=0, column=0, padx=(6, 8))

            # Slider (acts as the fill bar — CTkSlider shows a filled track)
            slider = ctk.CTkSlider(
                row,
                from_=0.0, to=1.0,
                command=lambda v, sid=stem_id: self._on_stem_slider(sid, float(v)),
            )
            slider.set(target_vol)
            slider.grid(row=0, column=1, sticky="ew", padx=4)

            # Volume % label
            vol_lbl = ctk.CTkLabel(
                row,
                text=f"{int(target_vol * 100):3d}%",
                font=ctk.CTkFont(size=11, family="Courier"),
                width=40, anchor="e",
            )
            vol_lbl.grid(row=0, column=2, padx=4)

            # Mute button [M]
            mute_btn = ctk.CTkButton(
                row,
                text="M",
                width=30, height=28,
                fg_color="gray35" if is_muted else ("#1565c0", "#0d47a1"),
                hover_color="gray25" if is_muted else ("#0d47a1", "#01579b"),
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda sid=stem_id: self._toggle_mute(sid),
            )
            mute_btn.grid(row=0, column=3, padx=(4, 8))

            self._stem_sliders[stem_id] = slider
            self._stem_vol_labels[stem_id] = vol_lbl
            self._stem_mute_btns[stem_id] = mute_btn
            self._stem_last_source[stem_id] = None

    # ── Leitmotif population ──────────────────────────────────────

    def _refresh_leitmotifs(self):
        for w in self._leitmotif_btn_frame.winfo_children():
            w.destroy()

        if not self._mixer:
            return

        leitmotifs = self._mixer.get_leitmotif_names()
        if not leitmotifs:
            ctk.CTkLabel(
                self._leitmotif_btn_frame,
                text="None loaded — add FluidR3_GM.sf2 and install pyfluidsynth",
                font=ctk.CTkFont(size=10), text_color="gray50",
            ).pack(side="left")
            return

        for lm_id in leitmotifs:
            lm_name = lm_id.replace("_", " ").title()
            if self._mixer._midi_gen:
                lm_obj = self._mixer._midi_gen._leitmotifs.get(lm_id)
                if lm_obj:
                    lm_name = lm_obj.name

            ctk.CTkButton(
                self._leitmotif_btn_frame,
                text=lm_name,
                height=28, width=max(80, len(lm_name) * 8),
                command=lambda lid=lm_id: self._mixer.trigger_leitmotif(lid),
            ).pack(side="left", padx=3)

    # ── User actions ──────────────────────────────────────────────

    def _on_scene_dropdown(self, display: str):
        path = self._scene_map.get(display)
        if path:
            self._update_scene_meta(display)
            self._load_scene(path)

    def _browse_library(self):
        folder = filedialog.askdirectory(
            title="Select Music Library Folder",
            initialdir=self._lib_path_var.get(),
        )
        if folder:
            self._lib_path_var.set(folder)
            _save_library_path(folder)
            self._rescan_and_refresh()

    def _play(self):
        if not self._mixer:
            return
        if not self._mixer._running:
            self._mixer.start()
        # If a scene is selected but not loaded, load it first
        display = self._scene_var.get()
        path = self._scene_map.get(display)
        if path and not self._mixer._scene_config:
            self._load_scene(path)

    def _stop(self):
        if self._mixer:
            self._mixer.stop()

    def _load_scene(self, scene_path: str):
        if not self._mixer or self._loading:
            return
        self._loading = True
        self._play_btn.configure(state="disabled", text="Loading…")
        t = threading.Thread(
            target=self._load_scene_bg, args=(scene_path,), daemon=True
        )
        t.start()

    def _load_scene_bg(self, scene_path: str):
        try:
            self._mixer.load_scene(scene_path)
            if not self._mixer._running:
                self._mixer.start()
        except Exception as e:
            print(f"[MixerView] Failed to load scene: {e}")
        self.after(0, self._on_scene_loaded)

    def _on_scene_loaded(self):
        self._loading = False
        self._play_btn.configure(state="normal", text="⏵  Play")
        self._populate_scene_dropdown()
        self._refresh_stems()
        self._refresh_leitmotifs()
        self._sync_bpm_key()

    def _on_stem_slider(self, stem_id: str, value: float):
        if self._updating_sliders:
            return
        self._stem_last_source[stem_id] = "user"
        if self._mixer:
            self._mixer.set_stem_volume(stem_id, value, fade_seconds=0.05)
        lbl = self._stem_vol_labels.get(stem_id)
        if lbl:
            lbl.configure(text=f"{int(value * 100):3d}%")

    def _toggle_mute(self, stem_id: str):
        if not self._mixer:
            return
        self._stem_last_source[stem_id] = "user"
        self._mixer.toggle_stem(stem_id)

    def _on_timeline_seek(self, value: float):
        if self._updating_sliders or not self._mixer:
            return
        _, total = self._mixer.get_playback_position()
        if total > 0:
            self._mixer.seek(float(value) * total)

    def _on_intensity_slider(self, value):
        level = int(round(float(value)))
        self._intensity_var.set(level)
        labels = ["base", "peaceful", "tension", "combat"]
        self._intensity_label.configure(
            text=f"{level} / 3  ({labels[min(level, 3)]})"
        )
        if self._mixer:
            self._mixer.set_intensity(level)
        # Mark all stems as user-controlled so poll doesn't fight the slider
        for stem_id in self._stem_sliders:
            self._stem_last_source[stem_id] = "user"
        # Allow re-sync after 1s
        self.after(1000, self._clear_user_source)

    def _clear_user_source(self):
        for stem_id in self._stem_last_source:
            if self._stem_last_source[stem_id] == "user":
                self._stem_last_source[stem_id] = None

    def _on_master_slider(self, value: float):
        if self._mixer:
            self._mixer.set_master_volume(float(value))
        self._master_label.configure(text=f"{int(float(value) * 100)}%")

    def _stop_leitmotif(self):
        if self._mixer:
            self._mixer.stop_leitmotif()

    def _panic(self):
        if self._mixer:
            self._mixer.panic()
        # Reset intensity indicator
        self._intensity_var.set(0)
        self._intensity_label.configure(text="0 / 3  (base)")

    # ── Periodic poll ─────────────────────────────────────────────

    def _poll(self):
        self._sync_stem_meters()
        self._sync_master_slider()
        self._sync_timeline()
        self._sync_status_bar()
        self._update_music_now_playing()
        self._poll_job = self.after(self.POLL_MS, self._poll)

    def _sync_stem_meters(self):
        if not self._mixer:
            return
        status = self._mixer.get_stem_status()

        self._updating_sliders = True
        try:
            for stem_id, info in status.items():
                target = info["target_volume"]
                is_muted = info["muted"]
                is_audible = info["is_audible"]

                # Update slider only if this stem was last changed by gesture/external source
                source = self._stem_last_source.get(stem_id)
                slider = self._stem_sliders.get(stem_id)
                if slider and source != "user":
                    if abs(slider.get() - target) > 0.02:
                        slider.set(target)

                # Always update the volume label (reflects live audio level, not just target)
                live_vol = info["volume"]
                lbl = self._stem_vol_labels.get(stem_id)
                if lbl:
                    lbl.configure(text=f"{int(live_vol * 100):3d}%")

                # Update mute button appearance
                btn = self._stem_mute_btns.get(stem_id)
                if btn:
                    if is_muted or not is_audible:
                        btn.configure(
                            fg_color="gray35",
                            hover_color="gray25",
                        )
                    else:
                        btn.configure(
                            fg_color=("#1565c0", "#0d47a1"),
                            hover_color=("#0d47a1", "#01579b"),
                        )

                # Clear gesture source flag once slider has caught up
                if source == "gesture" and slider and abs(slider.get() - target) < 0.02:
                    self._stem_last_source[stem_id] = None
        finally:
            self._updating_sliders = False

    def _sync_timeline(self):
        if not self._mixer or not hasattr(self, "_timeline_slider"):
            return
        current, total = self._mixer.get_playback_position()
        if total <= 0:
            return
        self._timeline_pos_var.set(_fmt_time(current))
        self._timeline_dur_var.set(_fmt_time(total))
        self._updating_sliders = True
        try:
            self._timeline_slider.set(current / total)
        finally:
            self._updating_sliders = False

    def _sync_master_slider(self):
        if not self._mixer:
            return
        current = self._mixer._master_volume
        if abs(self._master_slider.get() - current) > 0.01:
            self._updating_sliders = True
            self._master_slider.set(current)
            self._updating_sliders = False
        self._master_label.configure(text=f"{int(current * 100)}%")

    def _sync_status_bar(self):
        if not self._mixer:
            return

        # Play/stop button state
        if self._mixer._running and not self._loading:
            self._play_btn.configure(
                fg_color=("#2e7d32", "#1b5e20"),
                text="⏵  Play",
            )
            self._stop_btn.configure(fg_color=("#7b1fa2", "#4a0072"))
        elif not self._loading:
            self._play_btn.configure(
                fg_color=("gray35", "gray25"),
                text="⏵  Play",
            )
            self._stop_btn.configure(fg_color=("gray35", "gray25"))

        # Beat clock
        if self._mixer._running:
            bar, beat, _ = self._mixer.clock.get_position()
            self._beat_var.set(f"Bar {bar + 1} | Beat {beat + 1}")

    def _sync_bpm_key(self):
        if not self._mixer or not self._mixer._scene_config:
            self._bpm_var.set("BPM: —")
            self._key_var.set("Key: —")
            return
        cfg = self._mixer._scene_config
        self._bpm_var.set(f"BPM: {cfg.get('bpm', '?')}")
        self._key_var.set(f"Key: {cfg.get('key', '?')}")

    def set_gesture_active(self, active: bool):
        """Called from app to reflect whether gesture detector is running."""
        if active:
            self._gesture_var.set("Gesture: ● ON")
            self._gesture_lbl.configure(text_color=("#2e7d32", "#4caf50"))
        else:
            self._gesture_var.set("Gesture: ○ OFF")
            self._gesture_lbl.configure(text_color="gray50")

    # ── Background Music section ───────────────────────────────────

    def _build_music_section(self):
        """Embeds the background music player below the status bar."""
        if not self._mc:
            return

        outer = ctk.CTkFrame(self, corner_radius=10)
        outer.grid(row=6, column=0, sticky="nsew", padx=8, pady=(3, 8))
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        # Header row: title + folder path + change folder button
        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="Background Music",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self._music_folder_var = tk.StringVar(value="music/")
        ctk.CTkLabel(
            hdr, textvariable=self._music_folder_var,
            font=ctk.CTkFont(size=10), text_color="gray60", anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=8)

        ctk.CTkButton(
            hdr, text="📁 Change Folder", width=130, height=28,
            command=self._music_choose_folder,
        ).grid(row=0, column=2)

        # Now-playing + transport row
        np_row = ctk.CTkFrame(outer, fg_color="transparent")
        np_row.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        np_row.grid_columnconfigure(0, weight=1)

        self._music_now_playing_var = tk.StringVar(value="— nothing playing —")
        ctk.CTkLabel(
            np_row, textvariable=self._music_now_playing_var,
            font=ctk.CTkFont(size=12), anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        self._music_state_var = tk.StringVar(value="Stopped")
        ctk.CTkLabel(
            np_row, textvariable=self._music_state_var,
            font=ctk.CTkFont(size=10), text_color="gray60",
        ).grid(row=0, column=1, padx=8)

        transport = ctk.CTkFrame(np_row, fg_color="transparent")
        transport.grid(row=0, column=2)
        ctk.CTkButton(transport, text="⏮", width=32, height=28,
                      command=self._music_prev).pack(side="left", padx=2)
        self._music_play_btn = ctk.CTkButton(
            transport, text="▶", width=32, height=28,
            command=self._music_play_pause)
        self._music_play_btn.pack(side="left", padx=2)
        ctk.CTkButton(transport, text="⏹", width=32, height=28,
                      command=self._music_stop).pack(side="left", padx=2)
        ctk.CTkButton(transport, text="⏭", width=32, height=28,
                      command=self._music_next).pack(side="left", padx=2)

        # Volume row
        vol_row = ctk.CTkFrame(outer, fg_color="transparent")
        vol_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 4))
        vol_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(vol_row, text="Volume:", font=ctk.CTkFont(size=11),
                     ).grid(row=0, column=0, padx=(0, 8))
        self._music_vol_slider = ctk.CTkSlider(
            vol_row, from_=0.0, to=1.0,
            command=self._on_music_volume,
        )
        self._music_vol_slider.set(self._mc.get_volume())
        self._music_vol_slider.grid(row=0, column=1, sticky="ew", padx=4)
        self._music_vol_label = ctk.CTkLabel(
            vol_row, text=f"{int(self._mc.get_volume() * 100)}%",
            font=ctk.CTkFont(size=11), width=38,
        )
        self._music_vol_label.grid(row=0, column=2, padx=4)

        # Track list
        self._music_track_list = ctk.CTkScrollableFrame(outer, height=130)
        self._music_track_list.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._music_track_list.grid_columnconfigure(0, weight=1)

    def _refresh_music_library(self):
        if not self._mc or not hasattr(self, "_music_track_list"):
            return
        for w in self._music_track_list.winfo_children():
            w.destroy()

        library = self._mc.library
        bindings = self._bm.get_all() if self._bm else {}
        key_for_idx = {v: k for k, v in bindings.items()}

        if not library:
            ctk.CTkLabel(
                self._music_track_list,
                text="No tracks found. Add music files to the folder above.",
                font=ctk.CTkFont(size=11), text_color="gray60",
            ).grid(row=0, column=0, pady=12)
            return

        for idx, track in enumerate(library):
            row = ctk.CTkFrame(self._music_track_list, corner_radius=4, height=34)
            row.grid(row=idx, column=0, sticky="ew", padx=2, pady=1)
            row.grid_propagate(False)
            row.grid_columnconfigure(1, weight=1)

            key_label = key_for_idx.get(idx, "")
            ctk.CTkLabel(
                row,
                text=key_label.upper() if key_label else "—",
                font=ctk.CTkFont(size=11, weight="bold"),
                width=26, text_color=("gray30", "gray70"),
            ).grid(row=0, column=0, padx=(6, 3), pady=3)

            ctk.CTkLabel(
                row, text=track.name, anchor="w",
                font=ctk.CTkFont(size=11),
            ).grid(row=0, column=1, sticky="ew", padx=3)

            ctk.CTkButton(
                row, text="▶", width=26, height=24,
                command=lambda t=track: self._mc.play(t),
            ).grid(row=0, column=2, padx=3, pady=3)

            ctk.CTkButton(
                row, text="⌨", width=26, height=24,
                command=lambda i=idx: self._open_music_bind_dialog(i),
            ).grid(row=0, column=3, padx=(0, 6), pady=3)

    def _music_choose_folder(self):
        folder = filedialog.askdirectory(title="Select Music Folder")
        if folder and self._mc:
            self._music_folder_var.set(folder)
            self._mc.load_library(folder)
            self._refresh_music_library()

    def _music_play_pause(self):
        if not self._mc:
            return
        from core.music_controller import PlaybackState
        state = self._mc.get_state()
        if state == PlaybackState.PLAYING:
            self._mc.pause()
        elif state == PlaybackState.PAUSED:
            self._mc.resume()
        else:
            self._mc.resume()

    def _music_stop(self):
        if self._mc:
            self._mc.stop()

    def _music_next(self):
        if self._mc:
            self._mc.play_next()

    def _music_prev(self):
        if self._mc:
            self._mc.play_previous()

    def _on_music_volume(self, value: float):
        if self._mc:
            self._mc.set_volume(float(value))
        if hasattr(self, "_music_vol_label"):
            self._music_vol_label.configure(text=f"{int(float(value) * 100)}%")

    def _open_music_bind_dialog(self, track_idx: int):
        if not self._mc or not self._bm:
            return
        dlg = _MusicBindKeyDialog(self, track_idx, self._mc.library[track_idx].name)
        self.wait_window(dlg)
        if dlg.result is not None:
            key, idx = dlg.result
            if key:
                self._bm.bind(key, idx)
            self._refresh_music_library()

    def _update_music_now_playing(self):
        if not self._mc or not hasattr(self, "_music_now_playing_var"):
            return
        from core.music_controller import PlaybackState
        track = self._mc.get_current_track()
        state = self._mc.get_state()
        self._music_now_playing_var.set(track.name if track else "— nothing playing —")
        state_map = {
            PlaybackState.PLAYING: ("Playing", "#4caf50"),
            PlaybackState.PAUSED: ("Paused", "orange"),
            PlaybackState.STOPPED: ("Stopped", "gray60"),
            PlaybackState.FADING_IN: ("Fading In", "#4caf50"),
            PlaybackState.FADING_OUT: ("Fading Out", "orange"),
        }
        label, _ = state_map.get(state, ("Unknown", "gray60"))
        self._music_state_var.set(label)
        if hasattr(self, "_music_play_btn"):
            self._music_play_btn.configure(
                text="⏸" if state == PlaybackState.PLAYING else "▶"
            )


class _MusicBindKeyDialog(ctk.CTkToplevel):
    """Capture a key to bind to a background music track."""

    def __init__(self, parent, track_idx: int, track_name: str):
        super().__init__(parent)
        self.title("Bind Key to Track")
        self.geometry("360x220")
        self.resizable(False, False)
        self.result = None
        self.track_idx = track_idx

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.focus_set()

        ctk.CTkLabel(
            self, text=f"Binding: {track_name}",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=20, pady=(20, 4))

        ctk.CTkLabel(
            self, text="Press a number key (0-9) to assign it:",
            font=ctk.CTkFont(size=12),
        ).pack(padx=20, pady=(0, 8))

        self._key_lbl = ctk.CTkLabel(
            self, text="[ press a key ]",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self._key_lbl.pack(pady=(0, 16))
        self.bind("<KeyPress>", self._capture)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack()
        ctk.CTkButton(btns, text="Confirm", width=120,
                      command=self._confirm).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Unbind", width=120,
                      fg_color="#c62828", hover_color="#b71c1c",
                      command=self._unbind).pack(side="left", padx=8)

        self._captured = None

    def _capture(self, event):
        import tkinter as _tk
        if isinstance(event.widget, _tk.Entry):
            return
        key = event.keysym.lower()
        if key.isdigit() or key.isalpha():
            self._captured = key
            self._key_lbl.configure(text=key.upper())

    def _confirm(self):
        if self._captured:
            self.result = (self._captured, self.track_idx)
        self.destroy()

    def _unbind(self):
        self.result = ("", self.track_idx)
        self.destroy()
