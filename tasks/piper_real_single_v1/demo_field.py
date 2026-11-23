"""本机首批示范。status 只接收。prepare、empty、block 只在现场终端确认后控制。"""
import argparse
import csv
import fcntl
import json
import math
import os
import select
import signal
import sys
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from demo_io import (BOOT, CAL, CAL_SHA, CLOCK, HERE, ROOT, Feedback, PiperDevice,
                     Sender, camera, gap, h0, healthy, read, save, snapshot, stats)
from demo_path import plan


def agree(prompt):
    if input(prompt + "  输入 YES 并回车：").strip() != "YES":
        raise ValueError("操作员未确认")


def line():
    if select.select([sys.stdin], [], [], 0)[0]:
        value = sys.stdin.readline()
        if not value:
            raise EOFError("现场终端已断开")
        return value.strip().lower()
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    sub.add_parser("status", help="读取两秒实测反馈；TX=0")
    sub.add_parser("limits", help="仅查询六轴当前控制器限位")
    modes = {"restart-teach": "重新建立本次实测保持位并复开夹爪", "prepare-pads": "以实测指垫端点接续联调（只接收）", "prepare": "建立本次起点，核实开口", "width-check": "单点空夹卡尺核查",
             "teach": "被动手拖记录", "empty": "移走方块后核查新路径",
             "block": "按原布局抓放一次"}
    for kind, help_text in modes.items():
        sp = sub.add_parser(kind, help=help_text)
        sp.add_argument("session", type=Path)
        if kind == "prepare-pads":
            sp.add_argument("--first-open-mm", required=True, type=float, help="首次张开独立卡尺净距")
            sp.add_argument("--object-mm", required=True, type=float, help="同一夹持方向的实物宽")
        if kind == "width-check":
            sp.add_argument("target_mm", type=float, help="本次空夹目标 mm，15 至 40")
        if kind == "teach":
            sp.add_argument("placement", help="摆放编号")
        if kind == "block":
            sp.add_argument("--formal", action="store_true", help="首批逐条质检通过后采正式示范")
    a = p.parse_args()
    kind = a.kind
    if kind == "width-check" and not 15 <= a.target_mm <= 40:
        p.error("单点空夹目标须在 15–40 mm 内")
    if kind not in ("status", "limits") and not sys.stdin.isatty():
        p.error("在能观察机械臂的交互终端运行")
    session = getattr(a, "session", ROOT / "pi-q12-data/pi-demo-checks").resolve()
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

    def previous_hold():
        h = read(led)
        link_index = int(Path("/sys/class/net/can0/ifindex").read_text())
        if (h["boot_id"] != BOOT or h["tx_packets"] != stats()["tx_packets"]
                or h.get("ifindex",link_index) != link_index):
            raise RuntimeError("保持目标的 boot/TX 计数已变化，请重新建立本次起点")
        if gap(rx.current()[0], h["q"]) > .35:
            raise RuntimeError("实测姿态距先前有提交记录的起点超过 0.35°")
        return h["q"]

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

    def grip_at(width, force, label, require_width):
        sender.width(width, force, label)
        sent = CLOCK()
        deadline = time.monotonic()+2.5
        while time.monotonic() < deadline:
            row = healthy(dev, rx, grip)
            if (rx.grip[0] > sent + 800_000_000 and
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

    def restart_teach():
        nonlocal active
        cfg = read(session/"setup.json")
        old = read(led)
        if not cfg.get("commissioning_only") or old["boot_id"] != BOOT:
            raise ValueError("需要本次启动下已核实指垫端点的同一联调会话")
        width, force = cfg["open_m"], cfg["force_N"]
        if not .015 <= cfg["close_m"] < width <= .040 or not 0 < force <= 1:
            raise ValueError("当前开口或力度配置超出已核实范围")
        expected = old["q"]
        if source_file.exists():
            src = read(source_file)
            if src.get("retreat_window"):
                # Terminal hold and intended *next* start are distinct. This
                # command must see the manually restored start before any TX.
                taught = read(session/src["run"]/"run.json")
                if src["retreat_window"]["source_id"] != taught["run_id"]:
                    raise ValueError("Source trajectory identity mismatch")
                expected = taught["marks"][0]["q"]
        row = healthy(dev, rx, grip)
        start = row["q_rad"]
        if (row["arm"]["motion_status"] != 0 or max(map(abs,start)) > math.radians(5)
                or gap(start,expected) > .35):
            raise ValueError("先在现场恢复到既有起点并确认 CAN/MOVE_J 到位")
        report.update(previous_hold=old, expected_open_m=width)
        h0.calibration_arrival(dev,start)
        agree(f"已退出示教，空载，手和工具已移开。在当前实测位置保持，复开至 {width*1000:g} mm")
        limits()
        q = healthy(dev,rx,grip)["q_rad"]
        if gap(q,start) > .1:
            raise ValueError("确认期间当前位置发生变化")
        h0.calibration_arrival(dev,q)
        active = True
        sender.arm(q,"fresh_stationary_anchor_after_interruption")
        normal_hold(q)
        report["settled_open_m"] = grip_at(width,force,"reopen_before_reteach",True)
        normal_hold(q)
        record_hold(q)
        active = False

    def teach():
        base = previous_hold()
        cfg = read(session / "setup.json")
        if abs(rx.current()[1]-cfg["open_m"]) > .002:
            raise ValueError("请先完成张开与开口实测")
        report.update(placement=a.placement, session_id=cfg["session_id"], marks=[], breaks=[])
        save(source_file, dict(pending=run.name))
        save(clear_file, dict(pending=run.name))
        with camera(run) as check:
            print("腕图记录已启动。在起点单击实体键，确认绿灯常亮，然后回车。")
            input()
            print('如需分段，在静止处 B 回车开始休息；保持同姿态，N 回车接续。全程继续记录。')
            boundary = None
            keys = ("start", "close", "open", "end")
            for event in keys:
                if event != "start":
                    required = {"close":"c","open":"o","end":"e"}[event]
                    print(f"{event}: 静止至少 1 秒，输入 {required.upper()} 并回车，继续静止 1 秒。", flush=True)
                next_display = 0.
                while True:
                    check()
                    row = snapshot(dev, rx, grip)
                    if event == 'end' and time.monotonic() >= next_display:
                        err = [round(math.degrees(v-b),2) for v,b in zip(row['q_rad'],base)]
                        print('示教中，当前减起点 J1–J6 (°)', err, '夹爪 mm',
                              round(row['width_m']*1000,2), flush=True)
                        next_display = time.monotonic()+1
                    st = row["arm"]
                    if (st["ctrl_mode"] != 2 or st["teach_status"] != 1 or
                            st["arm_status"] not in (0, 11) or any(st["err_status"].values())):
                        raise RuntimeError(f"未收到正常示教记录状态：{st}")
                    key = None if event == "start" else line()
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
                    if event == "start" or key == required:
                        if event in ("start","end") and gap(row["q_rad"],base) > .35:
                            if event == "start":
                                raise ValueError("示教起点偏离已建立的保持位")
                            print("请手拖回原起点后再输入 E。", flush=True)
                            continue
                        # The receive thread publishes these three fields together.
                        ident, ns, q = rx.joint_sample
                        report["marks"].append(dict(event=event, joint_id=ident, mono_ns=ns, q=q))
                        print(event, "已记", flush=True)
                        break
                    time.sleep(.02)
            print("软件记录结束。单击实体键退出示教，确认灯灭。不要双击。", flush=True)
        input("确认实体示教灯已经熄灭后回车：")
        released = snapshot(dev, rx, grip)
        st = released["arm"]
        if st["ctrl_mode"] not in (0,1,2) or (st["ctrl_mode"] == 2 and st["teach_status"] != 2):
            raise RuntimeError(f"灯灭后仍未收到停止示教的状态：{st}")
        report["released"] = released
        if stats()["tx_packets"] != report["interface_before"]["tx_packets"]:
            raise RuntimeError("手拖期间主机 TX 变化；该轨迹需排查")
        # Mark the source only after the receive-only run closed cleanly.

    def replay():
        nonlocal active
        cfg = read(session / "setup.json")
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
        if gap(base,points[0]["q"]) > .35 or (not window and gap(base,points[-1]["q"]) > .35):
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
                sender.call("speed", 5, lambda: dev.robot.set_speed_percent(5))
                sender.call("mode", "MOVE_J", lambda: dev.robot.set_motion_mode("j"))
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
                                active = False
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
        rx = Feedback(fback)
        dev.robot.get_context().register_parser_packet_fun(rx.packet)
        def interrupted(*_):
            raise KeyboardInterrupt("operator interrupt")
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        try:
            dev.connect()
            report["initial"] = snapshot(dev, rx, grip)
            if kind not in ("teach","status","prepare-pads"):
                tx = stack.enter_context((run/"tx.csv").open("x",newline="",buffering=1))
                commands = stack.enter_context((run/"commands.jsonl").open("x",buffering=1))
                sender = Sender(dev, grip, tx, commands)
            if kind == "status":
                time.sleep(2)
            elif kind == "limits":
                print(json.dumps(limits(), ensure_ascii=False))
            elif kind == "prepare":
                prepare()
            elif kind == "width-check":
                check_width()
            elif kind == "prepare-pads":
                prepare_pads()
            elif kind == "restart-teach":
                restart_teach()
            elif kind == "teach":
                teach()
            else:
                replay()
            report["complete"] = True
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
            if rx.error:
                report.update(complete=False, receive_error=rx.error)
            save(run / "run.json", report)
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


if __name__ == "__main__":
    main()
