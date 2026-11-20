"""Associate existing H0 RGB/feedback records; never open a device or infer actions.

Source format: dog-and-arm@284c1f3 scripts/h0_record_camera.py and
scripts/h0_record_arm.py. The association uses preceding receive events from
one Linux boot. It is not exposure synchronization or a training-data exporter.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import csv
import json
import math
from pathlib import Path


def csv_rows(path: Path, *, optional: bool = False) -> list[dict]:
    if optional and not path.exists():
        return []
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def monotonic_times(rows: list[dict], label: str) -> list[int]:
    times = [int(row["host_monotonic_ns"]) for row in rows]
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError(f"{label}: receive clock goes backwards; do not reorder a mixed session")
    return times


def finite_value(text: str | None) -> float | None:
    if text is None or text == "":
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lo, hi = math.floor(position), math.ceil(position)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

    return {"count": len(values), "p50": percentile(.5),
            "p95": percentile(.95), "max": ordered[-1]}


def timing_summary(times: list[int]) -> dict:
    span = (times[-1] - times[0]) / 1e9 if len(times) > 1 else 0
    return {"rows": len(times), "receive_span_s": span,
            "receive_hz": (len(times) - 1) / span if span > 0 else None,
            "receive_interval_ms": distribution([(b - a) / 1e6 for a, b in zip(times, times[1:])])}


def load_samples(path: Path | None) -> dict[int, dict]:
    """Read native sample_index.jsonl or H0's exported window_manifest.json."""
    if path is None:
        return {}
    with path.open() as stream:
        rows = ([json.loads(line) for line in stream if line.strip()]
                if path.suffix == ".jsonl" else json.load(stream)["samples"])
    result = {}
    for row in rows:
        if row["stream"] != "color":
            continue
        index = int(row["index"])
        if index in result and result[index] != row:
            # Window manifests may repeat the same periodic sample for two events.
            old = result[index]
            if any(old[key] != row[key] for key in ("path", "host_monotonic_ns", "header_ns")):
                raise ValueError(f"Conflicting RGB sample metadata for index {index}")
        result[index] = row
    return result


def preceding(rows: list[dict], times: list[int], at: int, max_age_ns: int,
              kind: str) -> dict:
    index = bisect_right(times, at) - 1
    if index < 0:
        return {"status": "missing_preceding_feedback", "values": None,
                "host_monotonic_ns": None, "receive_age_ms": None}
    row = rows[index]
    names = [f"q{i}_rad" for i in range(1, 7)] if kind == "joint" else ["width_m"]
    values = [finite_value(row.get(name)) for name in names]
    age_ns = at - times[index]
    status = ("nonfinite_or_missing_measurement" if any(v is None for v in values)
              else "older_than_association_limit" if age_ns > max_age_ns else "associated")
    source_names = ("can_first_s", "can_last_s", "sdk_timestamp_s") if kind == "joint" else ("can_timestamp_s",)
    return {"status": status, "values": values, "csv_data_row": index + 1,
            "host_monotonic_ns": times[index], "host_unix_ns": int(row["host_unix_ns"]),
            "receive_age_ms": age_ns / 1e6,
            "source_timestamps_s": {key: row.get(key) for key in source_names},
            "source_timestamp_note": "Original CSV strings retained; not compared with monotonic time"}


