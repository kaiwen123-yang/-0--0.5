"""Deterministic, layout-disjoint synthetic demonstrations with failure audit."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from sim import COLORS, ColorEnv, teacher


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--record", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    splits = {"preflight": list(range(4))} if args.preflight else {
        "train": list(range(100, 140)), "validation": list(range(1000, 1005)), "test": list(range(2000, 2010))}
    manifest = dict(task="piper_h_color_pick_v1", data_source="synthetic_scripted_ik", hardware_execution=False,
                    fps=20, split_unit="layout_seed_including_all_color_prompts", split_seeds=splits,
                    action="commanded_absolute_joint_radians_6_and_gripper_opening_metres_1", episodes=[])
    env = ColorEnv(render=args.record)
    started = time.monotonic()
    try:
        for split, seeds in splits.items():
            for seed in seeds:
                for color in COLORS:
                    stem = args.output / split / f"layout_{seed:05d}_{color}"
                    stem.parent.mkdir(parents=True, exist_ok=True)
                    env.reset(seed, color)
                    # Save panorama for every preflight, and first layout per split.
                    video = stem.with_suffix(".mp4") if args.record and seed == seeds[0] else None
                    try:
                        result = teacher(env, stem.with_suffix(".npz") if args.record else None, video)
                    except Exception as exc:
                        result = dict(layout_seed=seed, target=color, success=False, error=repr(exc))
                    result.update(split=split, file=str(stem.relative_to(args.output).with_suffix(".npz")),
                                  video=str(video.relative_to(args.output)) if video else None)
                    if args.record and stem.with_suffix(".npz").exists():
                        result["sha256"] = hashlib.sha256(stem.with_suffix(".npz").read_bytes()).hexdigest()
                    manifest["episodes"].append(result)
                    manifest["elapsed_seconds"] = time.monotonic()-started
                    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
                    print(split, seed, color, "SUCCESS" if result["success"] else result, flush=True)
    finally:
        env.close()
    failures = [e for e in manifest["episodes"] if not e["success"]]
    print(json.dumps({"episodes": len(manifest["episodes"]), "failures": len(failures), "seconds": time.monotonic()-started}), flush=True)
    if failures:
        raise SystemExit("Teacher precondition failed; do not start training silently with failed demonstrations.")


if __name__ == "__main__":
    main()
