"""
ConductorSBN – Soundboard View
Grid of key→sound bindings.  Pressing a bound key plays the sound.
Keyword detection (Vosk) can be toggled on; detected keywords highlight
matching cards in real-time.
"""

import json
import os
import tkinter as tk
from threading import Thread
from tkinter import StringVar

import customtkinter as ctk
import sounddevice as sd
import vosk
import yaml
from pygame import mixer


class SoundboardView(ctk.CTkFrame):
    """Soundboard with key bindings and optional live keyword detection."""

    COLS = 5                          # cards per row
    FLASH_MS = 400                    # highlight duration (ms)
    SB_PATH = "config/soundboard_config.yaml"

    def __init__(self, parent, config_path: str):
        super().__init__(parent, fg_color="transparent")
        self.config_path = config_path
        self.active = False
        self.listening = False
        self._listen_thread: Thread | None = None
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._bindings: dict[str, dict] = {}
        self._load_configs()
        self._build_ui()

    # ── Config I/O ────────────────────────────────────────────────────
    def _load_configs(self):
        with open(self.config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.triggers: dict = cfg.get("sound_triggers", {})

        if os.path.exists(self.SB_PATH):
            with open(self.SB_PATH, encoding="utf-8") as f:
                sb = yaml.safe_load(f) or {}
        else:
            sb = {}
        self._bindings = sb.get("bindings", {})

    def _save_bindings(self):
        os.makedirs(os.path.dirname(self.SB_PATH), exist_ok=True)
        with open(self.SB_PATH, "w", encoding="utf-8") as f:
            yaml.dump(
                {"bindings": self._bindings}, f,
                default_flow_style=False, sort_keys=False,
            )

    # ── UI construction ───────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # -- Top control bar --
        bar = ctk.CTkFrame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 3))

        self._listen_btn = ctk.CTkButton(
            bar, text="\U0001F3A4  Start Listening", width=190, height=40,
            font=ctk.CTkFont(size=13), command=self._toggle_listen,
        )
        self._listen_btn.pack(side="left", padx=10, pady=8)

        self._status = ctk.CTkLabel(
            bar, text="Idle", font=ctk.CTkFont(size=12), text_color="gray60",
        )
        self._status.pack(side="left", padx=15)

        ctk.CTkButton(
            bar, text="＋ Add Binding", width=150, height=40,
            command=self._open_add_dialog,
        ).pack(side="right", padx=10, pady=8)

        # -- Card grid --
        self._grid = ctk.CTkScrollableFrame(self)
        self._grid.grid(row=1, column=0, sticky="nsew", padx=5, pady=3)

        # -- Bottom: last-heard text --
        self._heard_var = StringVar(value="")
        ctk.CTkLabel(
            self, textvariable=self._heard_var,
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="gray50", anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 6))

        self._refresh_grid()

    # ── Card grid ─────────────────────────────────────────────────────
    def _refresh_grid(self):
        for w in self._grid.winfo_children():
            w.destroy()
        self._cards.clear()

        for c in range(self.COLS):
            self._grid.grid_columnconfigure(c, weight=1, minsize=145)

        for idx, (key, bind) in enumerate(self._bindings.items()):
            r, c = divmod(idx, self.COLS)
            card = self._make_card(key, bind)
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            self._cards[key] = card

    def _make_card(self, key: str, bind: dict) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self._grid, width=145, height=125, corner_radius=10,
            border_width=2, border_color=("gray70", "gray30"),
        )
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=key.upper(),
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, pady=(14, 2))

        name = bind.get("name", bind.get("file", ""))
        display = (name[:18] + "\u2026") if len(name) > 20 else name
        ctk.CTkLabel(
            card, text=display, font=ctk.CTkFont(size=10),
        ).grid(row=1, column=0, pady=1)

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=2, column=0, pady=(4, 8))
        ctk.CTkButton(
            btns, text="\U0001F50A", width=32, height=26,
            command=lambda b=bind: self._play(b),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btns, text="\u2715", width=32, height=26,
            fg_color="#c62828", hover_color="#b71c1c",
            command=lambda k=key: self._remove(k),
        ).pack(side="left", padx=2)

        return card

    # ── Sound playback ────────────────────────────────────────────────
    @staticmethod
    def _play(bind: dict):
        fp = os.path.join("sounds", bind["file"])
        if os.path.exists(fp):
            snd = mixer.Sound(fp)
            snd.set_volume(bind.get("volume", 0.5))
            Thread(target=snd.play, daemon=True).start()

    def _remove(self, key: str):
        self._bindings.pop(key, None)
        self._save_bindings()
        self._refresh_grid()

    # ── Add-binding dialog ────────────────────────────────────────────
    def _open_add_dialog(self):
        dlg = _AddBindingDialog(self, self.triggers)
        self.wait_window(dlg)
        if dlg.result:
            key, kw, fname, vol = dlg.result
            self._bindings[key] = {
                "name": kw, "file": fname, "volume": vol,
            }
            self._save_bindings()
            self._refresh_grid()

    # ── Keyboard handling ─────────────────────────────────────────────
    def activate(self):
        """Called when this view becomes visible."""
        self._load_configs()
        self._refresh_grid()
        self.active = True
        self.winfo_toplevel().bind("<KeyPress>", self._on_key, add="+")

    def deactivate(self):
        """Called when leaving this view."""
        self.active = False
        try:
            self.winfo_toplevel().unbind("<KeyPress>")
        except Exception:
            pass
        if self.listening:
            self._stop_listen()

    def _on_key(self, event):
        # Don't intercept typing in entry fields / combo boxes
        if isinstance(event.widget, tk.Entry):
            return
        if event.widget.winfo_toplevel() != self.winfo_toplevel():
            return
        key = event.keysym.lower()
        if key in self._bindings:
            self._play(self._bindings[key])
            self._flash(key)

    def _flash(self, key: str, color=("#FFD700", "#B8860B")):
        card = self._cards.get(key)
        if not card:
            return
        orig = card.cget("border_color")
        card.configure(border_color=color, border_width=3)
        self.after(
            self.FLASH_MS,
            lambda: card.configure(border_color=orig, border_width=2),
        )

    # ── Keyword detection (Vosk) ──────────────────────────────────────
    def _toggle_listen(self):
        if self.listening:
            self._stop_listen()
        else:
            self._start_listen()

    def _start_listen(self):
        self.listening = True
        self._listen_btn.configure(
            text="\U0001F3A4  Stop Listening",
            fg_color="#c62828", hover_color="#b71c1c",
        )
        self._status.configure(text="Loading model\u2026", text_color="orange")
        self._listen_thread = Thread(target=self._listen_loop, daemon=True)
        self._listen_thread.start()

    def _stop_listen(self):
        self.listening = False
        self._listen_btn.configure(
            text="\U0001F3A4  Start Listening",
            fg_color=("#3a7ebf", "#1f538d"),
            hover_color=("#325882", "#14375e"),
        )
        self._status.configure(text="Idle", text_color="gray60")
        self._heard_var.set("")

    def _listen_loop(self):
        model_path = "vosk-model-small-en-us-0.15/vosk-model-small-en-us-0.15"
        if not os.path.exists(model_path):
            self.after(
                0, lambda: self._status.configure(
                    text="Vosk model not found!", text_color="red"),
            )
            self.listening = False
            return

        try:
            model = vosk.Model(model_path)
        except Exception as exc:
            self.after(
                0, lambda: self._status.configure(
                    text=f"Model error: {exc}", text_color="red"),
            )
            self.listening = False
            return

        self.after(
            0, lambda: self._status.configure(
                text="Listening\u2026", text_color="#4caf50"),
        )

        played: set[str] = set()
        sr = 16000

        try:
            with sd.RawInputStream(
                samplerate=sr, blocksize=4000, dtype="int16", channels=1,
            ) as stream:
                rec = vosk.KaldiRecognizer(model, sr)
                while self.listening:
                    data, _ = stream.read(4000)
                    raw = data[:]
                    if not raw:
                        break

                    if rec.AcceptWaveform(raw):
                        text = json.loads(rec.Result()).get("text", "")
                        if text:
                            self.after(
                                0, lambda t=text: self._heard_var.set(
                                    f"Heard: {t}"),
                            )
                            self._match_triggers(text, played, partial=False)
                        played.clear()
                    else:
                        p = json.loads(rec.PartialResult()).get("partial", "")
                        if p:
                            self._match_triggers(p, played, partial=True)
        except Exception as exc:
            self.after(
                0, lambda: self._status.configure(
                    text=f"Error: {exc}", text_color="red"),
            )
        finally:
            self.after(0, self._stop_listen)

    def _match_triggers(self, text: str, played: set, *, partial: bool):
        text_l = text.lower()
        for trigger, params in self.triggers.items():
            if trigger in text_l and trigger not in played:
                fp = os.path.join("sounds", params["file"])
                if os.path.exists(fp):
                    snd = mixer.Sound(fp)
                    snd.set_volume(params["volume"])
                    Thread(target=snd.play, daemon=True).start()
                    played.add(trigger)

                    # Highlight matching soundboard cards (green flash)
                    sfile = params["file"]
                    for k, b in self._bindings.items():
                        if b.get("name") == trigger or b.get("file") == sfile:
                            self.after(
                                0, lambda k=k: self._flash(
                                    k, color=("#4caf50", "#2e7d32")),
                            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Add-Binding Dialog
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class _AddBindingDialog(ctk.CTkToplevel):
    """Modal dialog: capture a key, pick a sound, create a binding."""

    def __init__(self, parent, triggers: dict):
        super().__init__(parent)
        self.title("Add Key Binding")
        self.geometry("440x320")
        self.resizable(False, False)
        self.triggers = triggers
        self.result = None
        self._captured_key: str | None = None

        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.focus_set()

        # ── Key capture area ──
        ctk.CTkLabel(
            self, text="Press the key you want to bind:",
            font=ctk.CTkFont(size=13),
        ).pack(padx=20, pady=(24, 4))

        self._key_lbl = ctk.CTkLabel(
            self, text="[ press any key ]",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self._key_lbl.pack(pady=(0, 16))
        self.bind("<KeyPress>", self._capture)

        # ── Sound picker ──
        ctk.CTkLabel(
            self, text="Sound to play:", font=ctk.CTkFont(size=13),
        ).pack(padx=20, anchor="w")

        names = sorted(triggers.keys())
        self._sound_var = ctk.StringVar(value=names[0] if names else "")
        self._combo = ctk.CTkComboBox(
            self, values=names, variable=self._sound_var, width=380,
        )
        self._combo.pack(padx=20, pady=(4, 20))

        # ── Confirm ──
        ctk.CTkButton(
            self, text="Add Binding", width=220, height=40,
            command=self._confirm,
        ).pack(pady=(0, 16))

    def _capture(self, event):
        # Ignore key events aimed at the combo box's internal entry
        if isinstance(event.widget, tk.Entry):
            return
        self._captured_key = event.keysym.lower()
        self._key_lbl.configure(text=self._captured_key.upper())

    def _confirm(self):
        kw = self._sound_var.get()
        if not self._captured_key or not kw:
            return
        p = self.triggers.get(kw, {})
        self.result = (
            self._captured_key, kw,
            p.get("file", ""), p.get("volume", 0.5),
        )
        self.destroy()
