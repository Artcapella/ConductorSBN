from core.speech_processor import SpeechHandler
from core.sound_manager import SoundManager
from core.volume_controller import VolumeController
import yaml

class AudioReactApp:
    def __init__(self):
        with open("config/sound_config.yaml") as f:
            self.config = yaml.safe_load(f)
        
        self.sound_manager = SoundManager("config/sound_config.yaml")
        self.volume_controller = VolumeController(self.config)
        self.speech_handler = SpeechHandler(self._on_phrase_detected)

    def _on_phrase_detected(self, phrase: str):
        # Feature 1: Print detected inputs
        print(f"Detected: {phrase}")

        # Feature 2: Handle volume commands
        if "louder" in phrase:
            self.sound_manager.increase_volume()
            print(f"Global volume increased to {self.sound_manager.global_volume}")
        elif "softer" in phrase:
            self.sound_manager.decrease_volume()
            print(f"Global volume decreased to {self.sound_manager.global_volume}")

        # Check for sound triggers
        for trigger in self.config['sound_triggers']:
            if trigger in phrase:
                self.sound_manager.play_sound(trigger)

    def run(self):
        print("Starting real-time listener...")
        self.speech_handler.start_listening()
        
        try:
            # Keep main thread alive while processing
            while True:
                input("Press Enter to stop...\n")
                break
        except KeyboardInterrupt:
            pass
        finally:
            self.speech_handler.stop()
            print("\nStopped listening")

if __name__ == "__main__":
    app = AudioReactApp()
    app.run()