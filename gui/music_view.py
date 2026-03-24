"""
ConductorSBN – Music View
Track library browser with playback controls and key binding editor.
"""

import os
import tkinter as tk
from tkinter import filedialog
from typing import Optional

import customtkinter as ctk


class MusicView(ctk.CTkFrame):
    """Background music controller view."""

    def __init__(self, parent, music_controller, binding_manager):
        super().__init__(parent, fg_color="transparent")
        self.mc = music_controller
        self.bm = binding_manager
        self._track_rows: list[ctk.CTkFrame] = []
        self._selected_idx: Optional[int] = None
        self._update_job = None
        self._build_ui()

    def activate(self):
        self._refresh_library()
        self._schedule_update()

    def deactivate(self):
        if self._update_job:
            self.after_cancel(self._update_job)
            self._update_job = None

    # ── Layout ────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top: Now Playing bar
        self._build_now_playing()

        # Middle: Track library
        self._build_library()

        # Bottom: Controls
        self._build_controls()

    def _build_now_playing(self):
        bar = ctk.CTkFrame(self, corner_radius=10)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bar, text="Now Playing",
                     font=ctk.CTkFont(size=11), text_color="gray60"
                     ).grid(row=0, column=0, padx=12, pady=(8, 0), sticky="w")

        self._now_playing_var = tk.StringVar(value="— nothing playing —")
        ctk.CTkLabel(bar, textvariable=self._now_playing_var,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").grid(row=1, column=0, columnspan=3,
                                      padx=12, pady=(0, 4), sticky="w")

        self._state_var = tk.StringVar(value="Stopped")
        ctk.CTkLabel(bar, textvariable=self._state_var,
                     font=ctk.CTkFont(size=11), text_color="gray60"
                     ).grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        # Transport buttons
        btn_frame = ctk.CTkFrame(bar, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=3, padx=12, pady=8)

        ctk.CTkButton(btn_frame, text="⏮", width=36, height=32,
                      command=self._prev).pack(side="left", padx=2)
        self._play_pause_btn = ctk.CTkButton(
            btn_frame, text="▶", width=36, height=32,
            command=self._play_pause)
        self._play_pause_btn.pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="⏹", width=36, height=32,
                      command=self._stop).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="⏭", width=36, height=32,
                      command=self._next).pack(side="left", padx=2)

    def _build_library(self):
        lib_frame = ctk.CTkFrame(self, corner_radius=10)
        lib_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        lib_frame.grid_columnconfigure(0, weight=1)
        lib_frame.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(lib_frame, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="Track Library",
                     font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, sticky="w")

        folder_btn = ctk.CTkButton(
            hdr, text="📁 Change Folder", width=140, height=30,
            command=self._choose_folder)
        folder_btn.grid(row=0, column=1, padx=(8, 0))

        self._folder_var = tk.StringVar(value="music/")
        ctk.CTkLabel(hdr, textvariable=self._folder_var,
                     font=ctk.CTkFont(size=10), text_color="gray60"
                     ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 4))

        # Scrollable track list
        self._track_list = ctk.CTkScrollableFrame(lib_frame)
        self._track_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self._track_list.grid_columnconfigure(0, weight=1)

    def _build_controls(self):
        ctrl = ctk.CTkFrame(self, corner_radius=10)
        ctrl.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))
        ctrl.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ctrl, text="Volume:", font=ctk.CTkFont(size=12)
                     ).grid(row=0, column=0, padx=12, pady=10)

        self._vol_slider = ctk.CTkSlider(
            ctrl, from_=0.0, to=1.0, width=200,
            command=self._on_volume_change)
        self._vol_slider.set(self.mc.get_volume())
        self._vol_slider.grid(row=0, column=1, padx=8, pady=10, sticky="w")

        self._vol_label = ctk.CTkLabel(
            ctrl, text=f"{int(self.mc.get_volume() * 100)}%",
            font=ctk.CTkFont(size=11))
        self._vol_label.grid(row=0, column=2, padx=8)

    # ── Library population ────────────────────────────────────────
    def _refresh_library(self):
        for w in self._track_list.winfo_children():
            w.destroy()
        self._track_rows.clear()

        library = self.mc.library
        bindings = self.bm.get_all()
        # Reverse: key → index
        key_for_idx = {v: k for k, v in bindings.items()}

        if not library:
            ctk.CTkLabel(
                self._track_list,
                text="No tracks found.\nAdd music files to the music/ folder\nor change the folder above.",
                font=ctk.CTkFont(size=12), text_color="gray60",
                justify="center",
            ).grid(row=0, column=0, pady=40)
            return

        for idx, track in enumerate(library):
            row = ctk.CTkFrame(self._track_list, corner_radius=6, height=40)
            row.grid(row=idx, column=0, sticky="ew", padx=4, pady=2)
            row.grid_propagate(False)
            row.grid_columnconfigure(1, weight=1)

            # Key badge
            key_label = key_for_idx.get(idx, "")
            badge = ctk.CTkLabel(
                row,
                text=key_label.upper() if key_label else "—",
                font=ctk.CTkFont(size=12, weight="bold"),
                width=30, text_color=("gray30", "gray70"),
            )
            badge.grid(row=0, column=0, padx=(8, 4), pady=4)

            name_lbl = ctk.CTkLabel(
                row, text=track.name, anchor="w",
                font=ctk.CTkFont(size=12))
            name_lbl.grid(row=0, column=1, sticky="ew", padx=4)

            # Play button
            play_btn = ctk.CTkButton(
                row, text="▶", width=30, height=26,
                command=lambda t=track: self.mc.play(t))
            play_btn.grid(row=0, column=2, padx=4, pady=4)

            # Bind key button
            bind_btn = ctk.CTkButton(
                row, text="⌨", width=30, height=26,
                command=lambda i=idx: self._open_bind_dialog(i))
            bind_btn.grid(row=0, column=3, padx=(0, 8), pady=4)

            self._track_rows.append(row)

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Select Music Folder")
        if folder:
            self._folder_var.set(folder)
            self.mc.load_library(folder)
            self._refresh_library()

    # ── Playback controls ─────────────────────────────────────────
    def _play_pause(self):
        from core.music_controller import PlaybackState
        state = self.mc.get_state()
        if state == PlaybackState.PLAYING:
            self.mc.pause()
        elif state == PlaybackState.PAUSED:
            self.mc.resume()
        else:
            self.mc.resume()

    def _stop(self):
        self.mc.stop()

    def _next(self):
        self.mc.play_next()

    def _prev(self):
        self.mc.play_previous()

    def _on_volume_change(self, value):
        self.mc.set_volume(float(value))
        self._vol_label.configure(text=f"{int(float(value) * 100)}%")

    # ── Now Playing updater ───────────────────────────────────────
    def _schedule_update(self):
        self._update_now_playing()
        self._update_job = self.after(500, self._schedule_update)

    def _update_now_playing(self):
        from core.music_controller import PlaybackState
        track = self.mc.get_current_track()
        state = self.mc.get_state()

        if track:
            self._now_playing_var.set(track.name)
        else:
            self._now_playing_var.set("— nothing playing —")

        state_map = {
            PlaybackState.PLAYING: ("Playing", "#4caf50"),
            PlaybackState.PAUSED: ("Paused", "orange"),
            PlaybackState.STOPPED: ("Stopped", "gray60"),
            PlaybackState.FADING_IN: ("Fading In", "#4caf50"),
            PlaybackState.FADING_OUT: ("Fading Out", "orange"),
        }
        label, color = state_map.get(state, ("Unknown", "gray60"))
        self._state_var.set(label)

        btn_text = "⏸" if state == PlaybackState.PLAYING else "▶"
        self._play_pause_btn.configure(text=btn_text)

    # ── Bind dialog ───────────────────────────────────────────────
    def _open_bind_dialog(self, track_idx: int):
        dlg = _BindKeyDialog(self, track_idx, self.mc.library[track_idx].name)
        self.wait_window(dlg)
        if dlg.result is not None:
            key, idx = dlg.result
            if key:
                self.bm.bind(key, idx)
            self._refresh_library()


class _BindKeyDialog(ctk.CTkToplevel):
    """Capture a number/letter key to bind to a track."""

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
            self,
            text=f"Binding: {track_name}",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=20, pady=(20, 4))

        ctk.CTkLabel(
            self,
            text="Press a number key (0-9) to assign it:",
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
        ctk.CTkButton(btns, text="Confirm", width=120, command=self._confirm
                      ).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Unbind", width=120,
                      fg_color="#c62828", hover_color="#b71c1c",
                      command=self._unbind).pack(side="left", padx=8)

        self._captured = None

    def _capture(self, event):
        if isinstance(event.widget, tk.Entry):
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
