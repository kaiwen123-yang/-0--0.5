"""Closed-loop evaluation. No teacher IK, object poses or scripted rescue actions."""
import argparse
import json
import os
from pathlib import Path
import time

import imageio.v2 as imageio
import jax
import numpy as np
from openpi.policies import policy_config as upstream_policy
from openpi.shared import normalize
from policy_config import ASSET_ID, DATA, RUN, make_config
from sim import COLORS, ColorEnv, HZ


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["base", "lora", "full"], required=True)
    p.add_argument("--split", choices=["validation", "test"], default="test")
    p.add_argument("--steps", type=int, default=420)
    p.add_argument("--limit-layouts", type=int)
    a = p.parse_args()
    cfg = make_config(a.mode)
    if a.mode == "base":
        checkpoint = Path(os.environ["PIPER_BASE_PARAMS"]).parent
    else:
        checkpoint = Path(json.loads((RUN / f"{a.mode}_training.json").read_text())["checkpoint"])
    policy = upstream_policy.create_trained_policy(cfg, checkpoint,
                    norm_stats=normalize.load(RUN / "assets" / ASSET_ID), sample_kwargs={"num_steps":10})
    # Same sampling RNG seed for paired models; actual action counts can differ.
    policy._rng = jax.random.key(42)
    manifest = json.loads((DATA / "manifest.json").read_text())
    seeds = manifest["split_seeds"][a.split]
    if a.limit_layouts:
        seeds = seeds[:a.limit_layouts]
    directory = RUN / "evaluations" / f"{a.mode}_{a.split}"
    directory.mkdir(exist_ok=True, parents=True)
    env = ColorEnv(render=True)
    results = []
    try:
        for seed in seeds:
            for color in COLORS:
                env.reset(seed, color)
                stem = directory / f"layout_{seed:05d}_{color}"
                writer = imageio.get_writer(str(stem.with_suffix(".mp4")), fps=HZ, codec="libx264", quality=7, macro_block_size=1)
                latencies, commands, states = [], [], []
                consecutive, stable, error = 0, False, None
                try:
                    for step in range(0, a.steps, 5):
                        obs = env.observe()
                        started = time.monotonic()
                        actions = np.asarray(policy.infer(obs)["actions"])
                        latencies.append(time.monotonic()-started)
                        if actions.shape != (10,7) or not np.isfinite(actions).all():
                            raise RuntimeError(f"Invalid action chunk {actions.shape}")
                        for action in actions[:5]:
                            writer.append_data(env.panorama())
                            states.append(env.state())
                            commands.append(env.step(action))
                            success = env.result()["success"]
                            consecutive = consecutive+1 if success else 0
                            if consecutive >= 40:
                                stable = True
                                break
                            if env.max_joint_violation > .02:
                                raise RuntimeError("Measured joint limit overshoot > 0.02 rad")
                        if stable:
                            break
                except Exception as exc:
                    error = repr(exc)
                finally:
                    writer.close()
                result = env.result()
                result.update(success=bool(stable and error is None), stable_2s=stable, error=error,
                              mode=a.mode, split=a.split, checkpoint=str(checkpoint),
                              video=str(stem.with_suffix(".mp4")), hardware_execution=False,
                              privileged_policy_input=False, scripted_rescue=False,
                              inference_seconds=latencies,
                              inference_median_excluding_first=float(np.median(latencies[1:])) if len(latencies)>1 else None,
                              physics_clock="paused_while_policy_computes; not a wall-clock real-time validation")
                stem.with_suffix(".json").write_text(json.dumps(result, indent=2))
                np.savez_compressed(stem.with_suffix(".npz"), state=np.asarray(states), executed_command=np.asarray(commands))
                results.append(result)
                summary = dict(mode=a.mode, split=a.split, successes=sum(r["success"] for r in results),
                               total=len(results), success_rate=np.mean([r["success"] for r in results]),
                               domain="simulation", hardware_validated=False, episodes=results)
                (directory / "summary.json").write_text(json.dumps(summary, indent=2))
                print(a.mode, a.split, seed, color, result["success"], error, flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    main()
