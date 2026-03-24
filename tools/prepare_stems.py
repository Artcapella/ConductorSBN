"""
Stem preparation utility for ConductorSBN adaptive mixer.

Run standalone to:
1. Verify all stems in a scene have matching sample rate, channels, and duration
2. Normalize/pad stems to match
3. Run Demucs on a full track to extract stems (optional)

Usage:
    python tools/prepare_stems.py verify assets/music/scenes/enchanted_forest/
    python tools/prepare_stems.py normalize assets/music/scenes/enchanted_forest/ --sr 44100
    python tools/prepare_stems.py split input_track.mp3 --output assets/music/scenes/new_scene/
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def verify_scene(scene_dir: str):
    """Check that all stems in a scene have matching properties."""
    scene_path = Path(scene_dir)
    config_path = scene_path / "scene.json"

    if not config_path.exists():
        print(f"ERROR: No scene.json in {scene_dir}")
        return False

    with open(config_path, "r") as f:
        config = json.load(f)

    print(f"Verifying scene: {config.get('name', scene_dir)}")
    issues = []
    properties = {}

    for stem_id, stem_config in config.get("stems", {}).items():
        file_path = scene_path / stem_config["file"]
        if not file_path.exists():
            issues.append(f"  MISSING: {stem_config['file']}")
            continue

        info = sf.info(str(file_path))
        props = {
            "samplerate": info.samplerate,
            "channels": info.channels,
            "frames": info.frames,
            "duration": info.duration,
            "format": info.format,
            "subtype": info.subtype,
        }
        properties[stem_id] = props
        print(f"  {stem_id}: {info.samplerate}Hz, {info.channels}ch, "
              f"{info.duration:.1f}s, {info.subtype}")

    if not properties:
        print("No stems found!")
        return False

    srs = set(p["samplerate"] for p in properties.values())
    chs = set(p["channels"] for p in properties.values())
    durs = set(round(p["duration"], 1) for p in properties.values())

    if len(srs) > 1:
        issues.append(f"  MISMATCH sample rates: {srs}")
    if len(chs) > 1:
        issues.append(f"  MISMATCH channel counts: {chs}")
    if len(durs) > 1:
        issues.append(f"  MISMATCH durations: {durs} "
                      f"(shortest: {min(p['duration'] for p in properties.values()):.1f}s, "
                      f"longest: {max(p['duration'] for p in properties.values()):.1f}s)")

    if issues:
        print("\nISSUES FOUND:")
        for issue in issues:
            print(issue)
        return False
    else:
        print("\nAll stems OK!")
        return True


def normalize_scene(scene_dir: str, target_sr: int = 44100, target_channels: int = 2):
    """Convert all stems to matching sample rate, channels, and pad to same duration."""
    scene_path = Path(scene_dir)
    config_path = scene_path / "scene.json"

    with open(config_path, "r") as f:
        config = json.load(f)

    print(f"Normalizing scene: {config.get('name', scene_dir)}")

    # First pass: find max duration
    max_duration = 0
    for stem_config in config.get("stems", {}).values():
        file_path = scene_path / stem_config["file"]
        if file_path.exists():
            info = sf.info(str(file_path))
            max_duration = max(max_duration, info.duration)

    target_frames = int(max_duration * target_sr)
    print(f"Target: {target_sr}Hz, {target_channels}ch, {max_duration:.1f}s ({target_frames} frames)")

    for stem_id, stem_config in config.get("stems", {}).items():
        file_path = scene_path / stem_config["file"]
        if not file_path.exists():
            continue

        data, sr = sf.read(str(file_path), dtype="float32", always_2d=True)
        changed = False

        if sr != target_sr:
            print(f"  {stem_id}: Resampling {sr} -> {target_sr} Hz")
            ratio = target_sr / sr
            new_length = int(data.shape[0] * ratio)
            indices = np.linspace(0, data.shape[0] - 1, new_length)
            new_data = np.zeros((new_length, data.shape[1]), dtype=np.float32)
            for ch in range(data.shape[1]):
                new_data[:, ch] = np.interp(indices, np.arange(data.shape[0]), data[:, ch])
            data = new_data
            changed = True

        if data.shape[1] != target_channels:
            print(f"  {stem_id}: Converting {data.shape[1]}ch -> {target_channels}ch")
            if data.shape[1] == 1 and target_channels == 2:
                data = np.column_stack([data[:, 0], data[:, 0]])
            elif data.shape[1] == 2 and target_channels == 1:
                data = np.mean(data, axis=1, keepdims=True)
            changed = True

        if data.shape[0] != target_frames:
            if data.shape[0] < target_frames:
                print(f"  {stem_id}: Padding {data.shape[0]} -> {target_frames} frames")
                pad = np.zeros((target_frames - data.shape[0], target_channels), dtype=np.float32)
                data = np.vstack([data, pad])
            else:
                print(f"  {stem_id}: Trimming {data.shape[0]} -> {target_frames} frames")
                data = data[:target_frames]
            changed = True

        if changed:
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            if not backup_path.exists():
                file_path.rename(backup_path)
            sf.write(str(file_path), data, target_sr, subtype="PCM_16")
            print(f"  {stem_id}: Saved (backup: {backup_path.name})")
        else:
            print(f"  {stem_id}: No changes needed")


def split_with_demucs(input_file: str, output_dir: str, model: str = "htdemucs_ft"):
    """Run Demucs stem separation on an input audio file."""
    try:
        import demucs.separate
    except ImportError:
        print("ERROR: Demucs not installed. Install with: pip install demucs")
        sys.exit(1)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Running Demucs ({model}) on {input_file}...")
    args = [
        "--name", model,
        "--out", str(output_path / "demucs_output"),
        "--mp3",
        input_file,
    ]
    demucs.separate.main(args)
    print(f"Stems saved to {output_path / 'demucs_output'}")
    print("Next: create scene.json and rename stems to match the schema.")


def create_test_scene(output_dir: str, bpm: float = 120.0, duration: float = 16.0):
    """Generate a test scene with synthesized tones for development/testing."""
    import os
    scene_path = Path(output_dir)
    scene_path.mkdir(parents=True, exist_ok=True)

    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)

    # Simple synthesized stems
    stems_data = {
        "base_pad": np.sin(2 * np.pi * 110 * t) * 0.3,
        "peaceful_melody": (
            np.sin(2 * np.pi * 440 * t) * 0.2
            * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t))
        ),
        "tension_strings": np.sin(2 * np.pi * 233 * t) * 0.25,
        "combat_percussion": (
            np.sign(np.sin(2 * np.pi * 2 * t)) * 0.4
            * np.clip(np.random.rand(len(t)) + 0.5, 0, 1)
        ),
        "combat_brass": np.sin(2 * np.pi * 330 * t) * 0.3 * np.clip(
            np.sin(2 * np.pi * 1.0 * t), 0, 1
        ),
    }

    config = {
        "name": "Test Scene",
        "bpm": bpm,
        "key": "Am",
        "time_signature": [4, 4],
        "stems": {
            "base_pad": {
                "file": "base_pad.wav",
                "layer": "base",
                "default_volume": 0.5,
                "always_on": True,
                "description": "Low drone foundation"
            },
            "peaceful_melody": {
                "file": "peaceful_melody.wav",
                "layer": "peaceful",
                "default_volume": 0.4,
                "always_on": False,
                "description": "Tremolo melody"
            },
            "tension_strings": {
                "file": "tension_strings.wav",
                "layer": "tension",
                "default_volume": 0.45,
                "always_on": False,
                "description": "Dissonant strings"
            },
            "combat_percussion": {
                "file": "combat_percussion.wav",
                "layer": "combat",
                "default_volume": 0.6,
                "always_on": False,
                "description": "Rhythmic pulse"
            },
            "combat_brass": {
                "file": "combat_brass.wav",
                "layer": "combat",
                "default_volume": 0.5,
                "always_on": False,
                "description": "Brass stabs"
            },
        },
        "layer_groups": {
            "base": {"stems": ["base_pad"], "intensity": 0},
            "peaceful": {"stems": ["peaceful_melody"], "intensity": 1},
            "tension": {"stems": ["tension_strings"], "intensity": 2},
            "combat": {"stems": ["combat_percussion", "combat_brass"], "intensity": 3},
        }
    }

    for name, audio in stems_data.items():
        stereo = np.column_stack([audio, audio]).astype(np.float32)
        out_path = scene_path / f"{name}.wav"
        sf.write(str(out_path), stereo, sr, subtype="PCM_16")
        print(f"  Generated: {out_path.name}")

    config_path = scene_path / "scene.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"Test scene created at: {scene_path}")
    return str(scene_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stem preparation utility for ConductorSBN")
    sub = parser.add_subparsers(dest="command")

    verify_p = sub.add_parser("verify", help="Verify scene stems consistency")
    verify_p.add_argument("scene_dir")

    norm_p = sub.add_parser("normalize", help="Normalize stems to match properties")
    norm_p.add_argument("scene_dir")
    norm_p.add_argument("--sr", type=int, default=44100)
    norm_p.add_argument("--channels", type=int, default=2)

    split_p = sub.add_parser("split", help="Split a track with Demucs")
    split_p.add_argument("input_file")
    split_p.add_argument("--output", default="assets/music/scenes/new_scene/")
    split_p.add_argument("--model", default="htdemucs_ft")

    test_p = sub.add_parser("create-test", help="Generate a test scene with synthesized tones")
    test_p.add_argument("--output", default="assets/music/scenes/test_scene/")
    test_p.add_argument("--bpm", type=float, default=120.0)
    test_p.add_argument("--duration", type=float, default=16.0)

    args = parser.parse_args()

    if args.command == "verify":
        verify_scene(args.scene_dir)
    elif args.command == "normalize":
        normalize_scene(args.scene_dir, args.sr, args.channels)
    elif args.command == "split":
        split_with_demucs(args.input_file, args.output, args.model)
    elif args.command == "create-test":
        create_test_scene(args.output, args.bpm, args.duration)
    else:
        parser.print_help()
