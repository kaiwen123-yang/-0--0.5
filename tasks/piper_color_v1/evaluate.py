"""Closed-loop evaluation. No teacher IK, object poses or scripted rescue actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import imageio.v2 as imageio
import numpy as np
from sim import COLORS, ColorEnv, HZ

HERE = Path(__file__).resolve().parent
RUN = Path(os.environ.get("PIPER_COLOR_RUN", HERE / "run"))
DATA = Path(os.environ.get("PIPER_COLOR_DATA", RUN / "dataset"))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["base", "lora", "full"], required=True)
    p.add_argument("--split", choices=["train", "validation", "test"], default="test")
    p.add_argument("--steps", type=int, default=420)
    p.add_argument("--limit-layouts", type=int)
    p.add_argument("--layout-seeds", type=int, nargs="+")
    p.add_argument("--targets", choices=COLORS, nargs="+", default=list(COLORS))
    p.add_argument("--replan-steps", type=int, choices=range(1, 11), default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data", type=Path, default=DATA)
    p.add_argument("--output", type=Path)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--norm-stats", type=Path)
    p.add_argument("--policy-host")
    p.add_argument("--policy-port", type=int, default=18765)
    p.add_argument("--no-video", action="store_true")
    a = p.parse_args()
    if a.steps <= 0 or (a.limit_layouts is not None and a.limit_layouts <= 0):
        p.error("steps and limit-layouts must be positive")
    if a.policy_host:
        from policy_client import PolicyClient
        policy = PolicyClient(a.policy_host, a.policy_port)
        metadata = policy.metadata
        if metadata["mode"] != a.mode:
            raise ValueError("Server mode differs from requested evaluation")
        checkpoint = Path(metadata["checkpoint"])
        if a.checkpoint and checkpoint.resolve() != a.checkpoint.resolve():
            raise ValueError("Server checkpoint differs from requested evaluation")
        if a.norm_stats and metadata["norm_stats"] != str(a.norm_stats.resolve()):
            raise ValueError("Server normalization differs from requested evaluation")
        policy.reset_seed(a.seed)
    else:
        import jax
        from openpi.policies import policy_config as upstream_policy
        from openpi.shared import normalize
        from policy_config import ASSET_ID, make_config
        cfg = make_config(a.mode)
        if a.checkpoint:
            checkpoint = a.checkpoint
        elif a.mode == "base":
            checkpoint = Path(os.environ["PIPER_BASE_PARAMS"]).parent
        else:
            checkpoint = Path(json.loads((RUN / f"{a.mode}_training.json").read_text())["checkpoint"])
        norm = a.norm_stats or RUN / "assets" / ASSET_ID
        policy = upstream_policy.create_trained_policy(cfg, checkpoint,
                        norm_stats=normalize.load(norm), sample_kwargs={"num_steps":10})
        policy._rng = jax.random.key(a.seed)
        metadata = {"checkpoint": str(checkpoint), "norm_stats": str(norm), "mode": a.mode}
    manifest = json.loads((a.data / "manifest.json").read_text())
    seeds = manifest["split_seeds"][a.split]
    if a.layout_seeds is not None:
        if not set(a.layout_seeds) <= set(seeds):
            p.error("Selected layout is outside the declared split")
        seeds = a.layout_seeds
    if a.limit_layouts:
        seeds = seeds[:a.limit_layouts]
    directory = a.output or RUN / "evaluations" / f"{a.mode}_{a.split}"
    directory.mkdir(exist_ok=False, parents=True)
    protocol = dict(mode=a.mode, split=a.split, layout_seeds=seeds, targets=a.targets,
                    max_steps=a.steps, replan_steps=a.replan_steps, seed=a.seed, policy=metadata,
                    policy_transport="websocket" if a.policy_host else "in_process",
                    dataset_manifest_sha256=hashlib.sha256((a.data / "manifest.json").read_bytes()).hexdigest(),
                    source_sha256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                   for name in ("evaluate.py", "sim.py", "policy_config.py", "serve.py", "policy_client.py")},
                    expected_episodes=len(seeds)*len(a.targets), hardware_execution=False)
    (directory / "protocol.json").write_text(json.dumps(protocol, indent=2))
    env = ColorEnv(render=True)
    results = []
    started_run = time.monotonic()
    try:
        for seed in seeds:
            for color in a.targets:
                env.reset(seed, color)
                stem = directory / f"layout_{seed:05d}_{color}"
                writer = None if a.no_video else imageio.get_writer(str(stem.with_suffix(".mp4")), fps=HZ, codec="libx264", quality=7, macro_block_size=1, output_params=["-threads", "2"])
                latencies, commands, states = [], [], []
                raw_actions, chunks, chunk_states, qpos, qvel, positions, tcp, states_after = [], [], [], [], [], [], [], []
                consecutive, stable, error = 0, False, None
                try:
                    for step in range(0, a.steps, a.replan_steps):
                        obs = env.observe()
                        started = time.monotonic()
                        actions = np.asarray(policy.infer(obs)["actions"])
                        latencies.append(time.monotonic()-started)
                        if actions.shape != (10,7) or not np.isfinite(actions).all():
                            raise RuntimeError(f"Invalid action chunk {actions.shape}")
                        chunks.append(actions.copy())
                        chunk_states.append(obs["state"].copy())
                        for action in actions[:min(a.replan_steps, a.steps-step)]:
                            if writer:
                                writer.append_data(env.panorama())
                            states.append(env.state())
                            qpos.append(env.data.qpos.copy())
                            qvel.append(env.data.qvel.copy())
                            positions.append(np.stack([env.positions()[c] for c in COLORS]))
                            tcp.append(env.data.site_xpos[env.site].copy())
                            raw_actions.append(action.copy())
                            commands.append(env.step(action))
                            states_after.append(env.state())
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
                    if writer:
                        writer.close()
                result = env.result()
                result.update(success=bool(stable and error is None), stable_2s=stable, error=error,
                              mode=a.mode, split=a.split, checkpoint=str(checkpoint),
                              video=str(stem.with_suffix(".mp4")) if writer else None, hardware_execution=False,
                              privileged_policy_input=False, scripted_rescue=False,
                              inference_seconds=latencies,
                              inference_median_excluding_first=float(np.median(latencies[1:])) if len(latencies)>1 else None,
                              physics_clock="paused_while_policy_computes; not a wall-clock real-time validation")
                stem.with_suffix(".json").write_text(json.dumps(result, indent=2))
                np.savez_compressed(stem.with_suffix(".npz"), state=np.asarray(states), executed_command=np.asarray(commands),
                                    raw_action=np.asarray(raw_actions), predicted_chunks=np.asarray(chunks),
                                    chunk_state=np.asarray(chunk_states), qpos=np.asarray(qpos), qvel=np.asarray(qvel),
                                    object_positions=np.asarray(positions), tcp=np.asarray(tcp), state_after=np.asarray(states_after),
                                    final_qpos=env.data.qpos.copy(), final_qvel=env.data.qvel.copy())
                results.append(result)
                summary = dict(mode=a.mode, split=a.split, successes=sum(r["success"] for r in results),
                               total=len(results), success_rate=np.mean([r["success"] for r in results]),
                               errors=sum(r["error"] is not None for r in results),
                               expected_episodes=protocol["expected_episodes"],
                               complete=len(results)==protocol["expected_episodes"],
                               wall_seconds=time.monotonic()-started_run,
                               domain="simulation", hardware_validated=False, episodes=results)
                (directory / "summary.json").write_text(json.dumps(summary, indent=2))
                print(a.mode, a.split, seed, color, result["success"], error, flush=True)
                if error:
                    raise RuntimeError(f"Evaluation stopped; recorded error: {error}")
    finally:
        env.close()
        if a.policy_host:
            policy.close()


if __name__ == "__main__":
    main()
