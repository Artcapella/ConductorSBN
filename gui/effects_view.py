"""
ConductorSBN – Voice Effects View
Preset selector, dry/wet control, and audio device configuration.
"""

import tkinter as tk

import customtkinter as ctk

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

from core.voice_effects import EffectPreset, HAS_PEDALBOARD, HAS_SD as FX_HAS_SD


PRESET_DESCRIPTIONS = {
    EffectPreset.NONE:       ("No Effect",   "gray60",   "Original voice, pass-through"),
    EffectPreset.TUNNEL:     ("Tunnel",       "#78909c",  "Stone corridor echo"),
    EffectPreset.CATHEDRAL:  ("Cathedral",    "#7e57c2",  "Vast reverberant space"),
    EffectPreset.CHOIR:      ("Choir",        "#26a69a",  "Harmonic choir voices"),
    EffectPreset.DEMON:      ("Demon",        "#ef5350",  "Deep demonic pitch shift"),
    EffectPreset.WHISPER:    ("Whisper",      "#9e9e9e",  "Filtered, eerie whisper"),
    EffectPreset.UNDERWATER: ("Underwater",   "#29b6f6",  "Muffled aquatic distortion"),
}


class EffectsView(ctk.CTkFrame):
    """Real-time voice effects control panel."""

    def __init__(self, parent, effects_processor):
        super().__init__(parent, fg_color="transparent")
        self.fx = effects_processor
        self._meter_job = None
        self._preset_btns: dict[EffectPreset, ctk.CTkButton] = {}
        self._build_ui()

    def activate(self):
        self._schedule_meters()

    def deactivate(self):
        if self._meter_job:
            self.after_cancel(self._meter_job)
            self._meter_job = None

    # ── Layout ────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_main_area()
        self._build_device_panel()

    def _build_top_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        bar.grid_columnconfigure(1, weight=1)

        # Enable toggle
        self._enabled_var = tk.BooleanVar(value=False)
        self._enable_btn = ctk.CTkButton(
            bar, text="🎙 Enable Voice FX", width=180, height=40,
            font=ctk.CTkFont(size=13),
            command=self._toggle_fx)
        self._enable_btn.grid(row=0, column=0, padx=12, pady=10)

        # Status
        self._status_var = tk.StringVar(value="Inactive")
        ctk.CTkLabel(bar, textvariable=self._status_var,
                     font=ctk.CTkFont(size=12), text_color="gray60"
                     ).grid(row=0, column=1, padx=8)

        if not HAS_PEDALBOARD:
            ctk.CTkLabel(
                bar,
                text="⚠ pedalboard not installed — limited effects quality",
                font=ctk.CTkFont(size=11), text_color="orange",
            ).grid(row=0, column=2, padx=12)

    def _build_main_area(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)

        # Left: presets + dry/wet
        left = ctk.CTkFrame(main, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=0)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Effect Presets",
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")

        # Preset grid (2 columns)
        preset_grid = ctk.CTkFrame(left, fg_color="transparent")
        preset_grid.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        preset_grid.grid_columnconfigure(0, weight=1)
        preset_grid.grid_columnconfigure(1, weight=1)

        presets = list(PRESET_DESCRIPTIONS.items())
        for i, (preset, (label, color, desc)) in enumerate(presets):
            r, c = divmod(i, 2)
            btn = ctk.CTkButton(
                preset_grid,
                text=f"{label}\n",
                height=60,
                fg_color=("gray80", "gray25"),
                hover_color=("gray70", "gray35"),
                text_color=color,
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda p=preset: self._select_preset(p),
            )
            btn.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
            self._preset_btns[preset] = btn

        # Dry/Wet slider
        dw_frame = ctk.CTkFrame(left, fg_color="transparent")
        dw_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(16, 8))
        dw_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(dw_frame, text="Dry/Wet:",
                     font=ctk.CTkFont(size=12)
                     ).grid(row=0, column=0, padx=(0, 8))

        self._dw_slider = ctk.CTkSlider(
            dw_frame, from_=0.0, to=1.0,
            command=self._on_dw_change)
        self._dw_slider.set(self.fx.dry_wet)
        self._dw_slider.grid(row=0, column=1, sticky="ew")

        self._dw_label = ctk.CTkLabel(
            dw_frame, text=f"{int(self.fx.dry_wet * 100)}%",
            font=ctk.CTkFont(size=11), width=40)
        self._dw_label.grid(row=0, column=2, padx=(8, 0))

        # Right: level meters
        right = ctk.CTkFrame(main, corner_radius=10, width=120)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=0)
        right.grid_propagate(False)
        right.grid_columnconfigure(0, weight=1)
        right.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(right, text="Levels",
                     font=ctk.CTkFont(size=12, weight="bold")
                     ).grid(row=0, column=0, columnspan=2, pady=(12, 4))

        ctk.CTkLabel(right, text="In", font=ctk.CTkFont(size=10)
                     ).grid(row=1, column=0)
        ctk.CTkLabel(right, text="Out", font=ctk.CTkFont(size=10)
                     ).grid(row=1, column=1)

        self._in_meter = ctk.CTkProgressBar(right, orientation="vertical",
                                             height=200, width=18)
        self._in_meter.set(0)
        self._in_meter.grid(row=2, column=0, padx=10, pady=8)

        self._out_meter = ctk.CTkProgressBar(right, orientation="vertical",
                                              height=200, width=18)
        self._out_meter.set(0)
        self._out_meter.grid(row=2, column=1, padx=10, pady=8)

        # Highlight current preset (NONE at start)
        self._highlight_preset(EffectPreset.NONE)

    def _build_device_panel(self):
        panel = ctk.CTkFrame(self, corner_radius=10)
        panel.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))
        panel.grid_columnconfigure(1, weight=1)
        panel.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(panel, text="Input Device:",
                     font=ctk.CTkFont(size=12)
                     ).grid(row=0, column=0, padx=12, pady=10)

        input_names, output_names = self._get_device_names()

        self._input_var = ctk.StringVar(value=input_names[0] if input_names else "Default")
        ctk.CTkOptionMenu(
            panel, values=input_names or ["Default"],
            variable=self._input_var, width=220,
            command=self._on_device_change,
        ).grid(row=0, column=1, padx=8, pady=10)

        ctk.CTkLabel(panel, text="Output Device:",
                     font=ctk.CTkFont(size=12)
                     ).grid(row=0, column=2, padx=12, pady=10)

        self._output_var = ctk.StringVar(value=output_names[0] if output_names else "Default")
        ctk.CTkOptionMenu(
            panel, values=output_names or ["Default"],
            variable=self._output_var, width=220,
            command=self._on_device_change,
        ).grid(row=0, column=3, padx=8, pady=10)

    # ── Control handlers ──────────────────────────────────────────
    def _toggle_fx(self):
        if self.fx.is_running:
            self.fx.stop()
            self._enable_btn.configure(
                text="🎙 Enable Voice FX",
                fg_color=("#3a7ebf", "#1f538d"),
                hover_color=("#325882", "#14375e"))
            self._status_var.set("Inactive")
        else:
            self.fx.start()
            if self.fx.is_running:
                self._enable_btn.configure(
                    text="⏹ Disable Voice FX",
                    fg_color="#c62828", hover_color="#b71c1c")
                self._status_var.set("Active")
            else:
                self._status_var.set("Failed to start — check audio devices")

    def _select_preset(self, preset: EffectPreset):
        self.fx.set_preset(preset)
        self._highlight_preset(preset)

    def _highlight_preset(self, active: EffectPreset):
        for preset, btn in self._preset_btns.items():
            if preset == active:
                btn.configure(
                    fg_color=("#3a7ebf", "#1f538d"),
                    hover_color=("#325882", "#14375e"),
                )
            else:
                btn.configure(
                    fg_color=("gray80", "gray25"),
                    hover_color=("gray70", "gray35"),
                )

    def _on_dw_change(self, value):
        self.fx.set_dry_wet(float(value))
        self._dw_label.configure(text=f"{int(float(value) * 100)}%")

    def _on_device_change(self, _=None):
        """Restart stream with new device selection."""
        was_running = self.fx.is_running
        if was_running:
            self.fx.stop()

        input_idx = self._get_device_index(self._input_var.get(), inputs=True)
        output_idx = self._get_device_index(self._output_var.get(), inputs=False)
        self.fx.input_device = input_idx
        self.fx.output_device = output_idx

        if was_running:
            self.fx.start()

    # ── Level meters ──────────────────────────────────────────────
    def _schedule_meters(self):
        self._update_meters()
        self._meter_job = self.after(66, self._schedule_meters)

    def _update_meters(self):
        # Scale level (typically 0-0.1 range) to 0-1 for progress bar
        in_val = min(self.fx.input_level * 10, 1.0)
        out_val = min(self.fx.output_level * 10, 1.0)
        self._in_meter.set(in_val)
        self._out_meter.set(out_val)

    # ── Device helpers ────────────────────────────────────────────
    def _get_device_names(self) -> tuple[list[str], list[str]]:
        if not HAS_SD:
            return [], []
        try:
            devices = sd.query_devices()
            inputs = [f"{i}: {d['name']}" for i, d in enumerate(devices)
                      if d["max_input_channels"] > 0]
            outputs = [f"{i}: {d['name']}" for i, d in enumerate(devices)
                       if d["max_output_channels"] > 0]
            return inputs or ["Default"], outputs or ["Default"]
        except Exception:
            return ["Default"], ["Default"]

    def _get_device_index(self, name: str, inputs: bool):
        if name == "Default" or not HAS_SD:
            return None
        try:
            idx = int(name.split(":")[0])
            return idx
        except (ValueError, IndexError):
            return None
