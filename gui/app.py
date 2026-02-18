"""
ConductorSBN – Main GUI Application
Provides a sidebar to switch between the Keyword Editor and Soundboard views.
"""

import customtkinter as ctk
from pygame import mixer

from gui.keyword_view import KeywordView
from gui.soundboard_view import SoundboardView

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

        # Layout: sidebar (col 0) + content (col 1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

        self._current: str | None = None
        self._show_keywords()

    # ── Sidebar ───────────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=185, corner_radius=0,
                          fg_color=("gray88", "gray14"))
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(3, weight=1)

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

        # Theme picker at bottom
        ctk.CTkLabel(sb, text="Theme:", font=ctk.CTkFont(size=11)).grid(
            row=4, column=0, padx=18, pady=(0, 2), sticky="w",
        )
        menu = ctk.CTkOptionMenu(
            sb, values=["Dark", "Light", "System"], width=145,
            command=lambda v: ctk.set_appearance_mode(v),
        )
        menu.set("Dark")
        menu.grid(row=5, column=0, padx=18, pady=(0, 20))

    # ── Content area ──────────────────────────────────────────────────
    def _build_content(self):
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._kw_view = KeywordView(self._content, CONFIG)
        self._sb_view = SoundboardView(self._content, CONFIG)

    # ── Navigation ────────────────────────────────────────────────────
    def _show_keywords(self):
        if self._current == "kw":
            return
        self._current = "kw"
        self._sb_view.deactivate()
        self._sb_view.grid_forget()
        self._kw_view.reload()
        self._kw_view.grid(row=0, column=0, sticky="nsew")
        self._kw_btn.configure(fg_color=self._ACTIVE_COLOR)
        self._sb_btn.configure(fg_color=self._INACTIVE_COLOR)

    def _show_soundboard(self):
        if self._current == "sb":
            return
        self._current = "sb"
        self._kw_view.grid_forget()
        self._sb_view.grid(row=0, column=0, sticky="nsew")
        self._sb_view.activate()
        self._sb_btn.configure(fg_color=self._ACTIVE_COLOR)
        self._kw_btn.configure(fg_color=self._INACTIVE_COLOR)


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ConductorApp()
    app.mainloop()
