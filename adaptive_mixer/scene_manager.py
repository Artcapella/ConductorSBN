"""
SceneManager — Discovers and manages available scene packs.
"""

import json
from pathlib import Path
from typing import Optional


class SceneManager:
    def __init__(self, scenes_dir: str = "assets/music/scenes"):
        self._scenes_dir = Path(scenes_dir)
        self._scenes: dict = {}  # scene_id -> {"path": ..., "config": ..., "name": ...}
        self.scan()

    def scan(self):
        """Scan the scenes directory for valid scene packs."""
        self._scenes.clear()
        if not self._scenes_dir.exists():
            return

        for scene_dir in sorted(self._scenes_dir.iterdir()):
            if scene_dir.is_dir():
                config_path = scene_dir / "scene.json"
                if config_path.exists():
                    try:
                        with open(config_path, "r") as f:
                            config = json.load(f)
                        scene_id = scene_dir.name
                        self._scenes[scene_id] = {
                            "path": str(scene_dir),
                            "config": config,
                            "name": config.get("name", scene_id),
                        }
                    except Exception as e:
                        print(f"[SceneManager] Warning: Invalid scene config in {scene_dir}: {e}")

        print(f"[SceneManager] Found {len(self._scenes)} scene(s): "
              f"{[s['name'] for s in self._scenes.values()]}")

    def get_scene_list(self) -> list:
        """Return list of available scenes with id, name, path."""
        return [
            {"id": sid, "name": s["name"], "path": s["path"]}
            for sid, s in self._scenes.items()
        ]

    def get_scene_paths(self) -> list:
        """Return list of scene directory paths."""
        return [s["path"] for s in self._scenes.values()]

    def get_scene_path(self, scene_id: str) -> Optional[str]:
        if scene_id in self._scenes:
            return self._scenes[scene_id]["path"]
        return None

    def get_scene_count(self) -> int:
        return len(self._scenes)
