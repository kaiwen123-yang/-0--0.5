"""Review a whole local replay and export only observed successes on the 50 ms grid."""
import argparse
import csv
import json
import math
import os
import subprocess
import struct
import tempfile
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from width_contract import CAMERA, REPRESENTATION, RETREAT, TERMINAL_VERSION, WIDTH, require_setup, require_width
from color_task import BLUE_RED, COLORS, recorded_task


PERIOD = 50_000_000
LEGACY_PROMPT = "Pick up the block, place it in the shallow tray, release it, and retreat."


def load(path):
    return json.loads(path.read_text())


def write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def csvrows(path):
    with path.open() as f:
        yield from csv.DictReader(f)


def distribution(values):
    a = np.array(values)
    if not a.size:
        return None
    return dict(n=len(a), min=float(a.min()), p50=float(np.median(a)),
                p95=float(np.percentile(a,95)), max=float(a.max()))


class Stream:
    def __init__(self, rows):
        self.rows = rows
        self.times = np.array([r["ns"] for r in rows], dtype=np.int64)
        if not rows or np.any(np.diff(self.times) <= 0):
            raise ValueError("Missing or unordered source stream")

    def at(self, ns):
        i = bisect_right(self.times, ns)-1
        if i < 0:
            raise ValueError("No causal source sample")
        return self.rows[i]


def submissions(path):
    tx = defaultdict(list)
    for f in csvrows(path / "tx.csv"):
        if f["result"] != "host_submitted" or f["error"]:
            raise ValueError(f"Unsuccessful CAN frame: {f}")
        tx[f["command_id"]].append(f)
    groups = defaultdict(list)
    seen = set()
    for line in (path/"commands.jsonl").read_text().splitlines():
        c = json.loads(line)
        frames = tx.get(c["id"], [])
        if (c["id"] in seen or c["result"] != "host_submitted" or not frames or
                c["frames"] != len(frames) or c["submitted_ns"] != int(frames[-1]["end_ns"])):
            raise ValueError(f"Missing/partial transaction {c['id']}")
        seen.add(c["id"])
        if c["kind"] not in ("arm","grip"):
            continue
        ids = [int(f["can_id"],16) for f in frames]
        raw = b"".join(bytes.fromhex(f["data"]) for f in frames)
        if c["kind"] == "arm" and ids == [0x155,0x156,0x157]:
            value = [math.radians(x*.001) for x in struct.unpack(">iiiiii",raw)]
        elif c["kind"] == "grip" and ids == [0x159] and raw[6] == 1:
            value = int.from_bytes(raw[:4],"big",signed=True)*1e-6
        else:
            raise ValueError(f"Unexpected wire IDs {ids}")
        if not np.allclose(value, c["actual"], rtol=0, atol=1e-12):
            raise ValueError("Transaction and payload disagree")
        groups[c["kind"]].append(dict(ns=c["submitted_ns"], start=int(frames[0]["start_ns"]),
                                      id=c["id"], value=value, source=c["source"]))
    if seen != set(tx):
        raise ValueError("Unaccounted CAN frames")
    for entries in groups.values():
        for i,entry in enumerate(entries):
            entry["until"] = entries[i+1]["start"] if i+1<len(entries) else None
    return Stream(groups["arm"]), Stream(groups["grip"]), sum(map(len,tx.values()))


