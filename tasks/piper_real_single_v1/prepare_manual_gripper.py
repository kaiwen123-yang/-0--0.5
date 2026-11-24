"""Release only the empty gripper before a hand-guided opening-width recording."""
import argparse
import fcntl
import json
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from demo_io import BOOT, CLOCK, Feedback, PiperDevice, Sender, gap, healthy, read, save, stats
from width_contract import require_setup


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("session", type=Path)
    session = cli.parse_args().session.resolve()
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
        dev.robot.get_context().register_parser_packet_fun(rx.packet)
        report = dict(kind="manual_gripper_prepare", use="preparation_only", session=session.name,
                      session_id=setup["session_id"], boot_id=BOOT, hold_before=held,
                      interface_before=before, complete=False)
        count = 0
        try:
            dev.connect()
            stack.callback(dev.disconnect)
            sender = Sender(dev, grip, tx, commands)
            first = healthy(dev, rx, grip, allow_disabled_gripper=True)
            report["initial"] = first
            time.sleep(.25)
            def stationary():
                row = healthy(dev, rx, grip, allow_disabled_gripper=True)
                if (row["arm"]["motion_status"] != 0 or gap(row["q_rad"], first["q_rad"]) > .1
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
                if (message and message.timestamp > sent_wall and rx.grip[0] > sent_mono
                        and not message.msg.foc_status.driver_enable_status
                        and not row["gripper"]["foc_status"]["driver_enable_status"]):
                    report["final"] = row
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Fresh gripper feedback did not confirm drive release")
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
