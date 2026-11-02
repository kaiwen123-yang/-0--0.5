"""Serve the adaptation config with its frozen old normalization."""
import argparse
import json
import logging
from pathlib import Path

import jax
from openpi.policies import policy_config as upstream
from openpi.shared import normalize
from openpi.serving.websocket_policy_server import WebsocketPolicyServer
from serve import SeededPolicy
from train_pi0_ef import config


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--norm-stats", type=Path, required=True)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    cfg = config()
    checkpoint, norm = a.checkpoint.resolve(strict=True), a.norm_stats.resolve(strict=True)
    policy = upstream.create_trained_policy(cfg, checkpoint, norm_stats=normalize.load(norm), sample_kwargs={"num_steps": 10})
    policy._rng = jax.random.key(42)
    metadata = {**cfg.policy_metadata, "model_family": "pi0", "mode": "lora", "checkpoint": str(checkpoint),
                "norm_stats": str(norm), "reset_seed_supported": True, "action_horizon": 10, "flow_denoising_steps": 10}
    print("MODEL_LOADED " + json.dumps(metadata), flush=True)
    WebsocketPolicyServer(SeededPolicy(policy), host="127.0.0.1", port=18770, metadata=metadata).serve_forever()
