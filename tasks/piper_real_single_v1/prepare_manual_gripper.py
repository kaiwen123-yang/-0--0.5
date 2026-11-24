"""Release only the empty gripper before a hand-guided opening-width recording."""
import argparse
import fcntl
import json
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from demo_io import BOOT, CLOCK, Feedback, PiperDevice, Sender, gap, h0, healthy, read, save, snapshot, stats
from width_contract import require_setup


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("session", type=Path)
    cli.add_argument("--in-teach", action="store_true",
                     help="在已进入实体示教且空爪停稳时，仅放松夹爪")
    args = cli.parse_args()
    session = args.session.resolve()
    setup = read(session / "setup.json")
    require_setup(setup)
    if setup["session_id"] != read(session / "session.json")["session_id"]:
        raise ValueError("Session identity differs from the formal setup")

    with ExitStack() as stack:
        lock = stack.enter_context(open("/tmp/dog_and_arm_piper_motion.lock", "a"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = session / "hold.json"
        held = read(ledger)
        ifindex_file = Path("/sys/class/net/can0/ifindex")
        before = stats()
        if (held["boot_id"] != BOOT or held["ifindex"] != int(ifindex_file.read_text())
                or held["tx_packets"] != before["tx_packets"]):
            raise RuntimeError("Current CAN interface or TX count differs from arm hold")
        command_file = Path(held["command_file"]).resolve()
        if (command_file.parent.parent != session or command_file.name != "commands.jsonl"
                or command_file.parent.name != held["run"]):
            raise RuntimeError("Arm command source does not belong to this session hold")
        source = read(command_file.parent / "run.json")
        if not source["complete"] or source["boot_id"] != BOOT or source["session"] != session.name:
            raise RuntimeError("Incomplete or unrelated held arm source")
        with command_file.open() as f:
            arms = [cmd for line in f if (cmd := json.loads(line))["kind"] == "arm"]
        if (not arms or arms[-1]["result"] != "host_submitted" or arms[-1]["frames"] != 3
                or gap(arms[-1]["actual"], held["q"]) > .00051):
            raise RuntimeError("Held position differs from the last submitted arm command")

        out = session / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_manual_gripper_prepare")
        out.mkdir()
        print(out, flush=True)
        feedback = stack.enter_context((out / "feedback.csv").open("x", newline=""))
        tx = stack.enter_context((out / "tx.csv").open("x", newline="", buffering=1))
        commands = stack.enter_context((out / "commands.jsonl").open("x", buffering=1))
        dev = PiperDevice()
        dev.feedback, dev.driver_feedback = deque(maxlen=256), deque(maxlen=256)
        grip = dev.robot.init_effector("agx_gripper")
        rx = Feedback(feedback)
        gripper_bits = deque(maxlen=2048)

        def receive(frame):
            rx.packet(frame)
            if (frame.is_rx and not frame.is_remote_frame and not frame.is_error_frame
                    and frame.arbitration_id == 0x2A8 and len(frame.data) == 8):
                gripper_bits.append((CLOCK(), frame.timestamp, bool(frame.data[6] & 0x40)))

        dev.robot.get_context().register_parser_packet_fun(receive)
        report = dict(kind="manual_gripper_prepare", use="preparation_only", session=session.name,
                      session_id=setup["session_id"], boot_id=BOOT, hold_before=held,
                      interface_before=before, in_teach=args.in_teach, complete=False)
        count = 0
        try:
            dev.connect()
            stack.callback(dev.disconnect)
            sender = Sender(dev, grip, tx, commands)
            def read_ready_pose():
                if not args.in_teach:
                    row = healthy(dev, rx, grip, allow_disabled_gripper=True)
                    if row["arm"]["motion_status"] != 0:
                        raise RuntimeError("Arm has not reached the held CAN target")
                    return row
                row = snapshot(dev, rx, grip)
                st = row["arm"]
                flags = row["gripper"]["foc_status"]
                issues = h0.calibration_driver_issues(dev, st, require_can=False)
                if (st["ctrl_mode"] != 2 or st["teach_status"] != 1 or st["arm_status"] not in (0, 11)
                        or issues or row["gripper"]["mode"] != "width"
                        or any(v for k,v in flags.items() if k not in ("homing_status", "driver_enable_status"))):
                    raise RuntimeError(f"Physical teaching or gripper status changed: {st}, {issues}, {flags}")
                return row

            first = read_ready_pose()
            report["initial"] = first
            time.sleep(.25)

            def stationary():
                row = read_ready_pose()
                if (gap(row["q_rad"], first["q_rad"]) > .1
                        or gap(row["q_rad"], held["q"]) > .35):
                    raise RuntimeError("Arm has moved from its stationary hold")
                return row
            row = stationary()
            if (int(ifindex_file.read_text()) != held["ifindex"]
                    or stats()["tx_packets"] != before["tx_packets"]):
                raise RuntimeError("Interface or TX count changed before release")

            if row["gripper"]["foc_status"]["driver_enable_status"]:
                sender.call("gripper_disable", 0, grip.disable_gripper, source="manual_finger_teaching")
                if (len(sender.frames) != 1 or int(sender.frames[0][3], 16) != 0x159
                        or bytes.fromhex(sender.frames[0][4]) != bytes(8)):
                    raise RuntimeError("Unexpected gripper release submission")
                count = 1
            sent_wall, sent_mono = time.time(), CLOCK()
            deadline = time.monotonic() + 2.5
            while True:
                row = stationary()
                message = grip.get_gripper_status()
                samples = [(ns, enabled) for ns, wire, enabled in list(gripper_bits)
                           if ns > sent_mono and wire > sent_wall]
                continuous_ns = 0
                if samples and not samples[-1][1]:
                    start_ns = samples[-1][0]
                    for ns, enabled in reversed(samples[:-1]):
                        if enabled or start_ns - ns > 100_000_000:
                            break
                        start_ns = ns
                    continuous_ns = samples[-1][0] - start_ns
                report.update(final=row, fresh_gripper_frames=len(samples),
                              enabled_gripper_frames=sum(enabled for _, enabled in samples),
                              continuous_disabled_ms=round(continuous_ns / 1e6, 3))
                if (continuous_ns >= 350_000_000 and message and message.timestamp > sent_wall
                        and not message.msg.foc_status.driver_enable_status
                        and not row["gripper"]["foc_status"]["driver_enable_status"]):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Gripper release unconfirmed: {report['enabled_gripper_frames']}/"
                                       f"{len(samples)} new frames enabled, width {row['width_m']*1000:.1f} mm")
                time.sleep(.02)
            report.update(complete=True, actual_width_mm=round(row["width_m"] * 1000, 3))
        except BaseException as exc:
            report.update(complete=False, error=repr(exc))
            raise
        finally:
            after = stats()
            report.update(interface_after=after, expected_gripper_frames=count)
            accounted = (int(ifindex_file.read_text()) == held["ifindex"]
                         and after["tx_packets"] - before["tx_packets"] == count
                         and read(ledger) == held)
            if not accounted:
                report["complete"] = False
                report["accounting_error"] = "CAN ledger changed or unexpected host frame"
            save(out / "run.json", report)
            if accounted and count:
                save(ledger, dict(held, tx_packets=after["tx_packets"]))
            if not accounted:
                raise RuntimeError(report["accounting_error"])
        print(f"夹爪驱动已失能，实际开口 {report['actual_width_mm']} mm，夹爪发送 {count} 帧。", flush=True)


if __name__ == "__main__":
    main()
