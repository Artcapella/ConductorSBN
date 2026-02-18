# ConductorSBN

Minimal instructions and dependency list for ConductorSBN.

**Prerequisites**
- Python 3.8 or newer
- Windows: Microsoft Visual C++ Build Tools (if compiling audio-related packages)

**Python dependencies**
The project uses the following Python packages:
- pygame
- vosk
- sounddevice
- PyYAML
- numpy
- SpeechRecognition

Install them with:

```bash
python -m pip install -r requirements.txt
```

If you need to install `PyAudio` (used by some microphone backends for `SpeechRecognition`) on Windows, the easiest methods are:

```bash
pip install pipwin
pipwin install pyaudio
```

or download a prebuilt wheel matching your Python version from https://www.lfd.uci.edu/~gohlke/pythonlibs/ and install with `pip install <wheel-file>`.

**System audio / PortAudio**
- `sounddevice` relies on PortAudio. On Windows the pip wheel normally bundles the required binaries; if you encounter build errors, install the Visual C++ Build Tools and then retry.

**Vosk speech model**
This repository expects a Vosk model in `vosk-model-small-en-us-0.15/` (included in the repo under `vosk-model-small-en-us-0.15/vosk-model-small-en-us-0.15/`). If you need a model or a different language, download from https://alphacephei.com/vosk/models and place it under `vosk-model-small-en-us-0.15/` or update `main.py` to point to your model path.

**Notes**
- The project uses `pygame.mixer` for audio playback.
- If you use a different microphone backend, ensure its dependencies are installed (e.g., `pyaudio`).

**Quick start**

```bash
python -m pip install -r requirements.txt
python main.py
```