def analyse(path):
    run = load(path/"run.json")
    if run["kind"] not in ("block","empty") or not run["complete"] or run["stop"] != "arrived_powered_hold":
        raise ValueError("Not a normally completed task replay")
    status = load(path/"rgb_status.json")
    if (status["boot_id"] != run["boot_id"] or status["camera_id"] != "CC16762023M" or
            status["queue_drops"] or status["error"] or run.get("final_unknown")):
        raise ValueError(f"Clock, final state or camera recorder error: {status}")
    images = Stream([dict(id=int(r["index"]),ns=int(r["mono_ns"]),unix=int(r["unix_ns"]),
                          header=int(r["header_ns"])) for r in csvrows(path/"rgb.csv")])
    if (len(images.rows) != status["written"] or status["received"] != status["written"] or
            any(r["id"]!=i or not (path/"rgb"/f"{i:07d}.png").is_file() for i,r in enumerate(images.rows))):
        raise ValueError("Incomplete original image sequence")
    sources = defaultdict(list)
    for r in csvrows(path/"feedback.csv"):
        sources[r["kind"]].append(dict(ns=int(r["mono_ns"]), id=int(r["id"]),
            first=int(r["first_ns"]), wire_span_ms=(float(r["wire_last_s"])-float(r["wire_first_s"]))*1e3,
            value=json.loads(r["values"])))
    arm, grip = Stream(sources["arm"]), Stream(sources["grip"])
    goals, openings, tx_count = submissions(path)
    delta = {k:v-run["interface_before"][k] for k,v in run["interface_after"].items()}
    if delta["tx_packets"] != tx_count or any(delta[k] for k in ("tx_errors","rx_errors","tx_dropped","rx_dropped")):
        raise ValueError(f"Unexpected CAN counters {delta}, sender frames {tx_count}")
    if [r["source"] for r in openings.rows] != ["initial_open","close","open"]:
        raise ValueError("Missing actual gripper sequence")
    begin, end = run["grid_start_ns"], run["grid_end_ns"]
    if end-begin < 10*PERIOD or images.times[0]>begin or images.times[-1]<end-PERIOD:
        raise ValueError("RGB or action window incomplete")
    times = np.arange(begin,end-PERIOD+1,PERIOD,dtype=np.int64)
    rows, states, actions, held = [], [], [], []
    ages = defaultdict(list)

    def coherent(t):
        # A bin may end while a 3-frame update is in flight. Use the last
        # coherent instant at/before that edge and disclose the exact offset.
        sample = t
        while True:
            a,g = goals.at(sample),openings.at(sample)
            starts = [v["until"] for v in (a,g) if v["until"] is not None and v["until"] <= sample]
            if not starts:
                return sample,a,g
            sample = min(starts)-1

    for tick in times:
        t = int(tick)
        i,q,g = images.at(t),arm.at(t),grip.at(t)
        for name,r in (("image",i),("joint",q),("grip",g)):
            age = (t-r["ns"])/1e6
            ages[name].append(age)
            if age > 100:
                raise ValueError(f"{name} stale at {t}: {age:.2f} ms")
        held_t, hq, hg = coherent(t)
        at,aq,ag = coherent(t+PERIOD)
        if at <= t:
            raise ValueError("No coherent target time in policy interval")
        states.append(q["value"]+[g["value"][0]])
        actions.append(aq["value"]+[ag["value"]])
        held.append(hq["value"]+[hg["value"]])
        rows.append(dict(t=t, image=i["id"], image_ns=i["ns"], image_header_ns=i["header"],
            q=q["id"], q_ns=q["ns"], grip=g["id"], grip_ns=g["ns"],
            state_age_ms=[ages[k][-1] for k in ("image","joint","grip")],
            triplet_host_span_ns=q["ns"]-q["first"], held_at_ns=held_t,
            held=[hq["id"],hg["id"]], action_at_ns=at, action=[aq["id"],ag["id"]],
            action_age_ms=[(at-aq["ns"])/1e6,(at-ag["ns"])/1e6],
            valid_from=[aq["ns"],ag["ns"]], valid_until_exclusive=[
                min(aq["until"] or end+1,end+1),min(ag["until"] or end+1,end+1)]))
    states, actions, held = map(np.asarray,(states,actions,held))
    gap_ms = np.diff(images.times)/1e6
    if gap_ms.max() > 100:
        raise ValueError(f"RGB gap {gap_ms.max():.1f} ms")
    moving = [r["ns"] for r in goals.rows if isinstance(r["source"],list)]
    intervals = np.diff(moving)/1e6
    gaps = []
    for idx in np.flatnonzero(intervals > 100):
        start, end_ns = moving[idx:idx+2]
        events = [r["source"] for r in openings.rows if start <= r["ns"] <= end_ns]
        pauses = [p["key"] for p in run.get("pauses",[]) if start <= p["at_ns"] <= end_ns]
        gaps.append(dict(after_ns=start, before_ns=end_ns, ms=float(intervals[idx]),
                         gripper_events=events, operator_keys=pauses))
    metrics = dict(arm_submissions=len(goals.rows),gripper_submissions=len(openings.rows),
        reference_gaps_over_100ms=gaps, images=len(images.rows), grid_rows=len(rows), joint_groups=len(arm.rows),
        gripper_rows=len(grip.rows), host_frames=tx_count, queue_drops=status["queue_drops"],
        rejected_triplets=run["rejected_triplets"], interface_delta=delta, feedback_age_ms={
            k:distribution(v) for k,v in ages.items()}, rgb_interval_ms=distribution(gap_ms),
        header_to_receive_ms=distribution([(i["unix"]-i["header"])/1e6 for i in images.rows]),
        triplet_host_span_ms=distribution([(q["ns"]-q["first"])/1e6 for q in arm.rows]),
        triplet_wire_span_ms=distribution([q["wire_span_ms"] for q in arm.rows]),
        reference_interval_including_dwell_ms=distribution(np.diff(moving)/1e6),
        max_axis_tracking_error_deg=distribution(np.max(np.abs(np.degrees(states[:,:6]-held[:,:6])),axis=1)),
        events=run["events"], final=run["final"], pauses=run.get("pauses",[]),
        host_submit_duration_ms=distribution([(r['ns']-r['start'])/1e6 for r in goals.rows]),
        representative_association=dict(rows[len(rows)//2], measured=states[len(rows)//2].tolist(),
                                        submitted_next=actions[len(rows)//2].tolist(),
                                        submitted_hold=held[len(rows)//2].tolist()))
    return run,times,rows,states,actions,held,metrics


def review(path, failed, actual, intervention):
    path = path.resolve()
    if not (path/"run.json").exists():
        candidates = sorted([p for p in path.iterdir() if p.name.endswith(("_empty","_block"))])
        if not candidates:
            raise ValueError("此会话尚无空场或实物重放")
        path = candidates[-1]
    print("复核", path)
    run = load(path/"run.json")
    color_block = run["kind"] == "block" and "target_color" in run
    if color_block and (path/"review.json").exists():
        raise FileExistsError("该实物运行已有审核；原判定保留在 " + str(path/"review.json"))
    result = dict(approved_empty=False, approved_block=False)
    def observed_result():
        grasped = actual or input("实际夹起颜色 blue/red/white/green，抓空 none，看不清 unknown：").strip()
        assisted = intervention or input("人工介入 yes/no，无法判定 unknown：").strip()
        if grasped not in (*COLORS, "none", "unknown") or assisted not in ("yes", "no", "unknown"):
            raise ValueError("请选择实际观测值；无法判定填 unknown")
        result.update(recorded_task(run), actual_grasped_color=grasped, intervention=assisted,
                      source_trajectory_id=run["source_trajectory_id"], session_id=run["session_id"],
                      placement=run["placement"])
        return grasped == run["target_color"] and assisted == "no"

    try:
        if failed:
            if color_block:
                observed_result()
            result.update(run_id=load(path/'run.json')['run_id'], verdict=failed)
            result["outcome"] = "failed"
            print('已保留失败阶段与原因。')
            return
        run,t,rows,state,act,held,metrics = analyse(path)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(4,2,figsize=(11,9),sharex=True)
        for i,ax in enumerate(axes.flat[:7]):
            scale = 180/math.pi if i<6 else 1000
            ax.plot((t-t[0])/1e9, held[:,i]*scale, label="submitted hold", lw=1)
            ax.plot((t-t[0])/1e9, state[:,i]*scale, label="measured", lw=.8)
            ax.set_ylabel(f"J{i+1} (deg)" if i<6 else "SDK width (mm)")
        axes.flat[0].legend()
        axes.flat[6].set_xlabel("Time (s)")
        axes.flat[7].set_visible(False)
        fig.tight_layout()
        fig.savefig(path/"trajectory.png",dpi=130)
        plt.close(fig)
        write(path/"quality.json",metrics)
        print(json.dumps({k:v for k,v in metrics.items() if k not in ("final","representative_association")},
                         ensure_ascii=False,indent=2))
        print('播放全程腕图。按实际时间的间隔见 quality.json；视频按 30 fps 显示。', flush=True)
        subprocess.run(['ffplay','-autoexit','-loglevel','error','-framerate','30','-i',
                        str(path/'rgb'/'%07d.png')], check=True)
        print('打开全程目标与实测轨迹', path/'trajectory.png', flush=True)
        subprocess.Popen(['xdg-open',str(path/'trajectory.png')],start_new_session=True)
        if run["kind"]=="empty":
            print("核对无方块、盘沿/线缆间隙、实际开合、P/R 暂停恢复和末端保持。")
            ok = run["pause_resume_verified"]
        else:
            print("核对夹起、转移、落盘、张开后留盘、退回，全程无人介入。")
            ok = not run.get("pauses")
            if color_block:
                print("本条原始指令", run["prompt"])
                matched = observed_result()
                ok = ok and matched
        verdict = input("完整观看并符合以上条件输入 PASS；其余输入失败阶段/原因：").strip()
        approved = verdict=="PASS" and bool(ok)
        result["outcome"] = "success" if approved else "failed"
        if color_block and not approved:
            result["operator_verdict"] = verdict
            grasped = result["actual_grasped_color"]
            if grasped != run["target_color"]:
                verdict = {"none":"no_grasp", "unknown":"unknown_grasp"}.get(grasped, "wrong_color")
            elif result["intervention"] != "no":
                verdict = "intervention_" + result["intervention"]
            elif verdict == "PASS":
                verdict = "paused_block"
        result.update(verdict=verdict, run_id=run["run_id"], use=run["use"],
                      approved_empty=approved and run["kind"]=="empty",
                      approved_block=approved and run["kind"]=="block")
        print("审核通过" if approved else "保留原始记录，未通过审核")
    except Exception as exc:
        result["error"] = repr(exc)
        raise
    finally:
        if color_block:
            if "run_id" in result:
                with (path/"review.json").open("x") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
        else:
            write(path/"review.json",result)


def freeze_attempts(requested):
    """Assign all formal block attempts to their session split before selecting successes."""
    attempts, groups = {}, {}
    for split in ("train", "validation"):
        if not requested[split]:
            raise ValueError(f"Missing {split} sessions")
        for item in requested[split]:
            session = item.resolve()
            single = (session/"run.json").is_file()
            if single:
                session = session.parent
            allocation = load(session/"session.json")
            if allocation["split"] != split:
                raise ValueError(f"Wrong split for {session}")
            paths = [item.resolve()] if single else sorted(session.glob("*_block"))
            for path in paths:
                run = load(path/"run.json")
                if run["kind"] != "block" or run["use"] != "formal":
                    continue
                ident = run["run_id"]
                if ident in attempts or run.get("session_id", allocation["session_id"]) != allocation["session_id"]:
                    raise ValueError(f"Duplicate run or session mismatch: {path}")
                record = dict(run_id=ident, raw_directory=str(path), split=split,
                              session_id=allocation["session_id"], complete=run["complete"])
                for key in ("placement", "source_trajectory_id", "requested_task"):
                    if key in run:
                        record[key] = run[key]
                for key in ("session_id", "placement", "source_trajectory_id"):
                    if key in record and groups.setdefault((key,record[key]),split) != split:
                        raise ValueError(f"Group crosses splits: {key}={record[key]}")
                if "target_color" in run:
                    record.update(recorded_task(run))
                review_file = path/"review.json"
                record.update(approved_block=False, outcome="unreviewed", actual_grasped_color="unknown",
                              intervention="unknown")
                if review_file.is_file():
                    reviewed = load(review_file)
                    if reviewed.get("run_id") != ident:
                        raise ValueError(f"Review does not identify this run: {path}")
                    record.update({k:reviewed[k] for k in ("outcome", "approved_block", "verdict", "operator_verdict",
                                  "actual_grasped_color", "intervention") if k in reviewed})
                    if "target_color" in run and recorded_task(reviewed) != recorded_task(run):
                        raise ValueError(f"Review changed the original task: {path}")
                    if record["approved_block"] and (record["outcome"] != "success" or not run["complete"]
                            or not record.get("target_color") or record["intervention"] != "no"
                            or record["actual_grasped_color"] != record["target_color"]):
                        raise ValueError(f"Success review missing matching observed result: {path}")
                attempts[ident] = record
    return attempts


def export(a):
    requested = {s:getattr(a,s) or [] for s in ("commissioning","train","validation")}
    if bool(requested["commissioning"]) == bool(requested["train"] or requested["validation"]):
        raise ValueError("联调单独导出；正式集需要 train 和 validation")
    formal = not requested["commissioning"]
    seen, groups, entries, manifests = set(), {}, [], []
    out = a.output.resolve()
    if out.exists():
        raise FileExistsError(out)
    attempts = freeze_attempts(requested) if formal else {}
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as stage:
        tmp = Path(stage)/"dataset"
        tmp.mkdir()
        for split,items in requested.items():
            for item in items:
                item = item.resolve()
                paths = [item] if (item/"run.json").is_file() else sorted(item.glob("*_block"))
                eligible = 0
                for path in paths:
                    rp = path/"review.json"
                    if formal:
                        if not attempts.get(load(path/"run.json")["run_id"], {}).get("approved_block"):
                            continue
                    elif not rp.exists() or not load(rp).get("approved_block"):
                        continue
                    run,t,rows,states,actions,_,metrics = analyse(path)
                    if run["use"] != ("formal" if formal else "commissioning_only"):
                        continue
                    if run["kind"] != "block" or load(rp)["run_id"] != run["run_id"]:
                        raise ValueError("Review/run mismatch")
                    contract = {}
                    if formal:
                        cfg = load(path.parent/"setup.json")
                        require_setup(cfg)
                        require_width(run)
                        taught = load(Path(run["source_directory"])/"run.json")
                        task = recorded_task(run)
                        if recorded_task(taught) != task:
                            raise ValueError(f"Instruction differs from taught source: {path}")
                        end = load(Path(run["source_directory"])/"task_end.json")
                        if (run.get("split") != split or cfg["split"] != split
                                or run["session_id"] != cfg["session_id"] or run.get("pauses")
                                or run.get("terminal_kind") != RETREAT or run.get("retreat_window")
                                or run.get("terminal_version") != TERMINAL_VERSION
                                or not taught["complete"] or taught["kind"] != "teach"
                                or taught["run_id"] != run["source_trajectory_id"]
                                or run.get("task_end") != end or end != taught["marks"][-1]
                                or taught["placement"] != run["placement"]
                                or taught["session_id"] != cfg["session_id"]
                                or not end["operator_empty_retreat"]):
                            raise ValueError("Formal block, declared split or normal source E mismatch")
                        contract = dict(gripper_basis=WIDTH, terminal_kind=RETREAT,
                                        terminal_version=TERMINAL_VERSION, training_eligible=True, split=split)
                        attempt = attempts[run["run_id"]]
                        contract.update(task, run_id=run["run_id"], actual_grasped_color=attempt["actual_grasped_color"],
                                        intervention=attempt["intervention"], outcome=attempt["outcome"])
                    ident = run["run_id"]
                    if ident in seen:
                        raise ValueError("Duplicate episode")
                    seen.add(ident)
                    for key in ("session_id","placement","source_trajectory_id"):
                        group = (key,run[key])
                        if groups.setdefault(group,split) != split:
                            raise ValueError(f"Group crosses splits: {group}")
                    eligible += 1
                    ep = tmp/ident
                    ep.mkdir()
                    for name,arr in (("state",states.astype("float32")),("actions",actions.astype("float32")),
                                     ("policy_timestamps_ns",t)):
                        np.save(ep/f"{name}.npy",arr,allow_pickle=False)
                    rgb = np.lib.format.open_memmap(ep/"camera_rgb.npy",mode="w+",dtype="uint8",
                                                    shape=(len(rows),480,640,3))
                    for j,r in enumerate(rows):
                        with Image.open(path/"rgb"/f"{r['image']:07d}.png") as im:
                            if im.mode!="RGB" or im.size!=(640,480):
                                raise ValueError("Unexpected original RGB")
                            rgb[j] = np.asarray(im)
                    rgb.flush()
                    del rgb
                    with (ep/"row_sources.jsonl").open("x") as f:
                        for r in rows:
                            f.write(json.dumps(r,separators=(",",":"))+"\n")
                    manifests.append(dict(directory=ident, raw_directory=str(path), boot_id=run["boot_id"],
                        calibration_commit=run["calibration_commit"], calibration=run["calibration"],
                        retreat_window=run.get("retreat_window"),
                        reset_between_runs=run.get("reset_between_runs"),
                        gripper_basis=run.get("gripper_basis","sdk_width_m"),
                        pad_measurements=run.get("pad_measurements",[]),
                        source_trajectory_id=run["source_trajectory_id"], session_id=run["session_id"],
                        placement_id=run["placement"], sources=f"{ident}/row_sources.jsonl"))
                    if formal:
                        manifests[-1].update(contract, installation=cfg["installation"],
                                             task_end=end, measurement_file=cfg["measurement_file"])
                    entries.append(dict(directory=ident,frames=len(rows), **({"split":split,
                                        "prompt":run.get("prompt",LEGACY_PROMPT)} | contract)))
                if not eligible and not formal:
                    raise ValueError(f"No reviewed {split} successes in {item}")
        if formal:
            if {e["split"] for e in entries} != {"train","validation"}:
                raise ValueError("Need reviewed formal successes in both independent splits")
            write(tmp/"attempts.json",list(attempts.values()))
        dataset_contract = dict(gripper_basis=WIDTH, collection_view="all_colors") if formal else {}
        write(tmp/"alignment_manifest.json",dict(**dataset_contract,episodes=manifests,period_ns=PERIOD,
              observation="last received RGB, joint group and gripper at or before t",
              action="latest coherent complete host targets at the end of (t,t+50ms]; bounded by episode",
              chunk="10 rows, repeat final row at episode boundary"))
        write(tmp/"dataset.json",dict(data_kind="real_demonstrations",camera_mount="wrist",
              camera_id=CAMERA,training_eligible=bool(formal),policy_hz=20,**dataset_contract,
              action_representation=REPRESENTATION if formal else "absolute_joint_targets_and_total_opening",
              timestamp_alignment_source="alignment_manifest.json"))
        write(tmp/"index.json",entries)
        from dataset import SingleCameraDataset
        for split in set(e["split"] for e in entries):
            ds = SingleCameraDataset(tmp,split,10,20)
            for entry, idx in zip(ds.entries, ds.ends-1, strict=True):
                row = ds[int(idx)]
                if row["prompt"] != entry["prompt"]:
                    raise ValueError("Reader changed the episode instruction")
                if not np.all(row["actions"] == row["actions"][0]):
                    raise ValueError("Reader did not pad at episode boundary")
        tmp.rename(out)
    print(out, "episodes",len(entries),"rows",sum(e["frames"] for e in entries))


def blue_red_view(master, output):
    from dataset import formal_entries, training_data_requirements
    master, output = master.resolve(), output.resolve()
    metadata = load(master/"dataset.json")
    if metadata.get("collection_view") != "all_colors" or not (master/"attempts.json").is_file():
        raise ValueError("Stage A requires a frozen full collection")
    if output == master or master in output.parents or output.exists():
        raise ValueError("Choose a new output outside the full collection")
    entries = [e for e in formal_entries(master,"wrist",20) if e["target_color"] in BLUE_RED]
    alignment = load(master/metadata["timestamp_alignment_source"])
    ids = {e["directory"] for e in entries}
    alignment["episodes"] = [m for m in alignment["episodes"] if m["directory"] in ids]
    alignment["collection_view"] = "blue_red"
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as stage:
        tmp = Path(stage)
        for ident in ids:
            (tmp/ident).symlink_to(os.path.relpath(master/ident, tmp), target_is_directory=True)
        write(tmp/"index.json",entries)
        write(tmp/"alignment_manifest.json",alignment)
        write(tmp/"dataset.json",dict(metadata, collection_view="blue_red",
              master_directory=os.path.relpath(master, tmp), target_colors=list(BLUE_RED)))
        missing = training_data_requirements(tmp, "wrist", 20)
        if missing:
            raise ValueError(missing)
        tmp.rename(output)
    print(output, {s:{c:sum(e["split"] == s and e["target_color"] == c for e in entries)
                          for c in BLUE_RED} for s in ("train","validation")})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="op",required=True)
    sp = sub.add_parser("review",help="检查一次重放；会话目录自动选最近执行")
    sp.add_argument("path",type=Path)
    sp.add_argument('--failed', metavar='原因', help='保留失败阶段和人工介入原因')
    sp.add_argument("--actual-grasped-color", choices=(*COLORS, "none", "unknown"))
    sp.add_argument("--intervention", choices=("yes", "no", "unknown"))
    sp = sub.add_parser("export",help="导出审核通过的完整真机数据")
    sp.add_argument("output",type=Path)
    for name in ("commissioning","train","validation"):
        sp.add_argument("--"+name,type=Path,nargs="+")
    sp = sub.add_parser("stage-a",help="从已冻结的四色主库派生蓝红目标视图")
    sp.add_argument("master",type=Path)
    sp.add_argument("output",type=Path)
    a = p.parse_args()
    if a.op=="review":
        review(a.path,a.failed,a.actual_grasped_color,a.intervention)
    elif a.op == "stage-a":
        blue_red_view(a.master,a.output)
    else:
        export(a)


if __name__=="__main__":
    main()
