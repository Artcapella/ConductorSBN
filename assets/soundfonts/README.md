# SoundFonts

Place a General MIDI SoundFont (.sf2) file here named `FluidR3_GM.sf2`.

## How to get it

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install fluid-soundfont-gm
# File will be at: /usr/share/sounds/sf2/FluidR3_GM.sf2
# Copy it here: cp /usr/share/sounds/sf2/FluidR3_GM.sf2 assets/soundfonts/
```

**macOS:**
```bash
brew install fluid-synth
# SoundFont is usually at /usr/local/share/soundfonts/default.sf2
```

**Windows:**
Download from: https://member.keymusician.com/Member/FluidR3_GM/index.html
Place `FluidR3_GM.sf2` in this directory.

Without a SoundFont, the adaptive mixer will still work for audio stem playback —
only leitmotif (MIDI) playback will be disabled.
