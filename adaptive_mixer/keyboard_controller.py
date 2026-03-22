"""
MixerKeyboardController — Maps keyboard hotkeys to adaptive mixer commands.

Integrates with the existing ConductorSBN keyboard system.
Uses Ctrl+key combinations to avoid conflicts with existing soundboard bindings.

Key mapping (all require Ctrl modifier):
    Ctrl+1 through Ctrl+9 : Toggle stems 1-9
    Ctrl+Up               : Increase master volume
    Ctrl+Down             : Decrease master volume
    Ctrl+Right            : Increase intensity
    Ctrl+Left             : Decrease intensity
    Ctrl+space            : Panic (fade all to silence)
    Ctrl+t                : Cycle and trigger next leitmotif
    Ctrl+l                : Stop current leitmotif

Function keys (no modifier needed — not used by existing system):
    F1-F9                 : Load scene by index
    F10                   : Cycle to next scene
"""

from .mixer import AdaptiveMixer


class MixerKeyboardController:
    def __init__(self, mixer: AdaptiveMixer):
        self._mixer = mixer
        self._available_scenes: list = []
        self._leitmotif_cycle_idx: int = 0
        self._scene_cycle_idx: int = 0
        self._current_intensity: int = 0

    def set_available_scenes(self, scene_dirs: list):
        """Set the list of available scene directories for cycling."""
        self._available_scenes = scene_dirs

    def handle_ctrl_key(self, key: str):
        """
        Process a Ctrl+key press from the existing keyboard handler.

        Args:
            key: Key symbol string from tkinter event.keysym (e.g. "1", "Up", "space").
        """
        key_lower = key.lower() if isinstance(key, str) else str(key)

        # Ctrl+1-9: toggle stem by index
        if key_lower.isdigit() and key_lower != "0":
            idx = int(key_lower) - 1
            stems = self._mixer.get_stem_names()
            if idx < len(stems):
                self._mixer.toggle_stem(stems[idx])
                status = self._mixer.get_stem_status()
                stem_name = stems[idx]
                state = "ON" if status.get(stem_name, {}).get("is_audible") else "fading out"
                print(f"[MixerKeys] Stem '{stem_name}': {state}")
            return

        # Ctrl+Up: mixer master volume up
        if key_lower in ("up",):
            vol = min(self._mixer._master_volume + 0.05, 1.0)
            self._mixer.set_master_volume(vol)
            print(f"[MixerKeys] Master volume: {vol:.2f}")
            return

        # Ctrl+Down: mixer master volume down
        if key_lower in ("down",):
            vol = max(self._mixer._master_volume - 0.05, 0.0)
            self._mixer.set_master_volume(vol)
            print(f"[MixerKeys] Master volume: {vol:.2f}")
            return

        # Ctrl+Right: intensity up
        if key_lower in ("right",):
            self._current_intensity = min(self._current_intensity + 1, 3)
            self._mixer.set_intensity(self._current_intensity)
            print(f"[MixerKeys] Intensity: {self._current_intensity}")
            return

        # Ctrl+Left: intensity down
        if key_lower in ("left",):
            self._current_intensity = max(self._current_intensity - 1, 0)
            self._mixer.set_intensity(self._current_intensity)
            print(f"[MixerKeys] Intensity: {self._current_intensity}")
            return

        # Ctrl+Space: panic
        if key_lower in ("space",):
            self._mixer.panic()
            self._current_intensity = 0
            print("[MixerKeys] PANIC — all silent")
            return

        # Ctrl+T: cycle leitmotifs
        if key_lower == "t":
            leitmotifs = self._mixer.get_leitmotif_names()
            if leitmotifs:
                lm_id = leitmotifs[self._leitmotif_cycle_idx % len(leitmotifs)]
                self._mixer.trigger_leitmotif(lm_id)
                print(f"[MixerKeys] Leitmotif: {lm_id}")
                self._leitmotif_cycle_idx = (
                    self._leitmotif_cycle_idx + 1
                ) % len(leitmotifs)
            return

        # Ctrl+L: stop leitmotif
        if key_lower == "l":
            self._mixer.stop_leitmotif()
            print("[MixerKeys] Leitmotif stopped")
            return

    def handle_function_key(self, key: str):
        """
        Process function key presses (F1-F10).

        Args:
            key: Key symbol from tkinter (e.g. "F1", "F10").
        """
        key_lower = key.lower()

        if key_lower == "f10":
            # Cycle to next scene
            if self._available_scenes:
                scene_dir = self._available_scenes[
                    self._scene_cycle_idx % len(self._available_scenes)
                ]
                import threading
                t = threading.Thread(
                    target=self._mixer.load_scene, args=(scene_dir,), daemon=True
                )
                t.start()
                self._scene_cycle_idx = (
                    self._scene_cycle_idx + 1
                ) % len(self._available_scenes)
                print(f"[MixerKeys] Loading scene: {scene_dir}")
            return

        if key_lower.startswith("f") and key_lower[1:].isdigit():
            scene_idx = int(key_lower[1:]) - 1
            if 0 <= scene_idx < len(self._available_scenes):
                scene_dir = self._available_scenes[scene_idx]
                import threading
                t = threading.Thread(
                    target=self._mixer.load_scene, args=(scene_dir,), daemon=True
                )
                t.start()
                print(f"[MixerKeys] Loading scene: {scene_dir}")
            return
