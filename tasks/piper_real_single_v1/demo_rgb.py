"""Lossless received wrist RGB only. Runs under the existing H0 ROS environment."""
import argparse
import csv
import json
import queue
import signal
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

TOPIC = "/wrist_camera/color/image_raw"
SERIAL = "CC16762023M"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--one", action="store_true", help="Save one current layout frame and exit")
    args = p.parse_args()
    out = args.directory
    serials = [s.read_text().strip() for s in Path("/sys/bus/usb/devices").glob("*/serial")
               if (s.parent / "idProduct").read_text().strip() == "0557"
               and (s.parent / "idVendor").read_text().strip() == "2bc5"]
    if serials != [SERIAL]:
        raise RuntimeError(f"Expected one wrist DC1, found {serials}")
    (out / "rgb").mkdir()
    rclpy.init()
    node = rclpy.create_node("pi_single_wrist_rgb")
    stop = threading.Event()
    pending = queue.Queue(32)
    report = dict(boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  camera_id=SERIAL, topic=TOPIC, received=0, written=0, queue_drops=0,
                  last_ns=0, error=None)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    def receive(msg):
        mono, unix = time.monotonic_ns(), time.time_ns()
        if (msg.width, msg.height, msg.encoding, msg.header.frame_id) != (
                640, 480, "rgb8", "wrist_camera_color_optical_frame"):
            raise ValueError("Wrist RGB identity/format changed")
        if args.one and report["received"]:
            return
        index = report["received"]
        report.update(received=index + 1, last_ns=mono)
        try:
            pending.put_nowait((index, mono, unix, msg))
        except queue.Full:
            report["queue_drops"] += 1
            raise RuntimeError("RGB writer queue overflow")

    def write():
        try:
            with (out / "rgb.csv").open("x", newline="") as f:
                w = csv.writer(f)
                w.writerow(["index", "mono_ns", "unix_ns", "header_ns"])
                while True:
                    item = pending.get()
                    if item is None:
                        break
                    idx, mono, unix, m = item
                    rgb = np.ndarray((480, 640, 3), dtype=np.uint8, buffer=m.data,
                                     strides=(m.step, 3, 1))
                    path = out / "rgb" / f"{idx:07d}.png"
                    if not cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                                       [cv2.IMWRITE_PNG_COMPRESSION, 1]):
                        raise IOError(path)
                    w.writerow((idx, mono, unix, m.header.stamp.sec * 10**9 + m.header.stamp.nanosec))
                    report["written"] += 1
                    if args.one:
                        stop.set()
        except Exception as exc:
            report["error"] = repr(exc)
            stop.set()

    def publish():
        tmp = out / "rgb.tmp"
        tmp.write_text(json.dumps(report))
        tmp.replace(out / "rgb_status.json")

    node.create_subscription(Image, TOPIC, receive,
                             QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
    worker = threading.Thread(target=write)
    worker.start()
    try:
        last = 0
        start = time.monotonic()
        while not stop.is_set():
            if args.one and time.monotonic()-start > 12:
                raise RuntimeError("No wrist image within 12 s. Check camera terminal.")
            rclpy.spin_once(node, timeout_sec=.1)
            now = time.monotonic()
            if now - last >= .2:
                count = node.count_publishers(TOPIC)
                if count > 1 or (report["received"] and count != 1):
                    raise RuntimeError(f"Wrist RGB publishers: {count}")
                publish()
                last = now
    except BaseException as exc:
        report["error"] = repr(exc)
        raise
    finally:
        while worker.is_alive():
            try:
                pending.put(None, timeout=.1)
                break
            except queue.Full:
                continue
        worker.join()
        publish()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    if report["error"]:
        raise RuntimeError(report["error"])


if __name__ == "__main__":
    main()
