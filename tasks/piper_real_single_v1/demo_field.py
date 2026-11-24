"""一次手拖真实抓放：C 控制夹爪闭合，O 张开，E 成功保存并独立回零。"""
import argparse
import csv
import fcntl
import json
import math
import os
import select
import signal
import sys
import termios
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from itertools import groupby
from pathlib import Path
from uuid import uuid4

from demo_io import (BOOT, CAL, CAL_SHA, CLOCK, HERE, ROOT, Feedback, PiperDevice,
                     Sender, camera, gap, h0, healthy, read, save, snapshot, stats)
from demo_path import plan
from demo_home import ZERO, first_home_target, handoff_at_measured_pose, ramp_joints, released_pose
from color_task import COLORS, recorded_task, task_for
from width_contract import WIDTH, RETREAT, TERMINAL_VERSION, require_setup


def agree(prompt):
    if input(prompt + "  输入 yes 并回车（大小写均可）：").strip().lower() != "yes":
        raise ValueError("操作员未确认")


def line():
    if select.select([sys.stdin], [], [], 0)[0]:
        value = sys.stdin.readline()
        if not value:
            raise EOFError("现场终端已断开")
        return value.strip().lower()
    return None


def main(argv=None, *, finished_run=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    sub.add_parser("status", help="读取两秒实测反馈；TX=0")
    sub.add_parser("limits", help="仅查询六轴当前控制器限位")
    modes = {"return-start": "沿已执行空场目标倒序返回，保持夹爪张开", "restart-teach": "重新建立本次实测保持位并复开夹爪", "prepare-pads": "以实测指垫端点接续联调（只接收）", "prepare": "建立本次起点，核实开口", "width-check": "单点空夹卡尺核查",
             "teach": "一次手拖真实抓放：C 闭合、O 张开、E 成功结束并回零", "empty": "移走方块后核查新路径",
             "block": "按原布局抓放一次"}
    modes.update({"home": "停止示教后经 SDK 自动回到六轴零位，独立保存回程",
                  "next-teach": "从零位准备下一组示教，适用于上一组完成或重录",
                  "prepare-formal": "沿用同一安装的卡尺记录，在新会话建立近起点保持",
                  "anchor-start": "被动重定位并退出示教后，近起点交接与同位锚定"})
    for kind, help_text in modes.items():
        sp = sub.add_parser(kind, help=help_text)
        sp.add_argument("session", type=Path)
        if kind == "home":
            sp.add_argument("--from-zero-pose", action="store_true", help="从现场已摆好的六轴零位姿态收齐传感器余差")
        if kind == "prepare-formal":
            sp.add_argument("held_session", type=Path, help="拥有当前真实保持记录的会话")
        if kind == "prepare-pads":
            sp.add_argument("--first-open-mm", required=True, type=float, help="首次张开独立卡尺净距")
            sp.add_argument("--object-mm", required=True, type=float, help="同一夹持方向的实物宽")
        if kind == "width-check":
            sp.add_argument("target_mm", type=float, help="本次空夹目标 mm，15 至 40")
        if kind in ("restart-teach", "next-teach"):
            sp.add_argument("--inside-start", action="store_true", default=kind == "next-teach",
                            help="从零位进入公共起点 J2 +2°、J3 −2°")
        if kind == "teach":
            sp.add_argument("placement", help="摆放编号")
            sp.add_argument("--start-marker", action="store_true",
                            help="被动预录期间复原布局，在实体示教的公共起点按 S 开始任务窗口")
            sp.add_argument("--passive-capture", action="store_true",
                            help="从实测起点被动记录三路数据和驱动状态，C/O 仅对实际事件打标")
            sp.add_argument("--manual-gripper", action="store_true",
                            help="手动夹指，C/O 仅标记，完整记录实测开口")
        if kind in ("teach", "block"):
            sp.add_argument("--target-color", choices=COLORS, help="该条真实指令的唯一目标")
            sp.add_argument("--scene-colors", nargs="+", choices=COLORS, help="实际混摆，各色一块")
        if kind == "block":
            sp.add_argument("--formal", action="store_true", help="首批逐条质检通过后采正式示范")
    a = p.parse_args(argv)
    kind = a.kind
    passive = kind == "teach" and a.passive_capture
    manual_gripper = kind == "teach" and (a.manual_gripper or passive)
    if kind == "teach" and a.start_marker and not passive:
        p.error("--start-marker 仅用于 --passive-capture")
    if kind == "width-check" and not 15 <= a.target_mm <= 40:
        p.error("单点空夹目标须在 15–40 mm 内")
    if kind not in ("status", "limits") and not sys.stdin.isatty():
        p.error("在能观察机械臂的交互终端运行")
    session = getattr(a, "session", ROOT / "pi-q12-data/pi-demo-checks").resolve()
    task = None
    if kind in ("teach", "block"):
        formal_setup = "terminal_kind" in read(session / "setup.json")
        if kind == "teach" and not formal_setup:
            p.error("一次真实示范请使用已准备的 T01/T02/V01 正式会话，并指定目标与场景颜色")
        if formal_setup or a.target_color or a.scene_colors:
            if not formal_setup or not a.target_color or not a.scene_colors:
                p.error("正式示教/实物运行须指定 --target-color 与 --scene-colors，并已完成 prepare-formal")
            if kind == "block" and not a.formal:
                p.error("此正式会话的实物运行须加 --formal")
            task = task_for(a.target_color, a.scene_colors)
    if kind == "prepare":
        session.mkdir(parents=True)
    elif kind in ("status", "limits"):
        session.mkdir(exist_ok=True)
    if not session.is_dir():
        p.error("先运行 prepare 建立新会话")
    run = session / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + kind)
    run.mkdir()
    print("记录目录", run, flush=True)
    report = dict(kind=kind, run_id=str(uuid4()), session=session.name, boot_id=BOOT,
                  calibration=CAL, calibration_commit=CAL_SHA, camera_mount="wrist",
                  camera_id="CC16762023M", complete=False, use="commissioning_only",
                  interface_before=stats(), started_unix_ns=time.time_ns())
    if getattr(a, "formal", False):
        report["use"] = "formal"
        report["requested_task"] = task
    active = False
    dev = rx = grip = sender = None
    led = session / "hold.json"
    source_file = session / "source.json"
    clear_file = session / "empty.json"

    def normal_hold(q):
        # Use the actual submitted target. At a rejected arrival, the narrow H0
        # quiet-window path may end the run in powered hold without a damping stop.
        nonlocal active
        try:
            h0.calibration_arrival(dev, q)
        except h0.CalibrationArrivalTimeout:
            measured, motor, status = h0.observe_timeout_hold(dev, q)
            if status["motion_status"] == 1:
                sender.arm(measured, "timeout_measured_hold")
                h0.observe_timeout_hold(dev, measured, sent_at=time.time(), motor_anchor=motor)
            active = False
            report["stop"] = "rejected_target_powered_hold"
            raise

    def limits():
        result = sender.limits()
        report["limits"] = result
        return sender.bounds

    def record_hold(q):
        save(led, dict(boot_id=BOOT, q=q, ifindex=int(Path("/sys/class/net/can0/ifindex").read_text()),
                       tx_packets=stats()["tx_packets"],
                       run=run.name, command_file=str(run / "commands.jsonl")))

    def ledger_target(ledger, *, strict):
        h = read(ledger)
        link_index = int(Path("/sys/class/net/can0/ifindex").read_text())
        if (h["boot_id"] != BOOT or h["tx_packets"] != stats()["tx_packets"]
                or h.get("ifindex",link_index) != link_index):
            raise RuntimeError("保持目标的 boot/TX 计数已变化，请重新建立本次起点")
        if strict:
            if h.get("ifindex") != link_index:
                raise RuntimeError("当前接口身份缺失或变化")
            commands = Path(h["command_file"])
            with commands.open() as f:
                arm = [c for line in f if (c := json.loads(line))["kind"] == "arm"]
            if (not arm or arm[-1]["result"] != "host_submitted" or arm[-1]["frames"] != 3
                    or gap(arm[-1]["actual"], h["q"]) > .00051):
                raise RuntimeError("保持账本与末次真实六轴提交不符")
        return h["q"]

    def previous_hold(ledger=led, *, strict=False):
        target = ledger_target(ledger, strict=strict)
        if gap(rx.current()[0], target) > .35:
            raise RuntimeError("实测姿态距先前有提交记录的起点超过 0.35°")
        return target

    def home():
        nonlocal active
        cfg = read(session/"setup.json")
        require_setup(cfg)
        held = ledger_target(led, strict=True)
        row = released_pose(dev, rx, grip)
        start, width = row["q_rad"], row["width_m"]
        report.update(use="reposition_only", session_id=cfg["session_id"], previous_hold=read(led))
        if finished_run is not None:
            prior = read(finished_run/"run.json")
            release = prior["home_release"]
            hold_run = prior["initial_hold_run"] if prior["kind"] == "teach" else finished_run.name
            if (prior["boot_id"] != BOOT or prior["session_id"] != cfg["session_id"]
                    or hold_run != read(led)["run"]
                    or prior["interface_after"]["tx_packets"] != report["interface_before"]["tx_packets"]
                    or release["ifindex"] != read(led)["ifindex"]
                    or gap(release["q_rad"], start) > .1 or abs(release["width_m"]-width) > .001):
                raise ValueError("结束示教与自动回零之间的姿态、开口或控制来源发生变化")
            report.update(source_trajectory_id=prior.get("source_trajectory_id", prior["run_id"]),
                          source_directory=prior.get("source_directory", str(finished_run)),
                          source_complete=prior["complete"], completed_run_id=prior["run_id"],
                          completed_run_kind=prior["kind"])
        if row["arm"]["ctrl_mode"] == 1 and gap(start,ZERO) <= .01 and gap(held,ZERO) <= .00051:
            normal_hold(ZERO)
            ledger_target(led, strict=True)
            # Keep the real command file for the already-held zero.
            if finished_run is not None:
                save(led, dict(read(led), run=run.name))
            report.update(stop="arrived_powered_hold", already_home=True)
            return
        if finished_run is None:
            agree("灯灭，空爪，人手与工具已离开回程范围。执行独立低速回零")
        before = stats()["tx_packets"]
        ledger_target(led, strict=True)
        bounds = limits()
        if stats()["tx_packets"] != before+6 or read(led)["ifindex"] != int(Path("/sys/class/net/can0/ifindex").read_text()):
            raise RuntimeError("限位查询期间接口或主机 TX 改变")
        save(led, dict(read(led), tx_packets=before+6))
        first = first_home_target(start, bounds, from_zero_pose=a.from_zero_pose)
        report["from_operator_zero_pose"] = a.from_zero_pose
        report.update(return_path="direct_joint_segment", home_waypoints_rad=[first, ZERO])
        fresh = released_pose(dev, rx, grip)
        if (fresh["arm"] != row["arm"] or gap(fresh["q_rad"],start) > .1
                or abs(fresh["width_m"]-width) > .001 or line() in ("p","e")):
            raise ValueError("起姿改变或操作员结束，取消本次回零")
        ledger_target(led, strict=True)
        active = True
        handoff_at_measured_pose(dev, rx, grip, sender, fresh["arm"], start, first, report)
        state = healthy(dev,rx,grip,allow_disabled_gripper=True)
        if min(gap(state["q_rad"],start), gap(state["q_rad"],first)) > .5:
            raise RuntimeError("交接后偏离实测起姿")
        if fresh["arm"]["ctrl_mode"] == 1:
            sender.arm(first,"fresh_home_anchor_in_CAN")
        normal_hold(first)
        sender.move_j_mode(50, kind="home_mode")
        time.sleep(.15)
        speed = min(3., *(math.degrees(m["max_rad_s"]) for m in report["limits"]))
        report.update(sdk_speed_percent=50, reference_deg_s=speed, reference_deg_s2=8)
        print(f"SDK 50% 档回零，参考最高 {speed:g}°/s，夹爪保持。P 或 E 回车会在当前参考位结束。", flush=True)
        target, completed = ramp_joints(dev,rx,grip,sender,first,ZERO,width,speed,
                                       lambda: line() in ("p","e"),"home_from_fresh_feedback",
                                       profile="trapezoid")
        normal_hold(target)
        final = healthy(dev,rx,grip,allow_disabled_gripper=True)
        if gap(final["q_rad"],target) > .35 or final["arm"]["motion_status"] != 0 or abs(final["width_m"]-width) > .002:
            raise RuntimeError("末次到位或夹爪反馈不符")
        record_hold(target)
        active = False
        if not completed:
            report["stop"] = "operator_ended_in_hold"
            raise ValueError("操作员结束回程，已保持实测目标")
        report["stop"] = "arrived_powered_hold"

    def physical_width(label, *, require_match=True):
        value = float(input(label + " 从侧面用标尺读两指内侧总间距（mm）：")) / 1000
        actual = rx.current()[1]
        if not math.isfinite(value) or not 0 <= value <= .1:
            raise ValueError("尺读必须为 0–100 mm 的有限数值")
        within = abs(actual-value) <= .002
        report.setdefault("opening_checks", []).append(dict(
            phase=label, ruler_m=value, feedback_m=actual, mono_ns=CLOCK(),
            feedback_minus_ruler_m=actual-value, within_2_mm=within))
        if require_match and not within:
            raise ValueError(f"尺读 {value*1000:.2f} mm，反馈 {actual*1000:.2f} mm，相差超过 2 mm")

    def grip_at(width, force, label, require_width, *, enable_on_open=False):
        sender.width(width, force, label, gripper_basis=WIDTH if report.get("terminal_kind") == RETREAT else None)
        sent = CLOCK()
        deadline = time.monotonic()+2.5
        while time.monotonic() < deadline:
            row = healthy(dev, rx, grip, allow_disabled_gripper=enable_on_open)
            if (row["gripper"]["foc_status"]["driver_enable_status"] and rx.grip[0] > sent + 800_000_000 and
                    (not require_width or abs(row["width_m"]-width) <= .002)):
                return row["width_m"]
            time.sleep(.02)
        raise RuntimeError(f"夹爪 {label} 无合格的新反馈")

    def check_width():
        report["use"] = "gripper_metrology_only"
        target = a.target_mm / 1000
        base = healthy(dev, rx, grip)["q_rad"]
        h0.calibration_arrival(dev, base)
        agree(f"夹爪空载、卡尺与人手已撤离。单次目标 {a.target_mm:g} mm，力 1 N")
        current = healthy(dev, rx, grip)
        if gap(base, current["q_rad"]) > .1 or current["arm"]["motion_status"] != 0:
            raise RuntimeError("单点检查前机械臂偏离保持位")
        grip_at(target, 1., "caliper_check", True)
        # The SDK keeps this single gripper command. This measurement sends
        # no arm command and never marks a teaching/replay session ready.
        widths = []
        until = time.monotonic() + .5
        while time.monotonic() < until:
            row = healthy(dev, rx, grip)
            if gap(base, row["q_rad"]) > .1 or row["arm"]["motion_status"] != 0:
                raise RuntimeError("空夹检查期间机械臂姿态变化")
            widths.append(row["width_m"])
            time.sleep(.01)
        report["settled_feedback_m"] = [min(widths), max(widths)]
        print("半秒反馈范围 (mm)", [round(v*1000, 2) for v in report["settled_feedback_m"]], flush=True)
        physical_width("caliper_check", require_match=False)

    def prepare():
        nonlocal active
        base = healthy(dev, rx, grip)["q_rad"]
        h0.calibration_arrival(dev, base)
        bounds = limits()
        if any(not lo <= x <= hi for x,(lo,hi) in zip(base,bounds)):
            raise ValueError("当前姿态超限")
        if max(map(abs, base)) > math.radians(5):
            raise ValueError("首批灯灭交接依照 H0 近零范围，现场另行确定起点")
        print("历史台架范围 15–40 mm、1 N。按实际方块选择此次目标；先空夹测量。")
        op = float(input("OPEN 总开口 mm：")) / 1000
        cl = float(input("CLOSE 总开口 mm：")) / 1000
        force = float(input("现场核实适用的力 N："))
        if not .015 <= cl < op <= .040 or not 0 < force <= 1:
            raise ValueError("首批仅使用 H0 台架范围内的开口、力度")
        physical_width("初始")
        agree("夹爪空载，手和标尺已撤离，将下发当前实测位置保持，并张开夹爪。")
        q = healthy(dev, rx, grip)["q_rad"]
        if gap(q, base) > .1:
            raise RuntimeError("准备期间起点移动")
        h0.calibration_arrival(dev,q)
        active = True
        sender.arm(q, "measured_stationary_anchor")
        normal_hold(q)
        for name,width in (("open", op), ("close", cl), ("reopen", op)):
            if name != "open":
                agree("移开标尺及人手，准备执行 " + name)
            active = True
            grip_at(width, force, name, True)
            # Once a powered hold is established, a rejected ruler reading
            # terminates preparation in place.
            active = False
            physical_width(name)

        cfg = dict(open_m=op, close_m=cl, force_N=force, session_id=report["run_id"],
                   opening_checks=report["opening_checks"])
        save(session / "setup.json", cfg)
        record_hold(q)

    def prepare_pads():
        # Recover only a known submitted hold after an opening metrology rejection.
        # Each following TX must belong to a completed, gripper-only measurement.
        if (session/"setup.json").exists() or led.exists():
            raise ValueError("该会话已有准备结果")
        first, = session.glob("*_prepare")
        initial = read(first/"run.json")
        if (initial["complete"] or initial["boot_id"] != BOOT or
                "尺读" not in initial.get("error","") or "2 mm" not in initial["error"]):
            raise ValueError("需要同一次启动下因开口尺读超差而结束的准备记录")
        def commands(path, data):
            with (path/"commands.jsonl").open() as f:
                items = [json.loads(line) for line in f]
            with (path/"tx.csv").open() as f:
                frames = list(csv.DictReader(f))
            if (not frames or any(r["result"] != "host_submitted" for r in items+frames)
                    or sum(r["frames"] for r in items) != len(frames)
                    or data["interface_after"]["tx_packets"]-data["interface_before"]["tx_packets"] != len(frames)):
                raise ValueError("提交记录与实际接口计数不一致")
            return items
        original = commands(first, initial)
        if [r["kind"] for r in original] != ["read_limit"]*6+["arm","grip"]:
            raise ValueError("原准备记录的关节保持或张开来源不明确")
        anchor, opening = original[-2:]
        if anchor["source"] != "measured_stationary_anchor" or opening["source"] != "open":
            raise ValueError("缺少当前实测保持与首次张开提交")
        open_m, force = opening["actual"], opening["force_N"]
        points = [dict(run=first.name, target_m=open_m, pad_gap_m=a.first_open_mm/1000)]
        tx_count = initial["interface_after"]["tx_packets"]
        for path in sorted(session.glob("*_width-check")):
            data = read(path/"run.json")
            if (data["boot_id"] != BOOT or not data["complete"] or
                    data["interface_before"]["tx_packets"] != tx_count):
                raise ValueError("卡尺核查会话间有未追溯的 TX 或时钟变化")
            cmd, = commands(path,data)
            if cmd["kind"] != "grip" or cmd["force_N"] != force:
                raise ValueError("两次测量间有其他动作或力设置")
            check, = data["opening_checks"]
            points.append(dict(run=path.name,target_m=cmd["actual"],pad_gap_m=check["ruler_m"],
                               sdk_width_m=check["feedback_m"]))
            tx_count = data["interface_after"]["tx_packets"]
        closing = min(points,key=lambda pt:pt["target_m"])
        repeated = points[-1]
        object_m = a.object_mm/1000
        if (len({pt["target_m"] for pt in points}) < 3 or repeated["target_m"] != open_m or
                abs(repeated["pad_gap_m"]-points[0]["pad_gap_m"]) > .002 or
                not all(0 < pt["pad_gap_m"] <= .1 for pt in points) or
                not closing["pad_gap_m"] < object_m < min(repeated["pad_gap_m"],points[0]["pad_gap_m"])):
            raise ValueError("需要实测闭合端、中间点、可重复张开端，并覆盖方块宽度")
        now = healthy(dev,rx,grip)
        if (stats()["tx_packets"] != tx_count or gap(now["q_rad"],anchor["actual"]) > .35 or
                abs(now["width_m"]-open_m) > .002):
            raise ValueError("当前姿态、夹爪或目标来源发生变化")
        h0.calibration_arrival(dev,anchor["actual"])
        if stats()["tx_packets"] != tx_count:
            raise ValueError("建立只读接续期间出现额外主机 TX")
        cfg = dict(session_id=report["run_id"],open_m=open_m,close_m=closing["target_m"],
                   force_N=force,object_m=object_m,gripper_basis="sdk_width_m_with_separate_caliper_endpoints",
                   commissioning_only=True,pad_measurements=points)
        save(led,dict(boot_id=BOOT,q=anchor["actual"],tx_packets=tx_count,
                      run=first.name,command_file=str(first/"commands.jsonl")))
        save(session/"setup.json",cfg)
        report.update(source_hold=anchor["id"], pad_measurements=points, object_m=object_m)

    def align_from_home(target, width, source):
        nonlocal active
        row = healthy(dev,rx,grip)
        start = row["q_rad"]
        if (gap(start,ZERO) > .35 or row["arm"]["motion_status"] != 0
                or any(not lo <= v <= hi for v,(lo,hi) in zip(target,sender.bounds,strict=True))):
            raise ValueError("公共起点准备需要 CAN 保持在零位，目标在控制器范围内")
        if gap(start,target) > .01:
            speed = min(3., *(math.degrees(m["max_rad_s"]) for m in report["limits"]))
            active = True
            sender.move_j_mode(5, kind="positioning_mode")
            final,done = ramp_joints(dev,rx,grip,sender,start,target,width,speed,
                                     lambda: line() in ("p","e"),source,profile="trapezoid")
            normal_hold(final)
            record_hold(final)
            active = False
            if not done:
                raise ValueError("已在当前参考位结束公共起点准备")
        else:
            active = True
            sender.arm(target,source)
            normal_hold(target)
            record_hold(target)
            active = False

    def restart_teach():
        nonlocal active
        cfg = read(session/"setup.json")
        old = read(led)
        next_group = kind == "next-teach"
        if not next_group and old["boot_id"] != BOOT:
            raise ValueError("需要本次启动下的会话")
        formal = cfg.get("commissioning_only") is False
        if formal:
            require_setup(cfg)
            prep = read(session/cfg["prepare_run"]/"run.json")
            pending = read(source_file).get("pending") if source_file.exists() else None
            taught = read(session/pending/"run.json") if pending else {}
            if (prep.get("kind") != "prepare-formal" or not prep.get("complete")
                    or prep.get("session_id") != cfg["session_id"]
                    or (not next_group and (prep.get("boot_id") != BOOT
                        or taught.get("kind") != "teach" or taught.get("complete") is not False
                        or taught.get("session_id") != cfg["session_id"]))):
                raise ValueError("正式重录需要已建立的起点和同会话未完成的示教")
            report.update(use="reposition_only", gripper_basis=WIDTH, terminal_kind=RETREAT,
                          prior_teach=taught.get("run_id"), prepare_run=cfg["prepare_run"])
        elif cfg.get("commissioning_only") is not True:
            raise ValueError("未知会话合同")
        if a.inside_start and not formal:
            raise ValueError("界内起点用于正式会话")
        width, force = cfg["open_m"], cfg["force_N"]
        if not .015 <= cfg["close_m"] < width <= .040 or not 0 < force <= 1:
            raise ValueError("当前开口或力度配置超出已核实范围")
        expected = ZERO if next_group else (prep["final"]["q_rad"] if formal else old["q"])
        if source_file.exists() and not next_group:
            src = read(source_file)
            if src.get("retreat_window"):
                # Terminal hold and intended *next* start are distinct. This
                # command must see the manually restored start before any TX.
                taught = read(session/src["run"]/"run.json")
                if src["retreat_window"]["source_id"] != taught["run_id"]:
                    raise ValueError("Source trajectory identity mismatch")
                expected = taught["marks"][0]["q"]
        row = healthy(dev, rx, grip, allow_disabled_gripper=formal)
        start = row["q_rad"]
        if row["arm"]["motion_status"] != 0 or gap(start,expected) > .35:
            raise ValueError("先在现场恢复到既有起点并确认 CAN/MOVE_J 到位")
        report.update(previous_hold=old, expected_open_m=width)
        h0.calibration_arrival(dev,start)
        next_position = "，再低速进入 J2 +2°、J3 −2° 公共起点" if a.inside_start else ""
        agree(f"已退出示教，空载，手和工具已移开。在当前实测位置保持，复开至 {width*1000:g} mm{next_position}")
        row = healthy(dev, rx, grip, allow_disabled_gripper=formal)
        if gap(row["q_rad"],start) > .1 or row["arm"]["motion_status"] != 0:
            raise ValueError("等待确认期间起点发生变化")
        if not row["gripper"]["foc_status"]["driver_enable_status"]:
            report["settled_open_m"] = grip_at(width,force,"reopen_before_reteach",True,enable_on_open=True)
        before = stats()["tx_packets"]
        interface = int(Path("/sys/class/net/can0/ifindex").read_text())
        cfg["bounds"] = limits()
        cfg["bounds_run"] = run.name
        save(session/"setup.json",cfg)
        q = healthy(dev,rx,grip)["q_rad"]
        if (gap(q,start) > .1 or stats()["tx_packets"] != before+6
                or int(Path("/sys/class/net/can0/ifindex").read_text()) != interface):
            raise ValueError("确认期间当前位置发生变化")
        h0.calibration_arrival(dev,q)
        active = True
        sender.arm(q,"fresh_stationary_anchor_after_interruption")
        normal_hold(q)
        if "settled_open_m" not in report:
            report["settled_open_m"] = grip_at(width,force,"reopen_before_reteach",True)
        normal_hold(q)
        record_hold(q)
        active = False
        if a.inside_start:
            target = [0., math.radians(2), math.radians(-2), 0., 0., 0.]
            align_from_home(target,report["settled_open_m"],"interior_collection_start")
            report["collection_start_q_rad"] = target
            report["stop"] = "arrived_powered_hold"

    def prepare_formal():
        nonlocal active
        allocation = read(session / "session.json")
        if (allocation["split"] not in ("train", "validation") or (session/"setup.json").exists()
                or led.exists() or a.held_session.resolve() == session):
            raise ValueError("需要独立、已分配 split 的新会话")
        evidence = ROOT/"pi-q12-data/pickplace_20261123_211053/setup.json"
        prior = read(evidence)
        cfg = dict(session_id=allocation["session_id"], split=allocation["split"], gripper_basis=WIDTH,
                   terminal_kind=RETREAT, terminal_version=TERMINAL_VERSION, commissioning_only=False,
                   installation="A01 Piper H official gripper, same pads and DC1 wrist mount",
                   measurement_file=str(evidence), pad_measurements=prior["pad_measurements"],
                   open_m=prior["open_m"], close_m=prior["close_m"], force_N=prior["force_N"])
        require_setup(cfg)
        ledger = a.held_session.resolve()/"hold.json"
        agree("确认沿用 A01 夹爪、指垫、腕部安装及固定浅盘，方块适用原夹持尺寸；空爪已张开，手和工具撤离。将查询限位、提交当前实测同位保持")
        base = previous_hold(ledger, strict=True)
        row = healthy(dev,rx,grip)
        if (max(map(abs,base)) > math.radians(5) or row["arm"]["motion_status"] != 0
                or abs(row["width_m"]-cfg["open_m"]) > .002):
            raise ValueError("需要已张开并到位的健康近起点")
        normal_hold(base)
        previous_hold(ledger, strict=True)
        count = stats()["tx_packets"]
        cfg["bounds"] = limits()
        if stats()["tx_packets"] != count + 6:
            raise RuntimeError("限位查询期间出现额外 TX")
        q = healthy(dev,rx,grip)["q_rad"]
        if gap(q,base) > .35 or max(map(abs,q)) > math.radians(5):
            raise ValueError("查询后起点发生变化")
        if any(not lo <= x <= hi for x,(lo,hi) in zip(q,cfg["bounds"],strict=True)):
            raise ValueError("实测起点超限")
        active = True
        sender.arm(q,"formal_measured_start")
        normal_hold(q)
        record_hold(q)
        active = False
        cfg["prepare_run"] = run.name
        report.update(cfg, inherited_ledger=str(ledger))
        save(session/"setup.json",cfg)

    def anchor_start():
        nonlocal active
        cfg = read(session/"setup.json")
        require_setup(cfg)
        source = session/read(source_file)["run"]
        taught = read(source/"run.json")
        if "home_release" in taught:
            held = previous_hold(strict=True)
            receipt = read(session/read(led)["run"]/"run.json")
            if (not taught["complete"] or taught["session_id"] != cfg["session_id"] or taught["boot_id"] != BOOT
                    or receipt["kind"] != "home" or not receipt["complete"] or not receipt.get("source_complete")
                    or receipt["stop"] != "arrived_powered_hold" or receipt["source_trajectory_id"] != taught["run_id"]
                    or gap(held,ZERO) > .01):
                raise ValueError("需要本次已通过示教的独立回零回执")
            agree("已回零；空爪、回程区域净空。张开夹爪并准备该示教的实际公共起点")
            previous_hold(strict=True)
            before = stats()["tx_packets"]
            limits()
            if stats()["tx_packets"] != before+6:
                raise RuntimeError("读取限位时有其他发送")
            current = healthy(dev,rx,grip,allow_disabled_gripper=True)
            if gap(current["q_rad"],ZERO) > .35 or current["arm"]["motion_status"]:
                raise ValueError("开始准备时已偏离零位")
            report.update(use="reposition_only",source_trajectory_id=taught["run_id"],
                          gripper_basis=WIDTH,terminal_kind=RETREAT,home_run=read(led)["run"])
            width = grip_at(cfg["open_m"],cfg["force_N"],"open_before_empty",True,enable_on_open=True)
            align_from_home(taught["marks"][0]["q"],width,"recorded_collection_start")
            report["stop"] = "arrived_powered_hold"
            return
        if (not taught["complete"] or taught.get("terminal_kind") != RETREAT
                or taught["session_id"] != cfg["session_id"] or not taught.get("released")
                or taught["boot_id"] != BOOT or not taught["reposition_only"].get("end")
                or read(led)["run"] != taught["initial_hold_run"]):
            raise ValueError("需要当前同源正常 E、独立手拖接续和灯灭记录")
        agree("已单击退出示教，灯灭，空夹张开，人手及工具撤离，当前近起点净空。执行交接和同位保持")
        expected = previous_hold(strict=True)
        row = snapshot(dev,rx,grip)
        q, st = row["q_rad"], row["arm"]
        if (st["teach_status"] != 2 or st["arm_status"] or st["motion_status"]
                or abs(row["width_m"]-cfg["open_m"]) > .002 or h0.near_zero_issues(dev,q,st)
                or gap(q,taught["marks"][0]["q"]) > .35):
            raise ValueError("灯灭或健康近起点条件不符，保留记录，勿自动回零")
        before = stats()["tx_packets"]
        bounds = limits()
        time.sleep(.3)
        fresh = snapshot(dev,rx,grip)
        if (stats()["tx_packets"] != before+6 or fresh["arm"] != st or gap(fresh["q_rad"],q) > .1
                or gap(fresh["q_rad"],expected) > .35
                or any(not lo <= x <= hi for x,(lo,hi) in zip(fresh["q_rad"],bounds,strict=True))):
            raise ValueError("近起点交接前反馈、限位或 TX 不符")
        report.update(use="reposition_only", source_trajectory_id=taught["run_id"], gripper_basis=WIDTH)
        if st["ctrl_mode"] != 1:
            active = True
            sender.call("handoff",st["ctrl_mode"],lambda: h0.handoff_near_zero(dev,q,st,
                lambda name,**kw: report.setdefault("handoff",[]).append(dict(stage=name,**kw))))
        row = healthy(dev,rx,grip)
        anchor = row["q_rad"]
        if gap(anchor,q) > .35 or gap(anchor,taught["marks"][0]["q"]) > .35 or row["arm"]["motion_status"]:
            raise RuntimeError("交接后偏离起点")
        active = True
        sender.arm(anchor,"measured_anchor_after_passive_reposition")
        normal_hold(anchor)
        record_hold(anchor)
        active = False
        report["stop"] = "arrived_powered_hold"

    def teach():
        base = rx.current()[0] if passive else previous_hold()
        cfg = read(session / "setup.json")
        if not manual_gripper and abs(rx.current()[1]-cfg["open_m"]) > .002:
            raise ValueError("请先完成张开与开口实测")
        report.update(placement=a.placement, session_id=cfg["session_id"], marks=[], breaks=[])
        formal = "terminal_kind" in cfg
        if formal:
            require_setup(cfg)
            if not passive:
                previous_hold(strict=True)
            report.update(gripper_basis=WIDTH, terminal_kind=RETREAT, terminal_version=TERMINAL_VERSION,
                          split=cfg["split"], initial_hold_run=read(led)["run"], use="formal",
                          collection_mode="kinesthetic_direct_v1",
                          source_trajectory_id=report["run_id"], source_directory=str(run),
                          arm_action_source="future_measured_joint_positions",
                          gripper_action_source="actual_submitted_sdk_width_target",
                          future_offset_ns=50_000_000, bounds=cfg["bounds"],
                          bounds_run=cfg.get("bounds_run",cfg["prepare_run"]),
                          events=[], gripper_command_feedback=[])
            if manual_gripper:
                report.update(collection_mode="kinesthetic_manual_gripper_v1",
                              gripper_action_source="future_measured_sdk_width",
                              gripper_operation="operator_backdrives_fingers",
                              initial_measured_width_m=rx.current()[1])
                if passive:
                    report.update(gripper_operation="operator_marked_observed_events", read_only=True,
                                  initial_measured_q_rad=base, gripper_flags_source="feedback.csv:0x2A8 byte6")
                elif snapshot(dev, rx, grip)["gripper"]["foc_status"]["driver_enable_status"]:
                    raise ValueError("夹爪驱动仍使能，先在任务外完成夹爪释放")
                # Use the most recent controller limits from the actual hold when available.
                held_run = read(session / read(led)["run"] / "run.json")
                if held_run.get("limits"):
                    report.update(bounds=[item["usable"] for item in held_run["limits"]],
                                  bounds_run=read(led)["run"])
            report.update(task)
            save(run/"task.json", dict(run_id=report["run_id"], session_id=cfg["session_id"],
                                       placement=a.placement, **task))
            print(a.placement, task["scene_colors"], task["prompt"], flush=True)
            if passive:
                print("三路只读采集。按实体键示教后可拖动六轴。夹爪使能时手指远离夹口。")
            elif manual_gripper:
                print("手动夹住指定色方块后按 C 标记；手动放入浅盘后按 O 标记。录制期间主机只接收。")
            else:
                print("一次录成训练示范：C 实际闭合，夹住指定方块后手拖搬运；O 实际张开，把方块放进浅盘。")
            print("抬离后 E 表示指定颜色已成功入盘、无额外救场；失败用 F 保存。手拖本身不算人工救场。")
            if not passive:
                agree("核对目标、布局和腕图，开始一次真实手拖抓放")
        save(source_file, dict(pending=run.name))
        save(clear_file, dict(pending=run.name))
        stopped_during = None
        pending_end = None

        def teach_gripper(event, check):
            # Only 0x159 is sent here. The six arm joints stay in physical teaching mode.
            before = snapshot(dev,rx,grip)
            width = cfg["close_m"] if event == "close" else cfg["open_m"]
            sender.width(width,cfg["force_N"],event,gripper_basis=WIDTH)
            sent = CLOCK()
            deadline = time.monotonic()+2.5
            last_width = None
            stable_since = None
            stable_width = None
            while time.monotonic() < deadline:
                check()
                row = snapshot(dev,rx,grip)
                st = row["arm"]
                flags = row["gripper"]["foc_status"]
                if (st["ctrl_mode"] != 2 or st["teach_status"] != 1 or st["arm_status"] not in (0,11)
                        or any(st["err_status"].values())
                        or any(v for k,v in flags.items() if k not in ("driver_enable_status","homing_status"))):
                    raise RuntimeError(f"夹爪动作期间示教/驱动状态改变：{st}, {flags}")
                measured = row["width_m"]
                moved = (before["width_m"]-measured >= .001) if event == "close" else abs(measured-width) <= .002
                fresh = rx.grip[0] > sent+300_000_000 and flags["driver_enable_status"]
                if fresh and moved:
                    if stable_since is None or abs(measured-stable_width) > .0005:
                        stable_since = time.monotonic()
                        stable_width = measured
                    elif stable_since is not None and time.monotonic()-stable_since >= .15:
                        item = dict(event=event, mono_ns=row["mono_ns"], target_m=width,
                                    measured_m=measured, before_m=before["width_m"],
                                    feedback_confirmed=True, command_id=sender.command_id)
                        report["gripper_command_feedback"].append(item)
                        if event in ("close","open"):
                            report["events"].append(item)
                        print(event,"已实际执行，目标/反馈 mm",round(width*1000,2),
                              round(measured*1000,2),flush=True)
                        return
                else:
                    stable_since = None
                last_width = measured
                time.sleep(.02)
            report["gripper_command_not_executed"] = dict(event=event,target_m=width,
                before_m=before["width_m"], last_measured_m=last_width)
            raise RuntimeError("手拖中已发送夹爪 0x159，但未收到实际开合反馈；保留记录，不自动切六轴控制模式")

        def still_and_in_bounds(sample):
            _, ns, q = sample
            recent = [(t, pos) for _, t, pos in list(rx.recent_joints) if 0 <= ns-t <= 500_000_000]
            return (all(lo <= v <= hi for v, (lo, hi) in zip(q, cfg["bounds"], strict=True))
                    and recent and ns-recent[0][0] >= 480_000_000
                    and all(gap(pos, q) <= .2 for _, pos in recent))

        def wait_for_physical_teach(check=None):
            if passive and a.start_marker:
                print("已预录。复原布局并回到公共起点，实体示教绿灯常亮、停稳后，S 回车开始任务。",flush=True)
            elif manual_gripper and snapshot(dev,rx,grip)["arm"]["teach_status"] == 1:
                print("实体示教键已开启，请保持起点，等 start 已记再手拖。", flush=True)
            else:
                print("起点就绪。单击实体示教键，绿灯常亮后停稳，等 start 已记再手拖。", flush=True)
            while True:
                if check is not None:
                    check()
                st = snapshot(dev,rx,grip)["arm"]
                if st["arm_status"] not in (0,11) or any(st["err_status"].values()):
                    raise RuntimeError(f"等待示教时出现控制器故障：{st}")
                if st["ctrl_mode"] == 2 and st["teach_status"] == 1:
                    if not (passive and a.start_marker) or line() == "s":
                        break
                    time.sleep(.03)
                    continue
                if passive and a.start_marker:
                    line()  # Discard input typed outside the physical teaching state.
                if st["ctrl_mode"] not in (0,1,2) or st["teach_status"] not in (0,2):
                    raise ValueError(f"意外的控制源或示教状态：{st}")
                time.sleep(.03)
            if not passive:
                previous_hold(strict=True)
            report["before_drag_recording"] = dict(joint_groups=rx.nq, gripper_frames=rx.ng)
            rx.write_samples = True
        if formal and not passive:
            wait_for_physical_teach()
        if passive:
            rx.write_samples = True
        with camera(run) as check:
            if passive:
                print("腕图、六轴、夹爪开口已开始记录。", flush=True)
                wait_for_physical_teach(check)
                base = rx.current()[0]
            if formal and not manual_gripper:
                teach_gripper("initial_open",check)
            if not formal:
                print("腕图记录已启动。在起点单击实体键，确认绿灯常亮，然后回车。")
                input()
            print('如需分段，在静止处 B 回车开始休息；保持同姿态，N 回车接续。全程继续记录。')
            boundary = None
            keys = ("start", "close", "open", "end")
            for event in keys:
                if event != "start":
                    required = {"close":"c","open":"o","end":"e"}[event]
                    if passive:
                        print({"close":"可以手拖机械臂。实际抓到后按 C；无法抓取可按 F 保存。",
                               "open":"实际释放后按 O；未完成可按 F 保存。",
                               "end":"抓对目标并已放入浅盘、空爪抬离停稳后按 E；否则 F 保存。"}[event],flush=True)
                    elif manual_gripper:
                        print({"close":"手动夹住后 C 回车标记；失败 F 回车。", "open":"手动释放后 O 回车标记；失败 F 回车。",
                               "end":"空爪抬离并停稳，目标色成功入盘 E 回车，失败 F 回车。"}[event], flush=True)
                    elif formal and event == "end":
                        print("放好目标色方块并空爪抬离：E 成功 / F 失败，随后结束实体示教、撤手并自动回零。")
                    elif formal:
                        print(f"{required.upper()} 回车将实际{'闭合夹住方块' if event=='close' else '张开放下方块'}；停稳后操作。",flush=True)
                    else:
                        print(f"{event}: 静止至少 1 秒，输入 {required.upper()} 并回车，继续静止 1 秒。", flush=True)
                next_display = 0.
                last_drag = None
                while True:
                    check()
                    row = snapshot(dev, rx, grip)
                    if passive and event == "close":
                        report["max_open_before_close_m"] = max(row["width_m"], report.get("max_open_before_close_m",report["marks"][0]["width_m"]))
                    if event == 'end' and not formal and time.monotonic() >= next_display:
                        err = [round(math.degrees(v-b),2) for v,b in zip(row['q_rad'],base)]
                        print('示教中，当前减起点 J1–J6 (°)', err, '夹爪 mm',
                              round(row['width_m']*1000,2), flush=True)
                        next_display = time.monotonic()+1
                    st = row["arm"]
                    if (formal and report["marks"] and st["ctrl_mode"] in (0,1,2)
                            and st["teach_status"] == 2 and st["arm_status"] == 0
                            and not any(st["err_status"].values())):
                        stopped_during = event
                        if (event == "end" and boundary is None and last_drag is not None
                                and 0 <= CLOCK()-last_drag[1] <= 100_000_000
                                and gap(row["q_rad"],last_drag[2]) <= .2 and still_and_in_bounds(last_drag)):
                            ident, ns, q = last_drag
                            pending_end = dict(event="end", joint_id=ident, mono_ns=ns, q=q)
                            if manual_gripper:
                                grip_ns, width = rx.grip
                                pending_end.update(grip_ns=grip_ns, width_m=width)
                        break
                    if (st["ctrl_mode"] != 2 or st["teach_status"] != 1 or
                            st["arm_status"] not in (0, 11) or any(st["err_status"].values())):
                        raise RuntimeError(f"未收到正常示教记录状态：{st}")
                    if manual_gripper and not passive and row["gripper"]["foc_status"]["driver_enable_status"]:
                        raise RuntimeError("夹爪驱动已使能，已停止被动录制，请勿徒手对抗夹爪")
                    last_drag = rx.joint_sample
                    key = None if event == "start" else line()
                    if manual_gripper and key == "0" and event == "open":
                        print("释放标记请用英文字母 O，再回车。",flush=True)
                    if manual_gripper and key == "f" and event != "end":
                        report["operator_outcome"] = "failed"
                        stopped_during = event
                        print("F 已记录。请单击实体键结束示教、确认灯灭。",flush=True)
                        break
                    if key == "b" and boundary is None:
                        ident, ns, q = rx.joint_sample
                        boundary = dict(joint_id=ident, mono_ns=ns, q=q)
                        print("分段停留，保持原姿态；N 回车接续。", flush=True)
                    if boundary is not None:
                        if gap(row["q_rad"], boundary["q"]) > .2:
                            raise ValueError("分段边界姿态改变，请重新示教完整路线")
                        if key == "n":
                            ident, ns, q = rx.joint_sample
                            report["breaks"].append([boundary, dict(joint_id=ident,mono_ns=ns,q=q)])
                            boundary = None
                            print("同姿态接续，继续手拖。", flush=True)
                        time.sleep(.02)
                        continue
                    if event == "start" or key == required or (formal and event == "end" and key == "f"):
                        if (event == "start" or (event == "end" and not formal)) and gap(row["q_rad"],base) > .35:
                            if event == "start":
                                raise ValueError("示教起点偏离已建立的保持位")
                            print("请手拖回原起点后再输入 E。", flush=True)
                            continue
                        # The receive thread publishes these three fields together.
                        ident, ns, q = rx.joint_sample
                        mark = dict(event=event, joint_id=ident, mono_ns=ns, q=q)
                        if manual_gripper:
                            grip_ns, width = rx.grip
                            mark.update(grip_ns=grip_ns, width_m=width,
                                        gripper_drive_enabled=row["gripper"]["foc_status"]["driver_enable_status"])
                            if passive and event=="end" and key=="e":
                                start,close,opened = report["marks"]
                                if (report["max_open_before_close_m"]-close["width_m"] < .001
                                        or opened["width_m"]-close["width_m"] < .001):
                                    print("C/O 标记缺少实际闭合或张开的宽度变化，本条可用 F 保存。",flush=True)
                                    continue
                            if event in ("close", "open"):
                                report["events"].append(dict(event=event, grip_ns=grip_ns, width_m=width))
                                print(f"{event} 标记宽度 {width*1000:.1f} mm",flush=True)
                        if formal and event == "end":
                            if (not passive or key != "f") and not still_and_in_bounds((ident, ns, q)):
                                print("E 未记录：在关节限位内的抬离位置停稳一秒。",flush=True)
                                continue
                            mark["operator_empty_retreat"] = True  # E is the explicit on-site confirmation
                            mark["operator_task_success"] = key == "e"
                            report["operator_outcome"] = "success" if key == "e" else "failed"
                        report["marks"].append(mark)
                        if formal and event == "start":
                            report["grid_start_ns"] = ns
                            time.sleep(.55)
                        elif formal and not manual_gripper and event in ("close","open"):
                            teach_gripper(event,check)
                        print(event, "已记", flush=True)
                        break
                    time.sleep(.02)
                if stopped_during:
                    break
            end = report["marks"][-1] if report["marks"][-1]["event"] == "end" else pending_end
            if formal and end is not None:
                # Drain the camera CSV through the E frame before reading its causal predecessor.
                time.sleep(.15)
                check()
                with (run/"rgb.csv").open() as f:
                    prior = [r for r in csv.DictReader(f) if int(r["mono_ns"]) <= end["mono_ns"]]
                if not prior or end["mono_ns"]-int(prior[-1]["mono_ns"]) > 100_000_000:
                    raise ValueError("E 缺少新鲜原图来源")
                end.update(image_id=int(prior[-1]["index"]), image_ns=int(prior[-1]["mono_ns"]))
                if pending_end is None:
                    save(run/"task_end.json",end)
            if not stopped_during:
                print("单击实体键结束示教，确认灯灭，然后撤手并清空回程范围。", flush=True)
        if formal:
            while True:
                st = snapshot(dev,rx,grip)["arm"]
                if st["teach_status"] == 2:
                    break
                if (st["ctrl_mode"] != 2 or st["teach_status"] != 1 or st["arm_status"] not in (0,11)
                        or any(st["err_status"].values())):
                    raise RuntimeError(f"等待结束示教期间控制状态改变：{st}")
                time.sleep(.03)
            released_pose(dev,rx,grip)
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
            if pending_end is not None:
                prompt = ("已灯灭。E 确认放对颜色并抬离，F 失败保存：" if manual_gripper else
                          "已灯灭并撤手。E 确认目标色成功入盘 / F 失败保存，均自动回零；H 仅回零：")
                key = input(prompt).strip().lower()
                if key not in ("e","f","h"):
                    raise ValueError("未完成现场交接")
                if passive and key=="e":
                    start,closed,opened = report["marks"]
                    if report["max_open_before_close_m"]-closed["width_m"] < .001 or opened["width_m"]-closed["width_m"] < .001:
                        raise ValueError("C/O 标记缺少实际夹爪开合反馈，保留数据，本条未通过")
                if key in ("e","f"):
                    pending_end["operator_empty_retreat"] = True
                    pending_end["operator_task_success"] = key == "e"
                    report["operator_outcome"] = "success" if key == "e" else "failed"
                    report["marks"].append(pending_end)
                    save(run/"task_end.json",pending_end)
            elif not manual_gripper:
                agree("已灯灭。空爪，手和工具已撤离整个回程范围，结束示教并自动回零")
        else:
            input("确认实体示教灯已经熄灭后回车：")
        released = snapshot(dev, rx, grip)
        st = released["arm"]
        if st["ctrl_mode"] not in (0,1,2) or (st["ctrl_mode"] == 2 and st["teach_status"] != 2):
            raise RuntimeError(f"灯灭后仍未收到停止示教的状态：{st}")
        report["released"] = released
        if formal:
            tx.flush()
            with (run/"tx.csv").open() as f:
                submitted = list(csv.DictReader(f))
            if manual_gripper and submitted:
                raise RuntimeError("手动夹指任务期间出现主机命令")
            if (any(int(r["can_id"],16) != 0x159 or r["result"] != "host_submitted" for r in submitted)
                    or stats()["tx_packets"]-report["interface_before"]["tx_packets"] != len(submitted)):
                raise RuntimeError("单次示教窗口包含夹爪以外的主机发送，保留记录")
            report["gripper_only_host_frames"] = len(submitted)
            # Gripper commands do not replace the arm target held before teaching.
            if not manual_gripper:
                save(led,dict(read(led),tx_packets=stats()["tx_packets"]))
        elif stats()["tx_packets"] != report["interface_before"]["tx_packets"]:
            raise RuntimeError("手拖期间主机 TX 变化；该轨迹需排查")
        if formal:
            released = released_pose(dev,rx,grip)
            if report["marks"][-1]["event"] == "end":
                fback.flush()
                end = report["marks"][-1]
                report["reposition_only"] = dict(after_joint_id=end["joint_id"], after_ns=end["mono_ns"],
                                                  scope="independent SDK home after teach")
                save(run/"reposition_only.json",report["reposition_only"])
                report.update(grid_end_ns=end["mono_ns"],stop="demonstration_finished",
                              reset_between_runs="separate_operator_handoff" if manual_gripper else "automatic_direct_home")
            else:
                report["source_rejection"] = f"示教在 {stopped_during} 阶段结束，缺少确认的任务终点"
            if not manual_gripper:
                report["home_release"] = dict(q_rad=released["q_rad"], width_m=released["width_m"],
                                              ifindex=int(Path("/sys/class/net/can0/ifindex").read_text()),
                                              confirmed_clear=True, mono_ns=released["mono_ns"])
        # Save the actual demonstration before the independent arm return.

    def return_start():
        nonlocal active
        cfg = read(session/"setup.json")
        source = read(source_file)
        receipt = read(clear_file)
        empty_path = session/receipt["run"]
        empty = read(empty_path/"run.json")
        quality = read(empty_path/"quality.json")
        held = previous_hold()
        last_run = read(session/read(led)["run"]/"run.json")
        if "terminal_kind" in cfg:
            require_setup(cfg)
            previous_hold(strict=True)
            reviewed = read(empty_path/"review.json")
            if (not reviewed["approved_empty"] or reviewed["run_id"] != empty["run_id"]
                    or empty.get("gripper_basis") != WIDTH or empty.get("terminal_kind") != RETREAT):
                raise ValueError("需要同源正式合同的已审核空场")
        if (not empty["complete"] or empty["kind"] != "empty" or not empty["pause_resume_verified"]
                or empty["stop"] != "arrived_powered_hold" or not last_run["complete"]
                or empty["source_directory"] != str(session/source["run"])
                or empty["source_trajectory_id"] != last_run.get("source_trajectory_id")
                or last_run["stop"] != "arrived_powered_hold" or not quality["grid_rows"]):
            raise ValueError("需要同源已到位的执行和本次真实空场提交记录")
        with (empty_path/"commands.jsonl").open() as f:
            all_cmds = [json.loads(x) for x in f]
        if any(c["result"] != "host_submitted" for c in all_cmds):
            raise ValueError("空场记录包含不完整提交")
        route = [c for c in reversed(all_cmds) if c["kind"]=="arm" and
                 (c["source"]=="source_start" or isinstance(c["source"], list))]
        if (len(route)<2 or route[-1]["source"]!="source_start" or
                gap(held,route[0]["actual"])>.01 or gap(route[-1]["actual"],empty["initial"]["q_rad"])>.35):
            raise ValueError("当前保持与已执行路径的首末不匹配")
        # The geometry is unchanged. Shorten strictly identical quantized holds
        # longer than a second to ten ticks; retain every distinct wire target.
        targets = []
        for _, group in groupby(route, key=lambda c:c["actual"]):
            same = list(group)
            targets.extend(same if len(same)<=20 else same[:5]+same[-5:])
        if any(gap(a["actual"],b["actual"]) > empty["reference_deg_s"]*.05+.002
               for a,b in zip(targets,targets[1:])):
            raise ValueError("空场原轨迹中存在过大相邻步")
        now = healthy(dev,rx,grip)
        if abs(now["width_m"]-cfg["open_m"])>.002 or now["arm"]["motion_status"]!=0:
            raise ValueError("请确认空夹张开且臂已到位")
        report.update(use="reposition_only",reference_run=empty_path.name,
                      source_trajectory_id=empty["source_trajectory_id"],original_ticks=len(route),
                      return_ticks=len(targets),start_target=route[0]["actual"],end_target=route[-1]["actual"])
        print("原路返回参考秒",len(targets)*.05,flush=True)
        agree("物体与工具已移出；沿空场原路倒序返回，空夹始终张开")
        previous_hold()
        limits()
        if any(not lo<=v<=hi for c in targets for v,(lo,hi) in zip(c["actual"],sender.bounds)):
            raise ValueError("本次反馈的控制器限位不覆盖该执行路径")
        h0.calibration_arrival(dev,held)
        active = True
        sender.move_j_mode(5)
        time.sleep(.15)
        goal = held
        previous_tick = time.monotonic()
        for c in targets:
            tick = time.monotonic()
            if tick-previous_tick>.15:
                raise RuntimeError("返回轨迹调度中断")
            previous_tick = tick
            row = healthy(dev,rx,grip)
            if gap(row["q_rad"],goal)>1 or abs(row["width_m"]-cfg["open_m"])>.002:
                raise RuntimeError("返回期间关节跟踪或开口异常")
            if line() in ("p","e"):
                normal_hold(goal)
                active = False
                if c is targets[0]:
                    prior = read(led)
                    save(led, dict(prior, tx_packets=stats()["tx_packets"], stop_run=run.name))
                else:
                    record_hold(goal)
                report["stop"] = "operator_ended_in_hold"
                raise ValueError("中止独立返回，已确认保持")
            goal = c["actual"]
            sender.arm(goal,c["id"])
            time.sleep(max(0,.05-(time.monotonic()-tick)))
        normal_hold(goal)
        record_hold(goal)
        report["stop"] = "arrived_powered_hold"
        active = False

    def replay():
        nonlocal active
        cfg = read(session / "setup.json")
        formal_source = "terminal_kind" in cfg
        if formal_source or report["use"] == "formal":
            require_setup(cfg)
            report.update(gripper_basis=WIDTH, terminal_kind=RETREAT, terminal_version=TERMINAL_VERSION,
                          pad_measurements=cfg["pad_measurements"], installation=cfg["installation"],
                          split=cfg["split"], measurement_file=cfg["measurement_file"])
        if cfg.get("commissioning_only"):
            if report["use"] == "formal":
                raise ValueError("此会话仅核实了指垫端点，正式训练需先确定物理开口契约")
            report.update(gripper_basis=cfg["gripper_basis"],pad_measurements=cfg["pad_measurements"])
        src = read(source_file)
        if not src.get('run'):
            raise ValueError('当前布局的示教尚未正常完成')
        path = session / src["run"]
        taught = read(path / "run.json")
        window = src.get("retreat_window")
        if window:
            if not cfg.get("commissioning_only") or report["use"] == "formal":
                raise ValueError("Selected retreat is for reviewed commissioning only")
            report.update(retreat_window=window,reset_between_runs="separate_confirmed_return")
        report.update(source_trajectory_id=taught["run_id"], source_directory=str(path),
                      placement=taught["placement"], session_id=cfg["session_id"])
        if formal_source:
            source_task = recorded_task(taught)
            if kind == "block":
                if task != source_task:
                    raise ValueError("本条指令或实物场景与当前示教源不同，请复原或为新目标示教")
                report.update(task)
                save(run/"task.json", dict(run_id=report["run_id"], session_id=cfg["session_id"],
                                           placement=taught["placement"], source_trajectory_id=taught["run_id"],
                                           **task))
            else:
                report["planned_block_task"] = source_task
            print(taught["placement"], source_task["scene_colors"], source_task["prompt"], flush=True)
            hold = read(led)
            anchor = read(session/hold["run"]/"run.json")
            if (window or taught.get("terminal_kind") != RETREAT or taught.get("gripper_basis") != WIDTH
                    or taught["session_id"] != cfg["session_id"] or taught["split"] != cfg["split"]
                    or not anchor["complete"] or anchor["stop"] != "arrived_powered_hold"
                    or anchor["kind"] not in ("anchor-start","return-start","home")
                    or not taught["complete"]
                    or anchor["source_trajectory_id"] != taught["run_id"]):
                raise ValueError("需要此正常源的近起点锚定或同源空场实际返回")
            previous_hold(strict=True)
            report.update(start_hold_run=hold["run"], task_end=taught["marks"][-1],
                          reset_between_runs="separate_confirmed_return")
        if kind == "empty":
            save(clear_file, dict(pending=run.name))
        if kind == "block":
            checked = read(clear_file)
            if not checked.get('run'):
                raise ValueError('当前路径尚无完成的空场核查')
            review = read(session / checked["run"] / "review.json")
            empty_report = read(session / checked["run"] / "run.json")
            if (checked["source"] != taught["run_id"] or not review["approved_empty"] or
                    empty_report["run_id"] != review["run_id"]):
                raise RuntimeError("先复核同一条空场轨迹")
        print("按手拖时的布局保持浅盘、基座和线缆位置。运行中 P 回车暂停，R 回车继续，E 回车结束。")
        agree(("方块已移走" if kind=="empty" else "方块已放回原位、同一路径空场已通过")
              + "，示教灯灭，人手离开。已现场检查路径、盘沿、指尖和线缆。")
        base = previous_hold()
        old_hold = read(led)
        bounds = limits()
        after_queries = stats()["tx_packets"]
        if after_queries != old_hold["tx_packets"] + 6:
            raise RuntimeError("限位读取期间出现额外主机 TX")
        # Queries cannot replace the previously submitted joint target.
        save(led, dict(old_hold, tx_packets=after_queries))
        speed = min(2.5, *(math.degrees(r['max_rad_s']) for r in report['limits']))
        points = plan(path, bounds, speed, window)
        report.update(reference_deg_s=speed, reference_deg_s2=8, retained_points=len(points))
        print("源关节点", points[-1]["id"]-points[0]["id"]+1, "保留节点", len(points),
              "计划轨迹秒", sum(p["ticks"] for p in points)*.05, flush=True)
        if gap(base,points[0]["q"]) > .35 or (not window and not formal_source and gap(base,points[-1]["q"]) > .35):
            raise ValueError("起点与实测保持位不符，或未经选择的末端偏离起点")
        agree("确认以上路径与时间，启动本次低速执行")
        with camera(run) as check:
            try:
                previous_hold()
                current = snapshot(dev, rx, grip)
                st = current["arm"]
                if gap(base,current["q_rad"]) > .35 or abs(current["width_m"]-cfg["open_m"]) > .002:
                    raise ValueError("交接时起点或夹爪发生变化")
                if st["ctrl_mode"] != 1:
                    issues = h0.near_zero_issues(dev, current["q_rad"], st)
                    if issues or st['arm_status'] != 0 or st["motion_status"] != 0 or st["ctrl_mode"] not in (0,2):
                        raise ValueError(f"不满足已验证的近零灯灭交接：{issues}, {st}")
                    time.sleep(.3)
                    if gap(current["q_rad"], rx.current()[0]) > .1:
                        raise RuntimeError("交接前姿态移动")
                    active = True
                    sender.call("handoff", st["ctrl_mode"], lambda: h0.handoff_near_zero(
                        dev, current["q_rad"], st, lambda name, **kw: print(name, kw, flush=True)))
                h0.calibration_arrival(dev, base)
                current = healthy(dev, rx, grip)
                if gap(base,current['q_rad']) > .35:
                    raise RuntimeError('交接后起点发生变化')
                active = True
                sender.arm(current["q_rad"], "start_measured_hold")
                normal_hold(current["q_rad"])
                sender.move_j_mode(5)
                time.sleep(.15)
                healthy(dev, rx, grip)
                sender.arm(points[0]["q"], "source_start")
                grip_at(cfg["open_m"], cfg["force_N"], "initial_open", True)
                report["grid_start_ns"] = CLOCK()
                last = points[0]["q"]
                paused = False
                last_tick = None
                for before, point in zip(points,points[1:]):
                    steps, k = point['ticks'], 0
                    start_q, start_fraction, fraction = before['q'], 0., 0.
                    while k < steps:
                        k += 1
                        tick = time.monotonic()
                        if last_tick is not None and tick-last_tick > .15:
                            raise RuntimeError("动作调度中断超过 150 ms")
                        last_tick = tick
                        check()
                        state = healthy(dev, rx, grip)
                        if gap(state["q_rad"], last) > 1:
                            raise RuntimeError("跟踪偏差超过 1°")
                        key = line()
                        if key in ("p","e"):
                            recent = [dev.angles(r) for r in list(dev.feedback)
                                      if tick-.4 <= r["monotonic_s"] <= tick]
                            excursion = max((gap(q,recent[0]) for q in recent), default=0.)
                            normal_hold(last)
                            report.setdefault("pauses", []).append(dict(at_ns=CLOCK(), target=last, key=key,
                                                                        prior_motion_deg=excursion))
                            if key == "e":
                                active = False
                                record_hold(last)
                                report["stop"] = "operator_ended_in_hold"
                                raise ValueError("现场提前结束，已确认保持")
                            print("暂停，保持已确认。R 回车继续，E 回车结束。", flush=True)
                            while True:
                                check()
                                if gap(healthy(dev, rx, grip)["q_rad"], last) > .5:
                                    raise RuntimeError("暂停期间偏离保持位")
                                key = line()
                                if key in ("r","e"):
                                    break
                                time.sleep(.05)
                            if key == "e":
                                normal_hold(last)
                                active = False
                                record_hold(last)
                                report["stop"] = "operator_ended_in_hold"
                                raise ValueError("暂停后提前结束，已确认保持")
                            paused = paused or excursion > .1
                            # Restart the remaining part of this same chord from rest.
                            start_q, start_fraction = last, fraction
                            deg = gap(last, point['q'])
                            seconds = max(1.5*deg/speed, math.sqrt(6*deg/8))
                            steps, k = max(steps-k+1, math.ceil(seconds/.05), 1), 1
                            tick = last_tick = time.monotonic()
                        t = k / steps
                        w = t*t*(3-2*t)
                        q = [x+w*(y-x) for x,y in zip(start_q,point["q"])]
                        fraction = start_fraction+w*(1-start_fraction)
                        sender.arm(q, [before["id"], point["id"], k, steps, fraction])
                        last = q
                        elapsed = time.monotonic()-tick
                        if elapsed > .1:
                            raise RuntimeError("动作循环耗时超过 100 ms")
                        time.sleep(max(0,.05-elapsed))
                    name = point["marker"]
                    if name in ("open","close"):
                        check()
                        normal_hold(last)
                        width = cfg[name+"_m"]
                        measured = grip_at(width,cfg["force_N"],name, kind=="empty" or name=="open")
                        report.setdefault("events", []).append(dict(event=name, mono_ns=CLOCK(),
                                                                    target_m=width, measured_m=measured))
                        print(name, "目标/反馈 mm", width*1000, measured*1000, flush=True)
                        last_tick = None
                normal_hold(last)
                report.update(grid_end_ns=CLOCK(), pause_resume_verified=paused, stop="arrived_powered_hold")
                record_hold(last)
                active = False
                if formal_source:
                    released = healthy(dev,rx,grip)
                    report["home_release"] = dict(q_rad=released["q_rad"], width_m=released["width_m"],
                        ifindex=int(Path("/sys/class/net/can0/ifindex").read_text()),
                        confirmed_clear=True, mono_ns=released["mono_ns"])
                    report["reset_between_runs"] = "automatic_direct_home"
            except BaseException:
                fault()
                raise

    def fault():
        nonlocal active
        if active:
            active = False
            report["stop"] = "fault_stop_requested"
            try:
                sender.call("fault_stop", None, dev.robot.electronic_emergency_stop)
                print("已提交阻尼急停，可能下沉。现场确认，必要时使用物理急停。", flush=True)
            except BaseException as exc:
                report["stop_error"] = repr(exc)
                print("软件急停提交未确认，请使用现场物理急停。", flush=True)

    with ExitStack() as stack:
        lock = stack.enter_context(open("/tmp/dog_and_arm_piper_motion.lock","a"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not (HERE.parents[1] / CAL).is_file():
            raise FileNotFoundError(CAL)
        dev = PiperDevice()
        dev.feedback, dev.driver_feedback = deque(maxlen=256), deque(maxlen=256)
        grip = dev.robot.init_effector("agx_gripper")
        fback = stack.enter_context((run/"feedback.csv").open("x", newline=""))
        rx = Feedback(fback, write_samples=not (kind == "teach" and task is not None))
        dev.robot.get_context().register_parser_packet_fun(rx.packet)
        def interrupted(*_):
            raise KeyboardInterrupt("operator interrupt")
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        try:
            dev.connect()
            report["initial"] = snapshot(dev, rx, grip)
            if kind not in ("teach","status","prepare-pads") or (kind == "teach" and task is not None):
                tx = stack.enter_context((run/"tx.csv").open("x",newline="",buffering=1))
                commands = stack.enter_context((run/"commands.jsonl").open("x",buffering=1))
                if passive:
                    csv.writer(tx).writerow(("start_ns","end_ns","command_id","can_id","data","result","error"))
                else:
                    sender = Sender(dev, grip, tx, commands)
            if kind == "status":
                time.sleep(2)
            elif kind == "limits":
                print(json.dumps(limits(), ensure_ascii=False))
            elif kind == "prepare-formal":
                prepare_formal()
            elif kind == "anchor-start":
                anchor_start()
            elif kind == "prepare":
                prepare()
            elif kind == "width-check":
                check_width()
            elif kind == "prepare-pads":
                prepare_pads()
            elif kind in ("restart-teach", "next-teach"):
                restart_teach()
            elif kind == "return-start":
                return_start()
            elif kind == "home":
                home()
            elif kind == "teach":
                teach()
            else:
                replay()
            report["complete"] = "source_rejection" not in report
        except BaseException as exc:
            report["error"] = repr(exc)
            fault()
            raise
        finally:
            try:
                report["final"] = snapshot(dev, rx, grip)
            except Exception as exc:
                report["final_unknown"] = repr(exc)
            dev.disconnect()
            report.update(interface_after=stats(), joint_groups=rx.nq, gripper_frames=rx.ng,
                          rejected_triplets=rx.bad_groups, ended_unix_ns=time.time_ns())
            if kind in ("teach","anchor-start","prepare-formal","home") and "final_unknown" in report:
                report["complete"] = False
            if rx.error:
                report.update(complete=False, receive_error=rx.error)
            save(run / "run.json", report)
            if manual_gripper and report["interface_after"]["tx_packets"] != report["interface_before"]["tx_packets"]:
                report.update(complete=False, source_rejection="手动夹指示教期间主机发送计数发生变化")
                save(run/"run.json", report)
            if report.get("collection_mode") in ("kinesthetic_direct_v1","kinesthetic_manual_gripper_v1"):
                success = report["complete"] and report.get("operator_outcome") == "success"
                verdict_source = "collector_rejection"
                if success:
                    verdict_source = "operator_success_key"
                elif report.get("operator_outcome") == "failed":
                    verdict_source = "operator_failure_key"
                save(run/"review.json",dict(run_id=report["run_id"],approved_teach=success,
                    approved_block=False,approved_empty=False,outcome="success" if success else "failed",
                    actual_grasped_color=task["target_color"] if success else "unknown",
                    intervention="no" if success else "unknown",verdict_source=verdict_source,
                    intervention_definition="extra rescue beyond intended kinesthetic teaching",
                    source_trajectory_id=report["run_id"],session_id=report["session_id"],
                    placement=a.placement,**task))
            if report["complete"] and kind == "teach":
                save(source_file, dict(run=run.name))
            if report["complete"] and kind == "empty":
                save(clear_file, dict(run=run.name, source=report["source_trajectory_id"]))
            print("证据", run/"run.json", "完成", report["complete"], flush=True)
            if "final" in report:
                s = report["final"]
                print("末次 q°", [round(math.degrees(v),3) for v in s["q_rad"]],
                      "夹爪 mm", round(s["width_m"]*1000,3), "模式", s["arm"],
                      "使能", [d["driver_enable_status"] for d in s["drives"]])

    if kind in ("teach", "empty", "block") and "home_release" in report and not (rx.error or "final_unknown" in report):
        if "source_rejection" in report:
            print("保留未通过的示教：", report["source_rejection"], flush=True)
        print("采集记录已关闭，按最高 3°/s 直接回零。", flush=True)
        if main(["home", str(session)], finished_run=run):
            return 1
        print("已回零。复原或更换摆放后，用 next-teach 开始下一组；本次成功示范直接用于导出，无需重放。", flush=True)
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

