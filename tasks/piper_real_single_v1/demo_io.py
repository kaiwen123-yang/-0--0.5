"""Field I/O using the installed PiperDevice, fixed H0 revision and its sender lock."""
import csv
import json
import math
import signal
import struct
import subprocess
import sys
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path("/home/kaiwen/research")
H0 = ROOT / "dog-and-arm/scripts"
H0_FIXED = ROOT / "pi-q12-data/20261122_start_diagnosis/h0-field/scripts"
CAL = "results/calibration-audit/20261122/ssh_multiview/wrist_rgb_calibration.json"
CAL_SHA = "479383a9e5945610c1585161e9225406b74738d5"
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
CLOCK = time.monotonic_ns
sys.path[:0] = [str(ROOT / "OSCBF-research"), str(H0_FIXED)]
from piper_oscbf.device import PiperDevice
import h0_operator_motion as h0


def save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def read(path):
    return json.loads(path.read_text())


def stats():
    folder = Path("/sys/class/net/can0/statistics")
    return {k: int((folder / k).read_text()) for k in
            ("tx_packets", "rx_packets", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped")}


def gap(q, other):
    return max(abs(math.degrees(a-b)) for a, b in zip(q, other, strict=True))


class Feedback:
    """Receive callback after the firmware parser. Never calls any send function."""
    def __init__(self, file):
        self.csv = csv.writer(file)
        self.csv.writerow(("kind", "id", "mono_ns", "first_ns", "wire_first_s", "wire_last_s",
                           "raw_hex", "values"))
        self.pending = []
        self.recent_joints = deque(maxlen=256)
        self.q = self.grip = self.joint_sample = None
        self.nq = self.ng = self.bad_groups = 0
        self.error = None

    def packet(self, frame):
        try:
            self._receive(frame)
        except Exception as exc:
            self.error = repr(exc)

    def _receive(self, frame):
        if frame.is_error_frame:
            self.error = "CAN error frame"
        if not frame.is_rx or frame.is_remote_frame or len(frame.data) != 8:
            return
        fid, ns, raw = frame.arbitration_id, CLOCK(), bytes(frame.data)
        if fid == 0x2A8:
            um, mn = struct.unpack(">ih", raw[:6])
            self.ng += 1
            self.grip = (ns, um * 1e-6)
            self.csv.writerow(("grip", self.ng, ns, ns, frame.timestamp, frame.timestamp,
                               raw.hex(), json.dumps([um * 1e-6, mn * .001, *raw[6:]])))
        if not 0x2A5 <= fid <= 0x2A7:
            return
        if fid != 0x2A5 + len(self.pending):
            self.pending.clear()
            self.bad_groups += 1
        if fid != 0x2A5 + len(self.pending):
            return
        self.pending.append((ns, frame.timestamp, raw))
        if len(self.pending) == 3:
            first, wire, _ = self.pending[0]
            data = b"".join(p[2] for p in self.pending)
            self.pending.clear()
            if not 0 <= frame.timestamp - wire < .005 or ns - first >= 5_000_000:
                self.bad_groups += 1
                return
            angles = [math.radians(v * .001) for v in struct.unpack(">iiiiii", data)]
            self.nq += 1
            self.q = (ns, angles)
            self.joint_sample = (self.nq, ns, angles)
            self.recent_joints.append(self.joint_sample)
            self.csv.writerow(("arm", self.nq, ns, first, wire, frame.timestamp,
                               data.hex(), json.dumps(angles)))

    def current(self):
        if self.error or not self.q or not self.grip:
            raise RuntimeError(f"Incomplete CAN reception: {self.error}")
        now = CLOCK()
        if max(now-self.q[0], now-self.grip[0]) >= 100_000_000:
            raise RuntimeError("Stale joint or gripper feedback")
        return self.q[1], self.grip[1]


class Sender:
    """One SDK comm for the arm and its gripper. H0 wraps the actual bus send."""
    def __init__(self, dev, grip, txfile, commands):
        self.dev, self.grip = dev, grip
        self.writer = csv.writer(txfile)
        self.writer.writerow(("start_ns", "end_ns", "command_id", "can_id", "data", "result", "error"))
        self.frames = []
        self.commands = commands
        self.count = 0
        self.command_id = "setup"
        self.bounds = None
        h0.log_calibration_submissions(dev.robot.get_context().get_comm(), self, self)

    @property
    def phase(self):
        return self.command_id

    def writerow(self, row):
        self.writer.writerow(row)
        self.frames.append(row)

    def call(self, kind, requested, fn, *, source=None):
        self.count += 1
        self.command_id = f"{self.count}:{kind}"
        self.frames = []
        item = dict(id=self.command_id, kind=kind, requested=requested, source=source,
                    start_ns=CLOCK(), result="incomplete")
        try:
            value = fn()
            ids = [int(f[3], 16) for f in self.frames]
            if not ids or any(f[5] != "host_submitted" for f in self.frames):
                raise RuntimeError(f"Missing host submission: {self.command_id}")
            if kind == "arm":
                if ids != [0x155, 0x156, 0x157]:
                    raise RuntimeError(f"Partial/unexpected joint transaction: {ids}")
                raw = b"".join(bytes.fromhex(f[4]) for f in self.frames)
                item["actual"] = [math.radians(i*.001) for i in struct.unpack(">iiiiii", raw)]
                if gap(requested, item["actual"]) > .00051:
                    raise RuntimeError("Unexpected SDK clamp or wire target")
            if kind == "grip":
                if ids != [0x159]:
                    raise RuntimeError(f"Unexpected gripper transaction: {ids}")
                raw = bytes.fromhex(self.frames[0][4])
                um, mn = struct.unpack(">iH", raw[:6])
                if (um, mn, raw[6]) != (round(requested[0]*1e6), round(requested[1]*1e3), 1):
                    raise RuntimeError("Unexpected gripper wire target")
                item.update(actual=um * 1e-6, force_N=mn * .001)
            item.update(result="host_submitted", submitted_ns=self.frames[-1][1])
            return value
        except BaseException as exc:
            item["error"] = repr(exc)
            raise
        finally:
            item["frames"] = len(self.frames)
            self.commands.write(json.dumps(item) + "\n")

    def arm(self, q, source):
        for value, (lo, hi) in zip(q, self.bounds, strict=True):
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError("Measured path outside controller or SDK bounds")
        self.call("arm", q, lambda: self.dev.robot.move_j(list(q)), source=source)

    def width(self, width, force, source, *, gripper_basis=None):
        if gripper_basis is not None:
            from width_contract import WIDTH
            if gripper_basis != WIDTH or not .015 <= width <= .040 or not 0 < force <= 1.:
                raise ValueError("Unknown SDK width contract or target outside verified settings")
        self.call("grip", [width, force],
                  lambda: self.grip.move_gripper_m(value=width, force=force), source=source)

    def limits(self):
        bounds = []
        for j in range(1, 7):
            requested = time.time()
            result = self.call("read_limit", j, lambda: self.dev.robot.get_joint_angle_vel_limits(j))
            if not result or result.timestamp < requested:
                raise RuntimeError(f"Missing new J{j} limit reply")
            lo, hi = result.msg.min_angle_limit, result.msg.max_angle_limit
            sdk = self.dev.robot.get_config()["joint_limits"][f"joint{j}"]
            if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
                raise ValueError(f"Invalid controller J{j} limits")
            speed = result.msg.max_joint_spd
            if not math.isfinite(speed) or speed <= 0:
                raise ValueError(f"J{j} has no positive controller speed limit")
            bounds.append(dict(joint=j, received_unix_s=result.timestamp, controller=[lo, hi],
                               max_rad_s=speed,
                               sdk=sdk, usable=[max(lo,sdk[0]), min(hi,sdk[1])]))
        self.bounds = [r["usable"] for r in bounds]
        return bounds


def snapshot(dev, rx, grip):
    q, width = rx.current()
    status = dev.robot.get_arm_status()
    drives = [dev.robot.get_driver_states(j) for j in range(1, 7)]
    gr = grip.get_gripper_status()
    if not all(m and 0 <= time.time()-m.timestamp < .2 for m in [status, gr, *drives]):
        raise RuntimeError("Stale controller, gripper or drive status")
    return dict(mono_ns=CLOCK(), q_rad=q, width_m=width, arm=status.msg.to_dict(),
                drives=[m.msg.foc_status.to_dict() for m in drives], gripper=gr.msg.to_dict())


def healthy(dev, rx, grip, *, allow_disabled_gripper=False):
    row = snapshot(dev, rx, grip)
    st = row["arm"]
    if (st["ctrl_mode"], st["arm_status"], st["mode_feedback"]) != (1, 0, 1):
        raise RuntimeError(f"Not healthy CAN/MOVE_J: {st}")
    issues = h0.calibration_driver_issues(dev, st)
    flags = row["gripper"]["foc_status"]
    if issues or row['gripper']['mode'] != 'width' or (not allow_disabled_gripper and not flags["driver_enable_status"]) or any(
            v for k,v in flags.items() if k not in ("homing_status", "driver_enable_status")):
        raise RuntimeError(f"Drive/gripper status: {issues} {flags}")
    return row


@contextmanager
def camera(directory):
    with (directory / "camera.log").open("x") as f:
        proc = subprocess.Popen(["bash", str(H0 / "h0_ros_env.sh"), "/usr/bin/python3",
                                 str(HERE / "demo_rgb.py"), str(directory)],
                                stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        path = directory / "rgb_status.json"

        def check():
            row = read(path)
            if (proc.poll() is not None or row["error"] or row["boot_id"] != BOOT or
                    row["written"] == 0 or CLOCK() - row["last_ns"] > 650_000_000):
                raise RuntimeError(f"RGB recording unavailable: {row}")

        try:
            start = time.monotonic()
            while not (path.is_file() and read(path)["written"]):
                if proc.poll() is not None or time.monotonic()-start > 12:
                    raise RuntimeError(f"No wrist images. See {directory}/camera.log")
                time.sleep(.05)
            check()
            yield check
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
            if proc.wait() != 0:
                raise RuntimeError(f"Camera writer failed: {directory}/camera.log")
