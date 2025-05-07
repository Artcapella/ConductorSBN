import speech_recognition as sr
from typing import Callable

class SpeechHandler:
    def __init__(self, callback: Callable[[str], None]):
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.callback = callback
        self._running = False

    def start_listening(self):
        self._running = True
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source)
        self._listen_loop()

    def _listen_loop(self):
        while self._running:
            try:
                with self.microphone as source:
                    audio = self.recognizer.listen(source, timeout=2)
                text = self.recognizer.recognize_google(audio).lower()
                self.callback(text)
            except sr.UnknownValueError:
                pass
            except Exception as e:
                print(f"Speech recognition error: {e}")

    def stop_listening(self):
        self._running = False