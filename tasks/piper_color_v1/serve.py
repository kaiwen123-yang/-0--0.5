"""Serve an exported candidate on localhost; never opens a CAN interface."""
import argparse
import json
from pathlib import Path

from openpi.policies import policy_config as upstream
from openpi.serving.websocket_policy_server import WebsocketPolicyServer
from policy_config import make_config


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--export", type=Path, required=True)
    p.add_argument("--port", type=int, default=8002)
    args = p.parse_args()
    manifest = json.loads((args.export / "manifest.json").read_text())
    cfg = make_config(manifest["selected_mode"])
    policy = upstream.create_trained_policy(cfg, args.export / "checkpoint")
    WebsocketPolicyServer(policy, host="127.0.0.1", port=args.port,
                          metadata={**cfg.policy_metadata, "export":str(args.export)}).serve_forever()
