import time
import threading
from pygame import mixer

class VolumeController:
    def __init__(self, config: dict):
        self.config = config
        self.target_volume = 1.0
        self.current_volume = 1.0
        self._running = False

    def fade_volume(self, target: float, duration: float = 1.0):
        self.target_volume = target
        steps = duration / self.config['volume_shift']['interval']
        step_size = (target - self.current_volume) / steps
        
        self._running = True
        threading.Thread(target=self._volume_adjuster, args=(step_size)).start()

    def _volume_adjuster(self, step_size: float):
        while self._running and abs(self.current_volume - self.target_volume) > 0.01:
            self.current_volume += step_size
            mixer.music.set_volume(self.current_volume)
            time.sleep(self.config['volume_shift']['interval'])
        self._running = False