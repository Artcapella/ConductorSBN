"""Debug script to find why FLUIDSYNTH_AVAILABLE is False when imported via gui.app."""
import os, sys

# NO pre-adding DLL dirs - mimicking gui_main.py exactly

# Step 1: import pygame mixer (like app.py line 8)  
print("[1] Importing pygame mixer...")
from pygame import mixer as pmixer
print(f"    OK")

# Step 2: import customtkinter (like app.py line 7)
print("[2] Importing customtkinter...")
import customtkinter as ctk
print(f"    OK")

# Step 3: Now import adaptive_mixer (the EXACT way app.py does it)
print("[3] Importing adaptive_mixer (app.py style)...")
try:
    from adaptive_mixer import (
        AdaptiveMixer, SceneManager,
        MixerGestureController, MixerKeyboardController,
    )
    print("    Import OK")
    from adaptive_mixer.midi_generator import FLUIDSYNTH_AVAILABLE
    print(f"    FLUIDSYNTH_AVAILABLE = {FLUIDSYNTH_AVAILABLE}")
except ImportError as e:
    print(f"    Import FAILED: {e}")
    FLUIDSYNTH_AVAILABLE = False

# Step 4: Create mixer (the EXACT way app.py does it)
print("[4] Creating AdaptiveMixer...")
try:
    m = AdaptiveMixer(
        soundfont_path="assets/soundfonts/FluidR3_GM.sf2",
        leitmotif_config_path="assets/leitmotifs/leitmotifs.json",
    )
    names = m.get_leitmotif_names()
    print(f"    Leitmotifs loaded: {len(names)}")
    m.cleanup()
except Exception as e:
    print(f"    FAILED: {e}")

