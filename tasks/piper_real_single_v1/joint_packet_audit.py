"""Audit CAN timestamp spans in one existing H0 observation-only session.

Run with the existing Python environment; no third-party packages are needed:
  python -m tasks.piper_real_single_v1.joint_packet_audit \
    --joints /actual/session/joints.csv \
    --observations /actual/session/association/observations.jsonl \
    --arm-summary /actual/session/arm_summary.json \
    --output /actual/new_joint_packet_audit.json

The default 5 ms reference is a nominal 200 Hz period used for screening only.
It is not an acceptance limit. A shorter span does not prove that the three
joint packets came from the same controller cycle. This tool reads no device,
does not decode raw CAN, and never changes associations or source records.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path


def timestamp(value: str | None) -> tuple[Decimal | None, str | None]:
    if value is None or not value.strip():
        return None, "missing"
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None, "invalid_decimal"
    if not number.is_finite():
        return None, "nonfinite"
    return number, None


def distribution(values: list[Decimal]) -> dict:
    """Decimal strings in milliseconds; linear interpolation between ranks."""
    ordered = sorted(values)
    result = {"count": len(ordered), "min": None, "p50": None,
              "p95": None, "p99": None, "max": None}
    if not ordered:
        return result
    result.update(min=str(ordered[0]), max=str(ordered[-1]))
    for key, fraction in (("p50", ".5"), ("p95", ".95"), ("p99", ".99")):
        position = Decimal(len(ordered) - 1) * Decimal(fraction)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        result[key] = str(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))
    return result


def summary(rows: list[dict]) -> dict:
    counts = Counter(reason for row in rows for reason in row["reasons"])
    finite = [row for row in rows if row["span_ms"] is not None]
    largest = max(finite, key=lambda row: row["span_ms"]) if finite else None
    return {
        "joint_rows": len(rows),
        "finite_span_ms": distribution([row["span_ms"] for row in finite]),
        "max_span_source": ({
            "csv_data_row": largest["csv_data_row"],
            "host_monotonic_ns": largest["raw"]["host_monotonic_ns"],
            "can_first_s": largest["raw"].get("can_first_s"),
            "can_last_s": largest["raw"].get("can_last_s"),
        } if largest else None),
        "finite_span_includes_negative_values": True,
        "rows_with_screening_flags": sum(bool(row["reasons"]) for row in rows),
        "flag_counts": dict(sorted(counts.items())),
        "flag_counts_can_overlap": True,
    }


def audit(args: argparse.Namespace) -> dict:
    joint_path = args.joints.resolve(strict=True)
    observations_path = args.observations.resolve(strict=True)
    metadata_path = args.arm_summary.resolve(strict=True)
    metadata = json.loads(metadata_path.read_text())
    boot_id = metadata.get("boot_id")
    if not isinstance(boot_id, str) or not boot_id:
        raise ValueError("The actual arm_summary.json must provide its boot_id")

    rows = []
    with joint_path.open(newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "host_monotonic_ns" not in reader.fieldnames:
            raise ValueError("Expected the original H0 joints.csv with host_monotonic_ns")
        for number, raw in enumerate(reader, 1):
            first, first_error = timestamp(raw.get("can_first_s"))
            last, last_error = timestamp(raw.get("can_last_s"))
            reasons = [f"{name}_{error}" for name, error in
                       (("can_first_s", first_error), ("can_last_s", last_error)) if error]
            span = (last - first) * 1000 if first is not None and last is not None else None
            if span is not None:
                if span < 0:
                    reasons.append("negative_span")
                if span >= args.reference_period_ms:
                    reasons.append("span_at_or_above_nominal_period_reference")
            rows.append({"csv_data_row": number, "csv_physical_end_line": reader.line_num,
                         "raw": raw, "span_ms": span, "reasons": reasons})
    if not rows:
        raise ValueError("The supplied joints.csv contains no actual joint rows")

    by_joint_row = defaultdict(list)
    unlinked_images = []
    image_indices = set()
    original_counts = Counter()
    with observations_path.open() as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            observation = json.loads(line)
            if observation.get("boot_id") != boot_id:
                raise ValueError(f"Observation line {line_number}: boot_id differs from arm_summary.json")
            if (observation.get("data_kind") != "observation_only"
                    or observation.get("training_eligible") is not False):
                raise ValueError(f"Observation line {line_number}: expected observation_only source metadata")
            rgb = observation["camera_rgb"]
            index = rgb["stream_index"]
            if not isinstance(index, int) or isinstance(index, bool) or index in image_indices:
                raise ValueError(f"Observation line {line_number}: invalid or duplicate RGB stream index")
            image_indices.add(index)
            original_counts["observation_rows"] += 1
            original_counts["rows_originally_marked_model_observation_complete"] += bool(
                observation.get("model_observation_complete"))
            feedback = observation["joint_feedback"]
            reference = {
                "rgb_stream_index": index, "observation_jsonl_line": line_number,
                "rgb_host_monotonic_ns": rgb["host_monotonic_ns"],
                "rgb_host_unix_ns": rgb.get("host_unix_ns"),
                "rgb_header_ns": rgb.get("header_ns"),
                "original_joint_association_status": feedback.get("status"),
            }
            row_number = feedback.get("csv_data_row")
            if row_number is None:
                unlinked_images.append({**reference, "reason": "source_association_has_no_joint_csv_row"})
                continue
            if (not isinstance(row_number, int) or isinstance(row_number, bool)
                    or not 1 <= row_number <= len(rows)):
                raise ValueError(f"Observation line {line_number}: joint CSV row is outside supplied source")
            joint = rows[row_number - 1]["raw"]
            if str(feedback["host_monotonic_ns"]) != joint["host_monotonic_ns"]:
                raise ValueError(f"Observation line {line_number}: joint receive time disagrees with CSV row")
            saved_times = feedback.get("source_timestamps_s", {})
            for key in ("can_first_s", "can_last_s", "sdk_timestamp_s"):
                if saved_times.get(key) != joint.get(key):
                    raise ValueError(f"Observation line {line_number}: original {key} disagrees with CSV row")
            by_joint_row[row_number].append(reference)
    if not original_counts["observation_rows"]:
        raise ValueError("The supplied observations.jsonl contains no actual observation rows")

    used_rows = [rows[number - 1] for number in sorted(by_joint_row)]
    anomalous_rows = []
    affected_by_reason = defaultdict(set)
    for row in rows:
        if not row["reasons"]:
            continue
        references = by_joint_row.get(row["csv_data_row"], [])
        for reason in row["reasons"]:
            affected_by_reason[reason].update(item["rgb_stream_index"] for item in references)
        anomalous_rows.append({
            "csv_data_row": row["csv_data_row"],
            "csv_physical_end_line": row["csv_physical_end_line"],
            "source_timestamps": {key: row["raw"].get(key) for key in (
                "host_monotonic_ns", "host_unix_ns", "can_first_s", "can_last_s", "sdk_timestamp_s")},
            "span_ms": str(row["span_ms"]) if row["span_ms"] is not None else None,
            "screening_flags": row["reasons"], "associated_rgb": references,
        })

    before = metadata.get("interface_before")
    after = metadata.get("interface_after")
    computed_delta = None
    if isinstance(before, dict) and isinstance(after, dict):
        computed_delta = {key: after[key] - value for key, value in before.items()
                          if isinstance(value, int) and not isinstance(value, bool)
                          and isinstance(after.get(key), int) and not isinstance(after[key], bool)}
    affected_images = sorted({index for indices in affected_by_reason.values() for index in indices})
    return {
        "schema": "piper_real_single_v1.joint_packet_span_audit.v1",
        "status": "READ_ONLY_ANALYSIS_COMPLETED",
        "data_kind": "observation_only", "training_eligible": False,
        "model_inference": "NOT_RUN", "training": "NOT_RUN", "hardware_commands_sent": 0,
        "sources": {"joints_csv": str(joint_path), "observations_jsonl": str(observations_path),
                    "arm_summary_json": str(metadata_path), "boot_id": boot_id},
        "screening_reference": {
            "nominal_period_ms": str(args.reference_period_ms),
            "comparison": "can_last_s minus can_first_s >= reference",
            "meaning": "caller-selected nominal packet-group period; screening only, not an acceptance limit",
        },
        "arithmetic": "Source decimal strings parsed with Decimal; epoch timestamps are never subtracted as floats. "
                      "Span/distribution values are decimal strings in ms; percentiles interpolate adjacent ranks.",
        "all_supplied_joint_rows": summary(rows),
        "unique_joint_rows_referenced_by_rgb": summary(used_rows),
        "source_observation_counts_unchanged": dict(original_counts),
        "arm_summary_reported_joint_rows": metadata.get("joint_rows"),
        "arm_summary_joint_row_count_matches_csv": metadata.get("joint_rows") == len(rows),
        "affected_rgb_stream_indices": affected_images,
        "affected_rgb_by_screening_flag": {key: sorted(value) for key, value in sorted(affected_by_reason.items())},
        "unlinked_rgb_observations": unlinked_images,
        "anomalous_joint_rows": anomalous_rows,
        "recorded_arm_session": {
            "started_monotonic_ns": metadata.get("started_monotonic_ns"),
            "ended_monotonic_ns": metadata.get("ended_monotonic_ns"),
            "can_error_frames": metadata.get("can_error_frames"),
            "recorder_error": metadata.get("error"),
            "interface_before": before, "interface_after": after,
            "interface_delta_computed_from_snapshots": computed_delta,
            "interface_delta_recorded_in_summary": metadata.get("interface_delta"),
        },
        "limitations": [
            "A short packet-group span does not prove same-cycle J1-J6 feedback or physical synchronization.",
            "Interface rx_dropped counts cannot be attributed to individual CAN IDs or affected images from these files.",
            "Flags locate source rows for a later examination of actual raw CAN; this tool does not infer missing packets.",
            "No original observation is rejected, relabeled, removed, or reassociated; original completeness counts remain unchanged.",
            "CAN receive timestamps and same-host observation association do not establish camera exposure or control latency.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joints", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--arm-summary", type=Path, required=True)
    parser.add_argument("--reference-period-ms", type=Decimal, default=Decimal("5"),
                        help="Nominal screening reference only; default 5 ms is not a validated acceptance limit")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; existing files are never overwritten")
    args = parser.parse_args()
    if not args.reference_period_ms.is_finite() or args.reference_period_ms <= 0:
        parser.error("reference period must be finite and positive")
    with localcontext() as context:
        context.prec = 50
        report = audit(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as destination:
        json.dump(report, destination, ensure_ascii=False, indent=2, allow_nan=False)
        destination.write("\n")
    print(json.dumps({"output": str(args.output.resolve()), "status": report["status"],
                      "joint_rows": report["all_supplied_joint_rows"]["joint_rows"],
                      "unique_joint_rows_used_by_rgb": report["unique_joint_rows_referenced_by_rgb"]["joint_rows"],
                      "affected_rgb_rows": len(report["affected_rgb_stream_indices"]),
                      "hardware_commands_sent": 0, "training_eligible": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
