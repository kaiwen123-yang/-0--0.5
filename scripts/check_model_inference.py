"""Load one verified LIBERO checkpoint and run two synthetic GPU predictions.

This is an inference compatibility check, not a simulator evaluation. No actions
are sent to a robot or simulator. Run one model per process to release memory.
"""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

from serve_local import validate_checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("pi0", "pi05"), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    checkpoint_name = f"{args.model}_libero"
    checkpoint = root / "checkpoints" / checkpoint_name
    validate_checkpoint(root, checkpoint, checkpoint_name, "jax")
    processes = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True
    ).strip()
    if processes:
        raise SystemExit("GPU compute processes are active; wait until the GPU is available.")

    import jax
    import numpy as np
    from openpi.policies import libero_policy, policy_config
    from openpi.training import config

    device = jax.devices("gpu")[0]
    cfg = config.get_config(checkpoint_name)
    started = time.monotonic()
    policy = policy_config.create_trained_policy(cfg, checkpoint)
    load_seconds = time.monotonic() - started
    np.random.seed(7)
    observation = libero_policy.make_libero_example()
    observation["prompt"] = "pick up the black bowl"
    durations = []
    for index in range(2):
        started = time.monotonic()
        result = policy.infer(observation)
        durations.append(time.monotonic() - started)
        actions = result["actions"]
        assert actions.shape == (cfg.model.action_horizon, 7), actions.shape
        assert np.isfinite(actions).all()
        np.save(root / f"results/{args.model}-synthetic-actions-{index}.npy", actions)
    report = {
        "status": "passed", "model": checkpoint_name, "backend": "jax",
        "device": device.device_kind, "checkpoint": str(checkpoint),
        "full_checkpoint_loaded": True, "batch_size": 1,
        "flow_denoising_steps": 10, "predictions": 2,
        "action_shape": list(actions.shape), "actions_finite": True,
        "load_seconds": load_seconds, "inference_wall_seconds": durations,
        "first_inference_includes_jit_compile": True,
        "device_allocator_memory_stats": device.memory_stats(),
        "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "input": "seeded official synthetic LIBERO example, not a task rollout",
        "training": False, "robot_connected": False,
        "scope": "Full model compatibility only; no success-rate or control-latency benchmark",
    }
    (root / f"results/{args.model}-gpu-inference.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
