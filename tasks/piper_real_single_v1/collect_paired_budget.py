"""Resume 20 independent training layouts and five validation layouts, blue/red per layout."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys

from color_task import BLUE_RED, COLORS, task_for
from prepare_passive_session import prepare


DATA = Path("/home/kaiwen/research/pi-q12-data")
DEMO = Path(__file__).resolve().with_name("pi_demo.sh")
LAYOUTS = (
    ("T01-RB02", "既有红蓝原布局，按现场记录复原"),
    ("T01-RB03", "既有红蓝交换布局，按现场记录复原"),
    ("T01-RB04", "蓝左近、红右远"),
    ("T01-RB05", "蓝右近、红左远"),
    ("T01-FOUR01", "蓝左远、红右近；白右远、绿中间"),
    ("T01-FOUR02", "蓝右远、红左近；白左远、绿右中"),
    ("T01-RB06", "蓝中近、红左中"),
    ("T01-FOUR03", "蓝中远、红右中；白左近、绿左远"),
    ("T01-FOUR04", "蓝右中、红左远；白中近、绿右远"),
    ("T01-FOUR05", "蓝左中、红中近；白右远、绿右近"),
    ("T02-RB01", "蓝左近、红中远"),
    ("T02-FOUR01", "蓝右近、红中远；白右中、绿左远"),
    ("T02-RB02", "蓝右远、红中近"),
    ("T02-FOUR02", "蓝中近、红左远；白右远、绿右近"),
    ("T02-RB03", "蓝中远、红左近"),
    ("T02-FOUR03", "蓝左中、红右近；白中远、绿左近"),
    ("T02-RB04", "蓝右中、红左中"),
    ("T02-FOUR04", "蓝右远、红中间；白左中、绿中近"),
    ("T02-RB05", "蓝左远、红中间"),
    ("T02-FOUR05", "蓝中间、红右远；白左远、绿左近"),
    ("V01-FOUR01", "验证会话既有独立四色布局，按现场记录复原"),
    ("V01-RB01", "独立重摆；蓝中间偏右近、红左后偏中"),
    ("V01-FOUR02", "独立重摆；蓝左后偏中、红中前偏左；白右近、绿右远"),
    ("V01-RB02", "独立重摆；蓝中后偏右、红左前偏中"),
    ("V01-FOUR03", "独立重摆；蓝左中偏近、红右后偏中；白右中、绿中前"),
)


def read(path):
    return json.loads(path.read_text())


def session_for(code):
    return DATA / f"pickplace_20261124_{code}"


def split_for(code):
    return "validation" if code == "V01" else "train"


def scene_for(placement):
    return COLORS if "-FOUR" in placement else BLUE_RED


def success_receipts(session, allocation):
    successes = {}
    known = dict(LAYOUTS)
    for review_file in sorted(session.glob("*_teach/review.json")):
        review = read(review_file)
        if review.get("approved_teach") is not True or review.get("placement") not in known:
            continue
        path = review_file.parent
        run = read(path / "run.json")
        task = read(path / "task.json")
        placement, target = review["placement"], review["target_color"]
        if target not in BLUE_RED:
            continue
        expected = dict(run_id=run["run_id"], session_id=allocation["session_id"], placement=placement,
                        **task_for(target, scene_for(placement)))
        if (not placement.startswith(allocation["code"] + "-")
                or run.get("split") != allocation["split"]
                or not all(all(record.get(k) == v for k, v in expected.items()) for record in (run, task, review))
                or run.get("complete") is not True or run.get("use") != "formal"
                or run.get("collection_mode") != "kinesthetic_manual_gripper_v1"
                or run.get("read_only") is not True or run.get("stop") != "demonstration_finished"
                or run.get("operator_outcome") != "success" or review.get("outcome") != "success"
                or review.get("verdict_source") != "operator_success_key"
                or review.get("actual_grasped_color") != target or review.get("intervention") != "no"
                or any(r.get("source_trajectory_id") != run["run_id"] for r in (run, review))
                or run["interface_before"]["tx_packets"] != run["interface_after"]["tx_packets"]
                or [m["event"] for m in run["marks"]] != ["start", "close", "open", "end"]
                or read(path / "task_end.json") != run["marks"][-1]):
            raise ValueError(f"成功回执与任务、来源或结束状态不符，请核对 {path}")
        successes.setdefault((placement, target), []).append((run["run_id"], path))
    return successes


def allocations():
    result = {}
    for code in ("T01", "T02", "V01"):
        session = session_for(code)
        allocation = read(session / "session.json")
        if (Path(allocation["session_directory"]).resolve() != session.resolve()
                or allocation["split"] != split_for(code)):
            raise ValueError(f"会话分配与目录或 split 不符：{session}")
        result[code] = dict(allocation, code=code)
    if len({alloc["session_id"] for alloc in result.values()}) != len(result):
        raise ValueError("训练及验证采集需要各自独立的 session_id")
    return result


def check_recorder_available():
    with open("/tmp/dog_and_arm_piper_motion.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("当前采集器正在使用，请等本条封存后再接队列") from None


def missing_task_end(run):
    """A stopped passive demonstration with no confirmed end can be retried at S."""
    return (run.get("read_only") is True and not run.get("complete")
            and not any(run.get(k) for k in ("error", "receive_error", "final_unknown"))
            and (run.get("source_rejection") or "").endswith("缺少确认的任务终点")
            and run.get("final", {}).get("arm", {}).get("teach_status") == 2)


def collect():
    allocation = allocations()
    existing = {}
    for code, entry in allocation.items():
        existing.update(success_receipts(session_for(code), entry))
    identities = [ident for group in existing.values() for ident, _ in group]
    if len(identities) != len(set(identities)):
        raise ValueError("不同录制目录复用了同一条示范来源")
    done = len(existing)
    print(f"50 个布局目标中已有 {done} 个真实成功。", flush=True)
    # Finish any previously half-completed layout before asking for a new placement.
    def unfinished_pair(item):
        covered = sum((item[0], color) in existing for color in BLUE_RED)
        return covered != 1
    for placement, layout in sorted(LAYOUTS, key=unfinished_pair):
        code = placement.split("-")[0]
        session = session_for(code)
        for target in BLUE_RED:
            key = placement, target
            if key in existing:
                continue
            consecutive_abnormal = 0
            while True:
                check_recorder_available()
                if not (session / "setup.json").is_file():
                    prepare(session, session_for("T01"))
                print(f"\n[{done+1}/50] {code} {allocation[code]['split']} · {placement} · "
                      f"抓{'蓝' if target == 'blue' else '红'} · {layout}。", flush=True)
                if target == "red":
                    print("请把蓝块和全部方块放回本布局原位，浅盘固定。", flush=True)
                print("本布局在腕图中可辨、浅盘固定、实体示教绿灯常亮，在公共起点停稳后按 S。"
                      "看到 start 已记再手拖。实际夹住后 C，实际释放后 O；入盘且空爪抬离停稳后 E，失败 F。", flush=True)
                while True:
                    answer = input("S 回车开始本条录制；Q 回车保存进度并退出：").strip().lower()
                    if answer == "q":
                        return 0
                    if answer == "s":
                        break
                check_recorder_available()
                receipts = success_receipts(session, allocation[code]).get(key)
                if receipts:
                    done += 1
                    print(f"该布局目标已有真实成功回执，直接接下一条：{receipts[0][1]}", flush=True)
                    break
                before = set(session.glob("*_teach"))
                cmd = ["bash", str(DEMO), "teach", str(session), placement, "--passive-capture",
                       "--target-color", target, "--scene-colors", *scene_for(placement)]
                rc = subprocess.run(cmd).returncode
                created = set(session.glob("*_teach")) - before
                if len(created) != 1:
                    raise RuntimeError(f"无法唯一识别本次录制，退出码 {rc}，新增目录 {sorted(created)}")
                path, = created
                if not (path / "run.json").is_file():
                    raise RuntimeError(f"未得到完整 run.json，请查看终端错误；目录 {path}，退出码 {rc}")
                run = read(path / "run.json")
                receipts = success_receipts(session, allocation[code]).get(key, [])
                if rc == 0 and (run["run_id"], path) in receipts:
                    done += 1
                    print(f"已收 {done}/50：{path}", flush=True)
                    break
                reason = run.get("error") or run.get("source_rejection") or run.get("operator_outcome") or f"退出码 {rc}"
                print(f"本条未推进，原始记录保存在 {path}。{reason}", flush=True)
                if not any(m["event"] == "start" for m in run.get("marks", [])):
                    raise RuntimeError("任务窗口开始前退出，请处理上述原因后重启队列")
                if rc < 0 or "KeyboardInterrupt" in str(reason):
                    raise RuntimeError("操作员已中止队列")
                if run.get("operator_outcome") == "failed" and not run.get("error"):
                    consecutive_abnormal = 0
                    print("按 F 的失败示范已保留，复原本布局后重录同一目标。", flush=True)
                    continue
                if missing_task_end(run):
                    consecutive_abnormal = 0
                    print("灯已灭，但未记到完整终点。原始数据已保存，进度不变；复原后按 S 重录。", flush=True)
                    continue
                consecutive_abnormal += 1
                if consecutive_abnormal >= 2:
                    raise RuntimeError("同一目标连续异常两次，已停止，请核对最近的录制回执")
                while True:
                    answer = input("排除原因后输入 retry 重录，或 Q 退出：").strip().lower()
                    if answer == "retry":
                        break
                    if answer == "q":
                        return 1
    print("已完成全部 50 个真实蓝红配对目标：训练 20 对、独立验证 5 对。", flush=True)
    return 0


def main():
    if not sys.stdin.isatty():
        raise RuntimeError("请从可操作的现场交互终端启动队列")
    with (DATA / ".pi_blue_red_50.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("已有一份蓝红配对队列在运行") from None
        return collect()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        sys.exit("队列已停，成功及失败记录均保留。")
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        sys.exit(str(error))
