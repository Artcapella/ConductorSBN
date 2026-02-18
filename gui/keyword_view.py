"""
ConductorSBN – Keyword Editor View
Displays all keywords from the YAML config.  Clicking a keyword opens an
edit panel with volume slider (0‒1.0), sound-file field, and play button.
"""

import os
import tkinter as tk
from threading import Thread

import customtkinter as ctk
import yaml
from pygame import mixer
from tkinter import filedialog


class KeywordView(ctk.CTkFrame):
    """Left: scrollable keyword list  |  Right: edit panel."""

    def __init__(self, parent, config_path: str):
        super().__init__(parent, fg_color="transparent")
        self.config_path = config_path
        self.selected_keyword: str | None = None
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._load_config()
        self._build_ui()

    # ── Config I/O ────────────────────────────────────────────────────
    def _load_config(self):
        with open(self.config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.triggers: dict = self.config.get("sound_triggers", {})

    def _save_config(self):
        self.config["sound_triggers"] = self.triggers
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(
                self.config, f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

    # ── UI construction ───────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=2, minsize=280)
        self.grid_columnconfigure(1, weight=3, minsize=360)
        self.grid_rowconfigure(0, weight=1)
        self._build_list_panel()
        self._build_edit_panel()

    # -- Left panel: keyword list --
    def _build_list_panel(self):
        panel = ctk.CTkFrame(self)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            panel, text="Keywords",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 5))

        # Search + Add bar
        toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        toolbar.grid_columnconfigure(0, weight=1)

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_list())
        ctk.CTkEntry(
            toolbar, placeholder_text="Search…", textvariable=self._search_var,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))

        ctk.CTkButton(
            toolbar, text="＋ Add", width=80, command=self._add_keyword,
        ).grid(row=0, column=1)

        # Scrollable list
        self._list_frame = ctk.CTkScrollableFrame(panel)
        self._list_frame.grid(
            row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10),
        )
        self._list_frame.grid_columnconfigure(0, weight=1)
        self._refresh_list()

    # -- Right panel: edit form --
    def _build_edit_panel(self):
        container = ctk.CTkFrame(self)
        container.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        # Placeholder shown when nothing is selected
        self._placeholder = ctk.CTkLabel(
            container, text="← Select a keyword to edit",
            font=ctk.CTkFont(size=15, slant="italic"), text_color="gray50",
        )
        self._placeholder.grid(row=0, column=0)

        # Editable form (hidden initially)
        form = ctk.CTkFrame(container, fg_color="transparent")
        form.grid_columnconfigure(0, weight=1)
        self._form = form
        self._form_container = container

        r = 0
        ctk.CTkLabel(form, text="Keyword",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=r, column=0, sticky="w", padx=20, pady=(20, 2)); r += 1
        self._kw_entry = ctk.CTkEntry(form, height=36)
        self._kw_entry.grid(row=r, column=0, sticky="ew", padx=20, pady=(0, 12)); r += 1

        ctk.CTkLabel(form, text="Volume",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=r, column=0, sticky="w", padx=20, pady=(8, 2)); r += 1
        vol_row = ctk.CTkFrame(form, fg_color="transparent")
        vol_row.grid(row=r, column=0, sticky="ew", padx=20, pady=(0, 12)); r += 1
        vol_row.grid_columnconfigure(0, weight=1)
        self._vol_slider = ctk.CTkSlider(
            vol_row, from_=0, to=1, number_of_steps=100, command=self._on_vol,
        )
        self._vol_slider.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self._vol_label = ctk.CTkLabel(vol_row, text="0.50", width=45)
        self._vol_label.grid(row=0, column=1)

        ctk.CTkLabel(form, text="Sound File",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=r, column=0, sticky="w", padx=20, pady=(8, 2)); r += 1
        file_row = ctk.CTkFrame(form, fg_color="transparent")
        file_row.grid(row=r, column=0, sticky="ew", padx=20, pady=(0, 12)); r += 1
        file_row.grid_columnconfigure(0, weight=1)
        self._file_entry = ctk.CTkEntry(file_row, height=36)
        self._file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(file_row, text="Browse", width=80,
                      command=self._browse).grid(row=0, column=1)

        self._play_btn = ctk.CTkButton(
            form, text="\U0001F50A  Play Sound", height=42,
            font=ctk.CTkFont(size=14), command=self._play,
        )
        self._play_btn.grid(row=r, column=0, padx=20, pady=(10, 6)); r += 1

        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.grid(row=r, column=0, sticky="ew", padx=20, pady=12)
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            actions, text="Save", fg_color="#2e7d32", hover_color="#1b5e20",
            command=self._save,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(
            actions, text="Delete", fg_color="#c62828", hover_color="#b71c1c",
            command=self._delete,
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

    # ── List helpers ──────────────────────────────────────────────────
    def _refresh_list(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._buttons.clear()

        query = self._search_var.get().lower()
        for i, kw in enumerate(self.triggers):
            if query and query not in kw.lower():
                continue
            btn = ctk.CTkButton(
                self._list_frame, text=kw, anchor="w", height=32,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray30"),
                command=lambda k=kw: self._select(k),
            )
            btn.grid(row=i, column=0, sticky="ew", pady=1)
            self._buttons[kw] = btn

        # Restore highlight
        if self.selected_keyword in self._buttons:
            self._buttons[self.selected_keyword].configure(
                fg_color=("gray75", "gray30"),
            )

    # ── Selection / editing ───────────────────────────────────────────
    def _select(self, kw: str):
        self.selected_keyword = kw
        params = self.triggers[kw]

        for k, btn in self._buttons.items():
            btn.configure(
                fg_color=("gray75", "gray30") if k == kw else "transparent",
            )

        self._kw_entry.delete(0, "end")
        self._kw_entry.insert(0, kw)
        self._vol_slider.set(params["volume"])
        self._vol_label.configure(text=f"{params['volume']:.2f}")
        self._file_entry.delete(0, "end")
        self._file_entry.insert(0, params["file"])

        self._placeholder.grid_forget()
        self._form.grid(row=0, column=0, sticky="nsew")

    def _on_vol(self, v):
        self._vol_label.configure(text=f"{v:.2f}")

    def _browse(self):
        path = filedialog.askopenfilename(
            initialdir=os.path.abspath("sounds"),
            title="Choose a sound file",
            filetypes=[("Audio", "*.mp3 *.wav *.ogg"), ("All", "*.*")],
        )
        if path:
            self._file_entry.delete(0, "end")
            self._file_entry.insert(0, os.path.basename(path))

    def _play(self):
        fname = self._file_entry.get().strip()
        if not fname:
            return
        fp = os.path.join("sounds", fname)
        if os.path.exists(fp):
            snd = mixer.Sound(fp)
            snd.set_volume(self._vol_slider.get())
            Thread(target=snd.play, daemon=True).start()

    def _save(self):
        if self.selected_keyword is None:
            return
        new_kw = self._kw_entry.get().strip()
        new_vol = round(self._vol_slider.get(), 2)
        new_file = self._file_entry.get().strip()
        if not new_kw or not new_file:
            return

        # Preserve order: replace in-place if renamed
        if new_kw != self.selected_keyword:
            rebuilt = {}
            for k, v in self.triggers.items():
                if k == self.selected_keyword:
                    rebuilt[new_kw] = {"file": new_file, "volume": new_vol}
                else:
                    rebuilt[k] = v
            self.triggers = rebuilt
        else:
            self.triggers[new_kw] = {"file": new_file, "volume": new_vol}

        self.config["sound_triggers"] = self.triggers
        self._save_config()
        self.selected_keyword = new_kw
        self._refresh_list()

    def _delete(self):
        if self.selected_keyword is None:
            return
        self.triggers.pop(self.selected_keyword, None)
        self.config["sound_triggers"] = self.triggers
        self._save_config()
        self.selected_keyword = None
        self._form.grid_forget()
        self._placeholder.grid(row=0, column=0)
        self._refresh_list()

    def _add_keyword(self):
        name = "new_keyword"
        n = 1
        while name in self.triggers:
            name = f"new_keyword_{n}"
            n += 1
        self.triggers[name] = {"file": "", "volume": 0.5}
        self._save_config()
        self._refresh_list()
        self._select(name)

    # ── Public ────────────────────────────────────────────────────────
    def reload(self):
        """Re-read config from disk (called when view becomes visible)."""
        self._load_config()
        self._refresh_list()
        if self.selected_keyword and self.selected_keyword in self.triggers:
            self._select(self.selected_keyword)
        else:
            self.selected_keyword = None
            self._form.grid_forget()
            self._placeholder.grid(row=0, column=0)
