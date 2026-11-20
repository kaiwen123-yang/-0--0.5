"""Export one real indexed RGB/state observation for the read-only model entry.

This consumes associate_h0.py output. It does not create demonstrations, action
labels, calibration matrices or a missing camera. Select an actual RGB stream
index and supply the task prompt explicitly.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--stream-index", type=int, required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    selected = None
    with args.index.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["camera_rgb"]["stream_index"] == args.stream_index:
                selected = row
                break
    if selected is None or not selected["model_observation_complete"]:
        raise ValueError("Selected row lacks its real image or an associated measured 7D state.")
    image_path = Path(selected["camera_rgb"]["path"])
    with Image.open(image_path) as source_image:
        rgb = np.asarray(source_image.convert("RGB"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as destination:
        np.savez(destination,
                 camera_rgb=rgb,
                 state=np.asarray(selected["state"], dtype=np.float32),
                 prompt=np.asarray(args.prompt))
    report = {
        "operation": "export_one_existing_real_observation",
        "source_index": str(args.index.resolve()),
        "stream_index": args.stream_index,
        "source_image": str(image_path),
        "camera_id": selected["camera_id"],
        "camera_mount": selected["mount"],
        "camera_host_monotonic_ns": selected["camera_rgb"]["host_monotonic_ns"],
        "joint_receive_age_ms": selected["joint_feedback"]["receive_age_ms"],
        "gripper_receive_age_ms": selected["gripper_feedback"]["receive_age_ms"],
        "observation_file": str(args.output.resolve()),
        "image_conversion": "PNG decoded directly to RGB with Pillow; no BGR stage, resize or undistortion",
        "action_labels_created": 0,
        "training_eligible": False,
        "model_inference": "NOT_RUN",
        "commands_sent": 0
    }
    with args.output.with_suffix(".json").open("x") as destination:
        json.dump(report, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

