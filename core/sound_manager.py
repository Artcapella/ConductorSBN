from pygame import mixer
import threading
import yaml
import os
from threading import Thread

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