"""
adaptive_mixer — Dynamic adaptive music mixing system for ConductorSBN.

Provides beat-synchronized stem layering, gesture-driven intensity control,
and keyboard hotkeys.

Quick start:
    from adaptive_mixer import AdaptiveMixer, MixerGestureController, \
        MixerKeyboardController, SceneManager

    scene_mgr = SceneManager("assets/music/scenes")
    mixer = AdaptiveMixer()
    gesture_ctrl = MixerGestureController(mixer)
    keyboard_ctrl = MixerKeyboardController(mixer)
    keyboard_ctrl.set_available_scenes(scene_mgr.get_scene_paths())

    scenes = scene_mgr.get_scene_list()
    if scenes:
        mixer.load_scene(scenes[0]["path"])
    mixer.start()
"""

from .mixer import AdaptiveMixer
from .beat_clock import BeatClock
from .stem_player import StemPlayer
from .gesture_controller import MixerGestureController
from .keyboard_controller import MixerKeyboardController
from .scene_manager import SceneManager

__all__ = [
    "AdaptiveMixer",
    "BeatClock",
    "StemPlayer",
    "MixerGestureController",
    "MixerKeyboardController",
    "SceneManager",
]
