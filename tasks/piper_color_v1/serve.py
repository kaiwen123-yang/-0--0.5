"""Serve one fixed checkpoint on localhost; never opens a CAN interface."""
import argparse
import json
import logging
from pathlib import Path

import jax
from openpi.policies import policy_config as upstream
from openpi.shared import normalize
from openpi.serving.websocket_policy_server import WebsocketPolicyServer
from policy_config import make_config, make_pi0_config


class SeededPolicy:
    def __init__(self, policy):
        self.policy = policy

    def infer(self, obs):
        # Session control is removed before the model sees any observation.
        if set(obs) == {"reset_seed"}:
            seed = int(obs["reset_seed"])
            self.policy._rng = jax.random.key(seed)
            return {"reset_seed": seed}
        return self.policy.infer(obs)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--export", type=Path)
    source.add_argument("--checkpoint", type=Path)
    p.add_argument("--mode", choices=["base", "lora", "full"])
    p.add_argument("--model-family", choices=["pi0", "pi05"], default="pi05")
    p.add_argument("--norm-stats", type=Path)
    p.add_argument("--port", type=int, default=8002)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.export:
        if args.mode:
            p.error("--mode is read from the export manifest")
        mode = json.loads((args.export / "manifest.json").read_text())["selected_mode"]
        checkpoint = args.export / "checkpoint"
    else:
        if args.mode is None:
            p.error("--checkpoint requires --mode")
        mode, checkpoint = args.mode, args.checkpoint
    checkpoint = checkpoint.resolve(strict=True)
    if args.model_family == "pi0" and mode != "lora":
        p.error("The dedicated pi0 six-demo config supports LoRA only")
    cfg = make_pi0_config() if args.model_family == "pi0" else make_config(mode)
    stats = normalize.load(args.norm_stats) if args.norm_stats else None
    policy = upstream.create_trained_policy(cfg, checkpoint, norm_stats=stats,
                                            sample_kwargs={"num_steps": 10})
    policy._rng = jax.random.key(args.seed)
    metadata = {**cfg.policy_metadata, "model_family": args.model_family,
                "mode": mode, "checkpoint": str(checkpoint),
                "norm_stats": str(args.norm_stats.resolve()) if args.norm_stats else "checkpoint_assets",
                "seed": args.seed, "reset_seed_supported": True, "action_horizon": 10,
                "flow_denoising_steps": 10}
    print("MODEL_LOADED " + json.dumps(metadata), flush=True)
    WebsocketPolicyServer(SeededPolicy(policy), host="127.0.0.1", port=args.port,
                          metadata=metadata).serve_forever()
