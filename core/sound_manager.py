from pygame import mixer
import threading
import yaml
import os

class SoundManager:
    def __init__(self, config_path: str):
        mixer.init()
        self.sounds = {}
        self.original_volumes = {}
        self.global_volume = 1.0
        self._load_config(config_path)

    def _load_config(self, config_path: str):
        with open(config_path) as f:
            config = yaml.safe_load(f)
        self.sound_triggers = config['sound_triggers']
        self.volume_step = config['volume_shift']['step']

        # Preload sounds with initial volume
        for trigger, params in self.sound_triggers.items():
            sound_path = os.path.join("sounds", params['file'])
            if not os.path.exists(sound_path):
                raise FileNotFoundError(f"Sound file {sound_path} not found")
            sound = mixer.Sound(sound_path)
            self.original_volumes[trigger] = params['volume']
            sound.set_volume(params['volume'] * self.global_volume)
            self.sounds[trigger] = sound

    def increase_volume(self):
        self.global_volume = min(2.0, self.global_volume + self.volume_step)
        self._update_all_volumes()

    def decrease_volume(self):
        self.global_volume = max(0.0, self.global_volume - self.volume_step)
        self._update_all_volumes()

    def _update_all_volumes(self):
        for trigger, sound in self.sounds.items():
            base_volume = self.original_volumes[trigger]
            sound.set_volume(base_volume * self.global_volume)

    def play_sound(self, trigger: str):
        if trigger in self.sound_triggers:
            def _play():
                # Use preloaded sound and current volume
                sound = self.sounds[trigger]
                sound.play()
            threading.Thread(target=_play).start()