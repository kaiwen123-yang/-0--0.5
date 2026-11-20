"""Show one existing ROS RGB topic and H0's latest persisted measured feedback.

No camera pipeline, CAN socket, SDK, policy server, enable or motion API is opened.
The H0 arm logger flushes CSV files every two seconds. Displayed feedback ages
include file visibility and viewer scheduling; they are not hardware latency.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image


class CsvTail:
    """Consume complete appended H0 CSV lines and retain their original timestamp."""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None
        self.identity = None
        self.header = None
        self.partial = ""
        self.latest = None
        self.first_seen_monotonic_ns = None

    def poll(self) -> None:
        if self.stream is None:
            if not self.path.is_file():
                return
            stat = self.path.stat()
            self.identity = (stat.st_dev, stat.st_ino)
            self.stream = self.path.open()
        stat = self.path.stat()
        if (stat.st_dev, stat.st_ino) != self.identity or stat.st_size < self.stream.tell():
            raise RuntimeError(f"Recording file replaced/truncated: {self.path}; select the correct session explicitly")
        chunk = self.stream.read()
        read_at_ns = time.monotonic_ns()
        if not chunk:
            return
        lines = (self.partial + chunk).split("\n")
        self.partial = lines.pop()
        updated = False
        for line in lines:
            if not line.strip():
                continue
            values = next(csv.reader([line]))
            if self.header is None:
                self.header = values
                if "host_monotonic_ns" not in self.header:
                    raise ValueError(f"Missing H0 receive timestamp in {self.path}")
                continue
            if len(values) != len(self.header):
                raise ValueError(f"Incomplete H0 CSV record in {self.path}")
            row = dict(zip(self.header, values))
            timestamp = int(row["host_monotonic_ns"])
            if timestamp > read_at_ns:
                raise ValueError(f"Feedback timestamp is in the future: {self.path}")
            if self.latest and timestamp < int(self.latest["host_monotonic_ns"]):
                raise ValueError(f"Feedback receive time regressed: {self.path}")
            self.latest = row
            updated = True
        if updated:
            self.first_seen_monotonic_ns = read_at_ns

    def close(self) -> None:
        if self.stream:
            self.stream.close()


class RgbView(Node):
    def __init__(self, topic: str):
        super().__init__("pi_single_camera_read_only_view")
        self.image = None
        self.received_ns = None
        self.header_ns = None
        self.frame_id = None
        self.frame_count = 0
        self.subscription = self.create_subscription(
            Image, topic, self.receive,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))

    def receive(self, message: Image) -> None:
        received_ns = time.monotonic_ns()
        if message.encoding not in ("rgb8", "bgr8"):
            raise ValueError(f"Expected real RGB image rgb8/bgr8, got {message.encoding}")
        image = np.ndarray((message.height, message.width, 3), dtype=np.uint8,
                           buffer=message.data, strides=(message.step, 3, 1)).copy()
        self.image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if message.encoding == "rgb8" else image
        self.received_ns = received_ns
        self.header_ns = message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
        self.frame_id = message.header.frame_id
        self.frame_count += 1


def values_text(row: dict | None, keys: list[str]) -> str:
    if row is None:
        return "MISSING (no measured row visible)"
    result = []
    for key in keys:
        raw = row.get(key)
        if raw is None or raw == "":
            result.append("MISSING")
        else:
            value = float(raw)
            result.append(f"{value:.5f}" if math.isfinite(value) else "NONFINITE")
    return "  ".join(result)


def feedback_line(name: str, tail: CsvTail, now_ns: int) -> str:
    if tail.latest is None:
        return f"{name}: no measured CSV row visible"
    event = int(tail.latest["host_monotonic_ns"])
    age_ms = (now_ns - event) / 1e6
    visible_age_ms = (tail.first_seen_monotonic_ns - event) / 1e6
    return f"{name}: recorded-event age={age_ms:.1f}ms; age when read from file={visible_age_ms:.1f}ms"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True, help="Existing RGB topic; no camera driver is started")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--mount", choices=("external_fixed", "wrist"), required=True)
    parser.add_argument("--arm-dir", type=Path, help="Existing H0 receive-only recording directory; optional for RGB-only display")
    parser.add_argument("--arm-metadata", type=Path, help="Default: arm-dir/arm_live.json; must contain this boot_id")
    parser.add_argument("--seconds", type=float, default=0, help="0: until q/Escape/Ctrl+C; otherwise explicit display session duration")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error("--seconds must be finite and nonnegative")
    if args.arm_metadata and args.arm_dir is None:
        parser.error("--arm-metadata requires --arm-dir")
    current_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    tails = []
    if args.arm_dir:
        metadata_path = args.arm_metadata or args.arm_dir / "arm_live.json"
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("boot_id") != current_boot:
            raise ValueError("H0 feedback boot_id is absent/different; cannot label it as this host's live feedback")
        tails = [CsvTail(args.arm_dir / "joints.csv"), CsvTail(args.arm_dir / "gripper.csv")]

    rclpy.init(args=[])
    node = RgbView(args.topic)
    title = "Pi single camera | READ ONLY | q/Escape to close"
    started = time.monotonic()
    print(json.dumps({"mode": "observation_only", "camera_rgb_topic": args.topic,
                      "camera_id": args.camera_id, "mount": args.mount, "boot_id": current_boot,
                      "arm_source": str(args.arm_dir) if args.arm_dir else None,
                      "hardware_commands_sent": 0, "model_inference": "NOT_RUN",
                      "feedback_note": "persisted H0 receive rows; two-second explicit flush; age is not sensor latency"}), flush=True)
    try:
        while rclpy.ok() and (args.seconds == 0 or time.monotonic() - started < args.seconds):
            rclpy.spin_once(node, timeout_sec=.01)
            for tail in tails:
                tail.poll()
            now_ns = time.monotonic_ns()
            width = max(960, node.image.shape[1] if node.image is not None else 0)
            image_height = node.image.shape[0] if node.image is not None else 480
            canvas = np.zeros((image_height + 260, width, 3), dtype=np.uint8)
            if node.image is not None:
                canvas[:image_height, :node.image.shape[1]] = node.image
            else:
                cv2.putText(canvas, "NO RGB RECEIVED - this is a display placeholder", (20, 80),
                            cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 170, 255), 1, cv2.LINE_AA)
            age = f"{(now_ns - node.received_ns) / 1e6:.1f}ms" if node.received_ns is not None else "MISSING"
            lines = [f"READ ONLY | mount={args.mount} | camera={args.camera_id}",
                     f"camera_rgb callback age={age}; received frames={node.frame_count}; no exposure-sync claim",
                     f"Original ROS header ns={node.header_ns}; topic={args.topic}"]
            if tails:
                joint, gripper = tails
                lines += ["Measured q1..q6 [rad]: " + values_text(joint.latest, [f"q{i}_rad" for i in range(1, 7)]),
                          feedback_line("Joints", joint, now_ns),
                          "Measured total opening [m]: " + values_text(gripper.latest, ["width_m"]),
                          feedback_line("Gripper", gripper, now_ns)]
            else:
                lines += ["Arm source not selected; measured state MISSING (no targets substituted)"]
            lines += ["H0 CSV flush: 2s. File visibility/scheduling contributes to feedback age; NOT hardware latency.",
                      "No actions sent. No model inference. RGB and persisted feedback are displayed separately."]
            for number, line in enumerate(lines):
                cv2.putText(canvas, line, (12, image_height + 24 + number * 25),
                            cv2.FONT_HERSHEY_SIMPLEX, .48, (225, 225, 225), 1, cv2.LINE_AA)
            cv2.imshow(title, canvas)
            if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                break
    except KeyboardInterrupt:
        pass
    finally:
        for tail in tails:
            tail.close()
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()
        print(json.dumps({"viewer_seconds": time.monotonic() - started, "rgb_callbacks": node.frame_count,
                          "hardware_commands_sent": 0, "model_inference": "NOT_RUN"}), flush=True)


if __name__ == "__main__":
    main()
