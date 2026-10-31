"""Local LIBERO evaluation server with reproducible per-episode JAX seeds."""
import argparse
import importlib.metadata
import json
import logging
from pathlib import Path
import time

from serve_local import validate_checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=("pi0", "pi05"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run_dir = args.run_dir.resolve()
    config_name = f"{args.model}_libero"
    checkpoint = root / "checkpoints" / config_name
    validate_checkpoint(root, checkpoint, config_name, "jax")

    import jax
    import numpy as np
    from openpi.policies import libero_policy, policy_config
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer
    from openpi.training import config
    from openpi_client.base_policy import BasePolicy

    started = time.monotonic()
    cfg = config.get_config(config_name)
    policy = policy_config.create_trained_policy(cfg, checkpoint, sample_kwargs={"num_steps": 10})
    loaded = time.monotonic()
    np.random.seed(7)
    warmup = policy.infer(libero_policy.make_libero_example())
    assert warmup["actions"].shape == (cfg.model.action_horizon, 7)
    assert np.isfinite(warmup["actions"]).all()

    class SeededPolicy(BasePolicy):
        def __init__(self):
            self.episode = None
            self.seed = None
            self.requests = 0

        def infer(self, obs):
            observation = dict(obs)
            episode = observation.pop("evaluation/episode_id")
            seed = observation.pop("evaluation/seed")
            if not isinstance(episode, str) or not episode:
                raise ValueError("A nonempty evaluation episode identifier is required")
            if not isinstance(seed, int) or not 0 <= seed < 2**31:
                raise ValueError("Invalid evaluation seed")
            if episode != self.episode:
                # Pinned upstream Policy has no public reset API. Reset exactly
                # its standard JAX RNG, preserving its Gaussian sampling path.
                policy._rng = jax.random.key(seed)
                self.episode, self.seed, self.requests = episode, seed, 0
            elif seed != self.seed:
                raise ValueError("The policy seed changed during an episode")
            result = policy.infer(observation)
            self.requests += 1
            result["evaluation"] = {"model": args.model, "episode_id": episode,
                                    "seed": seed, "request": self.requests}
            return result

    metadata = {
        "model": args.model, "config": config_name, "run_id": run_dir.name,
        "checkpoint": str(checkpoint), "backend": "jax", "precision": "bfloat16",
        "action_horizon": cfg.model.action_horizon, "flow_steps": 10,
        "episode_seed_reset": True, "warmup_excluded_from_evaluation_rng": True,
    }
    report = dict(metadata, load_seconds=loaded-started,
                  warmup_seconds=time.monotonic()-loaded,
                  device=jax.devices("gpu")[0].device_kind,
                  versions={name: importlib.metadata.version(name)
                            for name in ("jax", "jaxlib", "flax", "numpy")})
    (run_dir / f"server-{args.model}.json").write_text(json.dumps(report, indent=2) + "\n")
    logging.info("Ready: %s", json.dumps(metadata))
    WebsocketPolicyServer(SeededPolicy(), host="127.0.0.1", port=args.port,
                          metadata=metadata).serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
