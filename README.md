# ConductorSBN

A speech-reactive soundboard application built for tabletop RPG game masters (and anyone who wants real-time ambient audio control). ConductorSBN listens to your microphone for spoken keywords and automatically triggers matching sound effects — or lets you fire them manually via keyboard shortcuts in a visual grid interface.

---

## Features

### Speech Recognition (Offline)
- Uses [Vosk](https://alphacephei.com/vosk/) for fully offline, real-time speech recognition
- No internet connection required during use
- Detects keywords from your speech and instantly plays the mapped sound
- Prevents the same sound from retriggering mid-phrase

### Soundboard View
- Visual grid of sound cards, each bound to a keyboard key (A–Z)
- Press a key or click the play button to fire a sound
- Cards flash when triggered (manually or via speech)
- Toggle live keyword detection on/off from the soundboard
- Add or remove key bindings through a simple dialog

### Keyword Editor
- Browse and search all 100+ configured keyword-to-sound mappings
- Add new keywords, assign sound files via file browser, and set per-sound volume
- Preview sounds directly in the editor
- All changes auto-save to `config/sound_config.yaml`

### Audio Playback
- Powered by `pygame.mixer`
- Supports MP3, WAV, and OGG formats
- Sounds play in background threads — no blocking, overlapping playback supported
- Global volume control and per-sound base volume
- Voice commands: say **"louder"** or **"softer"** to adjust global volume on the fly

---

## Project Structure

```
ConductorSBN/
├── main.py                        # CLI-only speech recognition mode
├── gui_main.py                    # GUI entry point (recommended)
├── requirements.txt
├── config/
│   ├── sound_config.yaml         # Keyword → sound file + volume mappings
│   └── soundboard_config.yaml    # Keyboard key → sound bindings
├── core/
│   ├── sound_manager.py          # Sound loading and threaded playback
│   ├── speech_processor.py       # Speech recognition via Google API (CLI mode)
│   └── volume_controller.py      # Volume fade animations
├── gui/
│   ├── app.py                    # Root window and sidebar navigation
│   ├── keyword_view.py           # Keyword editor interface
│   └── soundboard_view.py        # Soundboard grid + Vosk listening
├── sounds/                        # ~70 fantasy-themed MP3/WAV sound effects
└── vosk-model-small-en-us-0.15/  # Bundled offline speech model
```

---

## Prerequisites

- Python 3.8 or newer
- A working microphone
- **Windows only:** [Microsoft Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (required if any audio packages need to compile from source)

---

## Installation

```bash
python -m pip install -r requirements.txt
```

**Python dependencies:**
- `pygame` — audio mixing and playback
- `vosk` — offline speech recognition
- `sounddevice` — microphone input (PortAudio-based)
- `PyYAML` — config file parsing
- `numpy` — audio data handling
- `SpeechRecognition` — alternative speech backend (CLI mode)
- `customtkinter` — modern GUI framework
- `darkdetect` — OS dark/light theme detection

### PyAudio (optional, Windows)

Some microphone backends require PyAudio. The easiest install methods on Windows:

```bash
pip install pipwin
pipwin install pyaudio
```

Or download a prebuilt wheel matching your Python version from https://www.lfd.uci.edu/~gohlke/pythonlibs/ and install with `pip install <wheel-file>`.

### PortAudio

`sounddevice` depends on PortAudio. The pip wheel for Windows normally bundles the required binaries. If you encounter errors, install Visual C++ Build Tools and retry.

---

## Running the App

### GUI Mode (recommended)

```bash
python gui_main.py
```

Opens a modern dark-themed window with a sidebar to switch between the **Keyword Editor** and **Soundboard** views. Includes a theme selector (Dark / Light / System).

### CLI Mode

```bash
python main.py
```

Runs in the terminal only. Listens for keywords and plays sounds based on `config/sound_config.yaml`. No soundboard, no GUI. Press `Ctrl+C` to quit.

---

## Configuration

### Keyword Mappings — `config/sound_config.yaml`

Maps spoken keywords to sound files and volumes. Over 100 fantasy-themed entries are included out of the box (sword clashes, fireballs, roars, healing chimes, thunder, and more).

```yaml
sword clash:
  filename: sounds/sword-clash-241729.mp3
  volume: 0.8

fireball:
  filename: sounds/fireball.mp3
  volume: 1.0
```

Edit this file directly or use the **Keyword Editor** in the GUI.

### Key Bindings — `config/soundboard_config.yaml`

Maps keyboard keys to sounds for manual triggering in the Soundboard view.

```yaml
a:
  sound_name: attack hit
  filename: sounds/hit.mp3

c:
  sound_name: counterspell
  filename: sounds/counterspell.mp3
```

Managed through the **Soundboard** tab's "Add Binding" dialog.

---

## Vosk Speech Model

The small English model (`vosk-model-small-en-us-0.15`) is included in this repository. It is used by the GUI soundboard's live listening mode.

To use a different language or a larger/more accurate model:
1. Download a model from https://alphacephei.com/vosk/models
2. Extract it under `vosk-model-small-en-us-0.15/` or update the model path in `gui/soundboard_view.py`

---

## Quick Start

```bash
python -m pip install -r requirements.txt
python gui_main.py
```

1. Open the **Soundboard** tab and click **Start Listening**
2. Speak a keyword (e.g., *"sword clash"*) — the matching card flashes and the sound plays
3. Press a bound key (e.g., `A`) to trigger a sound manually
4. Open the **Keywords** tab to add or edit mappings and preview sounds
