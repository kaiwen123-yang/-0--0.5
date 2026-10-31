"""Freeze v2, verify six teacher replays, then regenerate train-only RGB data."""
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from dataset import prepare
from sim import COLORS, HALF, teacher
from sim_v2 import ColorEnvV2, freeze

RUN = Path(os.environ["PIPER_COLOR_RUN"])


def save(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2))
    temp.replace(path)


def main():
    version = freeze(RUN)
    data = RUN / "dataset"
    data.mkdir(exist_ok=False)
    manifest = dict(task=version["version"], scene_sha256=version["scene_sha256"],
                    data_source="fresh_scripted_ik_v2", fps=20, hardware_execution=False,
                    split_unit="layout_seed_including_all_color_prompts",
                    split_seeds={"train": list(range(100, 140)),
                                 "validation": list(range(1000, 1005)), "test": list(range(2000, 2010))},
                    generated_splits=["train"], episodes=[])
    started = time.monotonic()
    controls = []
    env = ColorEnvV2(render=True)
    try:
        for layout in range(100, 140):
            for color in COLORS:
                env.reset(layout, color)
                stem = data / "train" / f"layout_{layout:05d}_{color}"
                stem.parent.mkdir(exist_ok=True)
                video = stem.with_suffix(".mp4") if layout in (100, 101) else None
                t0 = time.monotonic()
                result = teacher(env, stem.with_suffix(".npz"), video)
                result.update(split="train", file=str(stem.with_suffix(".npz").relative_to(data)),
                              sha256=hashlib.sha256(stem.with_suffix(".npz").read_bytes()).hexdigest(),
                              elapsed_seconds=time.monotonic() - t0)
                manifest["episodes"].append(result)
                manifest["elapsed_seconds"] = time.monotonic() - started
                save(data / "manifest.json", manifest)
                print("DEMONSTRATION " + json.dumps(result), flush=True)
                if not result["success"]:
                    raise RuntimeError(f"Teacher task failed: {layout}/{color}")
                if layout in (100, 101):
                    with np.load(stem.with_suffix(".npz"), allow_pickle=False) as archive:
                        commands = archive["executed_command"].copy()
                        stages = archive["stage"].copy()
                    env.reset(layout, color)
                    for command in commands:
                        env.step(command)
                    stable = []
                    for _ in range(40):
                        env.step(env.command)
                        stable.append(env.result()["success"])
                    env.reset(layout, color)
                    end_lift = int(np.flatnonzero(stages == "lift")[-1]) + 1
                    for command in commands[:end_lift]:
                        env.step(command)
                    hold = np.r_[env.state()[:6], 0.]
                    heights, positions, states = [], [], []
                    for _ in range(200):
                        env.step(hold)
                        positions.append(env.positions()[color])
                        heights.append(float(positions[-1][2] - HALF))
                        states.append(env.state())
                    control = {"layout": layout, "target": color, "full_replay_success": all(stable),
                               "hold_seconds": 10, "minimum_hold_height_m": min(heights),
                               "final_hold_height_m": heights[-1], "held_5cm": min(heights) > .05,
                               "teacher_control_only": True}
                    controls.append(control)
                    np.savez_compressed(stem.with_name(stem.name + "_hold_control.npz"),
                                        state=states, object_position=positions, height=heights, hold_command=hold)
                    save(RUN / "teacher_controls.json", {"episodes": controls,
                         "complete": len(controls) == 6,
                         "all_passed": all(c["full_replay_success"] and c["held_5cm"] for c in controls)})
                    if not control["full_replay_success"] or not control["held_5cm"]:
                        raise RuntimeError(f"Frozen-v2 teacher control failed: {control}")
                if len(manifest["episodes"]) % 6 == 0:
                    save(RUN / "data_progress.json", {"episodes": len(manifest["episodes"]),
                         "total": 120, "elapsed_seconds": time.monotonic() - started,
                         "mean_seconds_per_episode": (time.monotonic() - started) / len(manifest["episodes"])})
    finally:
        env.close()
    if len(manifest["episodes"]) != 120:
        raise ValueError("Expected all 120 training demonstrations")
    prepare(data)
    audit = json.loads((data / "audit.json").read_text())
    if audit["frames"] != 32160 or audit["splits"]["train"] != 120:
        raise ValueError(f"Actual dataset differs from fixed training budget: {audit}")
    save(RUN / "data_complete.json", {**audit, "scene_sha256": version["scene_sha256"],
         "manifest_sha256": hashlib.sha256((data / "manifest.json").read_bytes()).hexdigest(),
         "heldout_demonstrations_generated_or_read": False, "elapsed_seconds": time.monotonic() - started})


if __name__ == "__main__":
    main()