def associate(args: argparse.Namespace) -> dict:
    camera_dir = args.camera_dir.resolve(strict=True)
    camera_metadata_path = (args.camera_metadata or camera_dir / "camera_summary.json").resolve(strict=True)
    camera_metadata = json.loads(camera_metadata_path.read_text())
    camera_boot = camera_metadata.get("boot_id")
    if not camera_boot:
        raise ValueError("Camera summary needs its real boot_id before clock association")
    arm_dir = args.arm_dir.resolve(strict=True) if args.arm_dir else None
    arm_metadata_path, arm_metadata = None, None
    if arm_dir is not None:
        arm_metadata_path = (args.arm_metadata or arm_dir / "arm_summary.json").resolve(strict=True)
        arm_metadata = json.loads(arm_metadata_path.read_text())
        if not arm_metadata.get("boot_id"):
            raise ValueError("Arm summary needs its real boot_id before clock association")
        if arm_metadata["boot_id"] != camera_boot:
            raise ValueError("Camera and arm boot_id differ; these monotonic clocks cannot be associated")
    elif args.arm_metadata:
        raise ValueError("--arm-metadata requires --arm-dir")

    colors = [row for row in csv_rows(camera_dir / "stream_timing.csv") if row["stream"] == "color"]
    color_times = monotonic_times(colors, "RGB")
    if not colors:
        raise ValueError("No real color receive events in stream_timing.csv")
    joints = csv_rows(arm_dir / "joints.csv", optional=True) if arm_dir else []
    grippers = csv_rows(arm_dir / "gripper.csv", optional=True) if arm_dir else []
    joint_times, gripper_times = monotonic_times(joints, "joints"), monotonic_times(grippers, "gripper")
    sample_path = args.sample_manifest
    if sample_path is None and (camera_dir / "sample_index.jsonl").is_file():
        sample_path = camera_dir / "sample_index.jsonl"
    if sample_path is not None:
        sample_path = sample_path.resolve(strict=True)
    samples = load_samples(sample_path)
    seen_indices: set[int] = set()
    for color in colors:
        index = int(color["index"])
        if index in seen_indices:
            raise ValueError(f"Repeated color stream index {index}; supply one original H0 session")
        seen_indices.add(index)
        if index in samples:
            sample = samples[index]
            if (int(sample["host_monotonic_ns"]) != int(color["host_monotonic_ns"])
                    or int(sample["header_ns"]) != int(color["header_ns"])):
                raise ValueError(f"RGB sample {index} disagrees with stream_timing.csv")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    counts: Counter = Counter()
    joint_ages, gripper_ages = [], []
    with (output / "observations.jsonl").open("x") as destination:
        for color, at in zip(colors, color_times):
            index = int(color["index"])
            joint = preceding(joints, joint_times, at, int(args.max_joint_age_ms * 1e6), "joint")
            gripper = preceding(grippers, gripper_times, at, int(args.max_gripper_age_ms * 1e6), "gripper")
            for name, feedback, ages in (("joint", joint, joint_ages), ("gripper", gripper, gripper_ages)):
                counts[f"{name}_{feedback['status']}"] += 1
                if feedback["receive_age_ms"] is not None:
                    ages.append(feedback["receive_age_ms"])
            state = (joint["values"] + gripper["values"]
                     if joint["status"] == gripper["status"] == "associated" else None)
            sample = samples.get(index)
            image_path = (camera_dir / sample["path"]).resolve() if sample else None
            image_exists = image_path is not None and image_path.is_file()
            counts["rgb_receive_rows"] += 1
            counts["rows_with_complete_measured_state"] += state is not None
            counts["rows_with_retained_raw_png"] += image_exists
            counts["complete_observation_rows"] += image_exists and state is not None
            row = {
                "schema": "piper_real_single_v1.observation_index.v1",
                "data_kind": "observation_only", "training_eligible": False,
                "camera_id": args.camera_id, "mount": args.mount, "boot_id": camera_boot,
                "camera_rgb": {"path": str(image_path) if image_path else None, "available": image_exists,
                               "stream_index": index, "host_monotonic_ns": at,
                               "host_unix_ns": int(color["host_unix_ns"]), "header_ns": int(color["header_ns"]),
                               "frame_id": color["frame_id"], "source_encoding": color["encoding"],
                               "width": int(color["width"]), "height": int(color["height"]),
                               "stored_format": "PNG" if sample else None,
                               "decode_note": "Pillow convert('RGB') decodes directly; cv2.imread needs one BGR-to-RGB conversion. Do not swap an already-RGB array."},
                "state": state, "state_units": "q1..q6 rad, measured total gripper opening m",
                "joint_feedback": joint, "gripper_feedback": gripper,
                "action": None, "action_source": "not_recorded_by_this_observation_tool",
                "model_observation_complete": bool(image_exists and state is not None),
                "association": "latest preceding measured receive event; no interpolation or future state",
            }
            destination.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")

    report = {
        "schema": "piper_real_single_v1.h0_association_report.v1",
        "hardware_execution": "NOT_RUN", "model_inference": "NOT_RUN",
        "operation": "offline analysis of existing real H0 recording",
        "data_kind": "observation_only", "training_eligible": False, "action_rows_created": 0,
        "camera_id": args.camera_id, "mount": args.mount,
        "clock": {"boot_id": camera_boot, "arm_same_boot_verified": arm_metadata is not None,
                  "basis": "same-host monotonic receive time", "hardware_sync_claimed": False,
                  "note": "ROS header, kernel CAN and SDK times are retained separately; none is asserted to be exposure time"},
        "sources": {"camera_directory": str(camera_dir), "arm_directory": str(arm_dir) if arm_dir else None,
                    "camera_metadata": str(camera_metadata_path),
                    "arm_metadata": str(arm_metadata_path) if arm_metadata_path else None,
                    "sample_manifest": str(sample_path) if sample_path else None},
        "association_limits_ms": {"joint": args.max_joint_age_ms, "gripper": args.max_gripper_age_ms,
                                  "meaning": "caller-selected data association limits, not verified hardware latency limits"},
        "counts": dict(counts),
        "receive_timing": {"camera_rgb": timing_summary(color_times), "joint": timing_summary(joint_times),
                           "gripper": timing_summary(gripper_times)},
        "preceding_receive_age_ms": {"joint": distribution(joint_ages), "gripper": distribution(gripper_ages)},
        "limitations": ["Receive association is not exposure synchronization or sensor latency.",
                        "H0 periodic PNG samples are sparse; most timing rows may have no raw image file.",
                        "Annotated preview.avi is not used as raw RGB.",
                        "No action labels are inferred from measured states or historical motion events.",
                        "CameraInfo, intrinsics and extrinsics remain source metadata, not newly calibrated values."],
    }
    (output / "association_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-dir", type=Path, required=True)
    parser.add_argument("--arm-dir", type=Path, help="Omit for explicit camera-only observation indexing")
    parser.add_argument("--camera-metadata", type=Path, help="Default: camera-dir/camera_summary.json")
    parser.add_argument("--arm-metadata", type=Path, help="Default: arm-dir/arm_summary.json")
    parser.add_argument("--sample-manifest", type=Path, help="Native sample_index.jsonl or H0 window_manifest.json")
    parser.add_argument("--camera-id", required=True, help="Actual camera identity, not an invented second stream")
    parser.add_argument("--mount", choices=("external_fixed", "wrist"), required=True)
    parser.add_argument("--max-joint-age-ms", type=float, default=100)
    parser.add_argument("--max-gripper-age-ms", type=float, default=100)
    parser.add_argument("--output", type=Path, required=True, help="New directory; source files are unchanged")
    args = parser.parse_args()
    if not all(math.isfinite(x) and x >= 0 for x in (args.max_joint_age_ms, args.max_gripper_age_ms)):
        parser.error("association ages must be finite and nonnegative")
    report = associate(args)
    print(json.dumps({"output": str(args.output.resolve()), "counts": report["counts"],
                      "hardware_execution": "NOT_RUN", "training_eligible": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
