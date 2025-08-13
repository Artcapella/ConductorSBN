from pygame import mixer
import vosk
import sys
import sounddevice as sd
import json
import yaml
import os
from threading import Thread
import ctypes
import numpy as np
import array

class SoundManager:
    def __init__(self, config_path):
        mixer.init()
        self.global_volume = 1.0
        self.sounds = {}
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
            
        for name, params in config['sound_triggers'].items():
            sound = mixer.Sound(os.path.join("sounds", params['file']))
            sound.set_volume(params['volume'])
            self.sounds[name] = (sound, params['volume'])

    def adjust_volume(self, delta):
        self.global_volume = max(0.0, min(2.0, self.global_volume + delta))
        print(f"Volume now: {self.global_volume*100:.0f}%")

    def play(self, trigger):
        if trigger in self.sounds:
            sound, base_vol = self.sounds[trigger]
            sound.set_volume(base_vol * self.global_volume)
            Thread(target=sound.play).start()

class AudioReactApp:
    def __init__(self, config_path):
        self.sm = SoundManager(config_path)
        
        # Vosk setup
        model_path = "C:/Users/clair/OneDrive/Documents/GitHub/ConductorSBN/vosk-model-small-en-us-0.15/vosk-model-small-en-us-0.15"
        if not os.path.exists(model_path):
            raise FileNotFoundError("Vosk model not found")
        
        self.model = vosk.Model(model_path)
        self.sample_rate = 16000
        self.device_info = sd.query_devices(None, 'input')
        self._played_triggers = set()  # Track played triggers for current phrase

    def process_phrase(self, text, is_partial=False):
        text = text.lower()
        if "louder" in text and (not is_partial):
            self.sm.adjust_volume(0.1)
        elif "softer" in text and (not is_partial):
            self.sm.adjust_volume(-0.1)
        else:
            for trigger in self.sm.sounds:
                if trigger in text and trigger not in self._played_triggers:
                    self.sm.play(trigger)
                    self._played_triggers.add(trigger)

    def run(self):
        with sd.RawInputStream(samplerate=self.sample_rate, blocksize=4000,
                             dtype='int16', channels=1) as stream:
            
            rec = vosk.KaldiRecognizer(self.model, self.sample_rate)
            print("Listening... (speak clearly and wait for sound feedback)")
            
            while True:
                data, _ = stream.read(4000)
                data_bytes = data[:]  # Slicing buffer returns bytes
                if len(data_bytes) == 0: break
                
                if rec.AcceptWaveform(data_bytes):
                    result = json.loads(rec.Result())
                    self.process_phrase(result.get('text', ''), is_partial=False)
                    self._played_triggers.clear()  # Reset after final result
                
                # Process partial results
                partial = json.loads(rec.PartialResult())
                partial_text = partial.get('partial', '')
                if partial_text and len(partial_text) > 0:
                    self.process_phrase(partial_text, is_partial=True)

if __name__ == "__main__":
    app = AudioReactApp("config/sound_config.yaml")
    try:
        app.run()
    except KeyboardInterrupt:
        sys.exit()