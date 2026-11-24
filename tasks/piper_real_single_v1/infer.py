"""Read-only inference on one actual saved observation, using its own trained assets.

Run with the existing OpenPI environment from the repository root:
  python -m tasks.piper_real_single_v1.infer --spec <actual.json> \
      --checkpoint <single-camera-checkpoint> --observation <actual.npz> --output <predictions.npz>

Observation keys: camera_rgb (uint8 RGB HWC), state (7 measured values), prompt.
The observation needs no action label. No CAN sender is imported or called.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np


from .width_contract import CAMERA, WIDTH, model_asset_id
from .color_task import BLUE_RED, stage_a_prompt


def create_policy(spec, checkpoint):
    """Reusable by the live shadow loop; model loading happens only on this call."""
    from openpi.policies import policy_config

    from .policy_config import make_inference_config

    # OpenPI loads norm_stats from this exact checkpoint's assets/asset_id.
    # Do not inject B's or another model family's statistics here.
    checkpoint = Path(checkpoint).expanduser()
    asset = checkpoint/"assets"/model_asset_id(spec)
    metadata = json.loads((asset/"width_contract.json").read_text())
    expected = dict(gripper_basis=WIDTH, model_family=spec["model_family"], camera_mount="wrist",
                    asset_id=asset.name, split="train", target_colors=list(BLUE_RED), action_horizon=10, policy_hz=20,
                    normalization="quantile" if spec["model_family"]=="pi05" else "mean_std",
                    norm_sha256=hashlib.sha256((asset/"norm_stats.json").read_bytes()).hexdigest())
    if any(metadata.get(k) != v for k,v in expected.items()) or not metadata.get("frozen_split_sha256"):
        raise ValueError("Incompatible real wrist checkpoint normalization metadata")
    return policy_config.create_trained_policy(make_inference_config(spec, checkpoint), checkpoint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--instruction", help="本次蓝/红规范指令；省略时使用观测自带的阶段 A 指令")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text())
    required_fields = ("model_family", "camera_mount", "openpi_root", "action_horizon", "policy_hz")
    missing = [f"spec.{key}" for key in required_fields if spec.get(key) is None or spec.get(key) == ""]
    if spec.get("model_family") not in ("pi0", "pi05"):
        missing.append("spec.model_family must be pi0 or pi05")
    if spec.get("camera_mount") != "wrist" or spec.get("gripper_basis") != WIDTH or spec.get("action_horizon") != 10:
        missing.append("formal wrist spec requires explicit SDK width v1 and action_horizon=10")
    if spec.get("policy_hz") != 20:
        missing.append("spec.policy_hz must be 20 for this action-grid contract")
    if missing:
        print(json.dumps({"status": "NOT_RUN", "missing": missing, "sent": False}, indent=2))
        return 2
    checkpoint = Path(args.checkpoint).expanduser()
    aid = model_asset_id(spec)
    required = (checkpoint / "params", checkpoint / "assets" / aid / "norm_stats.json", Path(args.observation))
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print(json.dumps({"status": "NOT_RUN", "missing": missing, "sent": False}, indent=2))
        return 2
    openpi_root = Path(spec["openpi_root"]).expanduser()
    sys.path.insert(0, str(openpi_root))
    sys.path.insert(0, str(openpi_root / "src"))
    with np.load(args.observation, allow_pickle=False) as sample:
        if any(k not in sample or sample[k].item() != v for k,v in
               (("gripper_basis",WIDTH),("camera_id",CAMERA),("camera_mount","wrist"))):
            raise ValueError("Observation lacks the matching SDK width and single wrist identity")
        observation = {
            "camera_rgb": sample["camera_rgb"].copy(),
            "state": sample["state"].copy(),
            "prompt": stage_a_prompt(args.instruction if args.instruction is not None else str(sample["prompt"].item())),
        }
    policy = create_policy(spec, checkpoint)
    started = time.perf_counter_ns()
    actions = np.asarray(policy.infer(observation)["actions"])
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(output, actions=actions, state=observation["state"], prompt=observation["prompt"], gripper_basis=WIDTH, sent=False)
    report = {
        "status": "READ_ONLY_INFERENCE_COMPLETED",
        "gripper_basis": WIDTH,
        "model_family": spec["model_family"],
        "camera_mount": spec["camera_mount"],
        "policy_hz": spec["policy_hz"],
        "policy_hz_semantics": "nominal action grid; not measured inference or robot frequency",
        "checkpoint": str(checkpoint),
        "observation": args.observation,
        "output": str(output),
        "inference_ms": elapsed_ms,
        "timing_scope": "one call including any first-call compilation, not a steady-state latency estimate",
        "sent": False,
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
