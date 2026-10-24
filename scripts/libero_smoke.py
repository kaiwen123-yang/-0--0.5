"""Validate LIBERO metadata and physics on CPU, without models or rendering."""
import json
from pathlib import Path
import sys
import time

from libero_bootstrap import ROOT, configure, allow_trusted_initial_states
configure(cpu_only=True)

import numpy as np
import torch
import mujoco
import robosuite
from libero.libero import benchmark
from libero.libero.envs.env_wrapper import ControlEnv

allow_trusted_initial_states()


def main():
    started = time.monotonic()
    suites = benchmark.get_benchmark_dict()
    metadata = {}
    for name in benchmark.libero_suites:
        suite = suites[name]()
        for i in range(suite.n_tasks):
            assert Path(suite.get_task_bddl_file_path(i)).is_file()
        metadata[name] = suite.n_tasks
    suite = suites["libero_spatial"]()
    task = suite.get_task(0)
    states = suite.get_task_init_states(0)
    assert len(states) > 0
    env = ControlEnv(
        bddl_file_name=suite.get_task_bddl_file_path(0),
        use_camera_obs=False,
        has_renderer=False,
        has_offscreen_renderer=False,
        hard_reset=False,
    )
    try:
        env.seed(7)
        obs = env.reset()
        obs = env.set_init_state(states[0])
        for _ in range(10):
            obs, reward, done, info = env.step([0.0] * 6 + [-1.0])
        assert np.isfinite(env.sim.data.qpos).all()
        assert np.isfinite(env.sim.data.qvel).all()
        assert not any(key.endswith("_image") for key in obs)
        result = {
            "status": "passed",
            "interpreter": sys.executable,
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "torch_cuda_build": torch.version.cuda,
            "mujoco": mujoco.__version__,
            "robosuite": robosuite.__version__,
            "suites": metadata,
            "task": task.name,
            "initial_states": len(states),
            "physics_steps": 10,
            "rendering": False,
            "model_inference": False,
            "observations": {k: list(np.asarray(v).shape) for k, v in obs.items()},
            "qpos_finite": True,
            "qvel_finite": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "scope": "CPU physics preparation; not policy success-rate reproduction",
        }
    finally:
        env.close()
    output = ROOT / "results/libero_cpu_smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
