"""Source-native 20 Hz supervision. Read the frozen audit; never write to it."""
import argparse
import csv
import json
from fractions import Fraction
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "contracts.json").read_text())
PERIOD = CONFIG["period_ns"]
HORIZON = CONFIG["horizon"]


def read_json(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ranges(indices):
    groups = np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1)
    return " ".join(f"{g[0]}-{g[-1]}" for g in groups if len(g))


def video_clock(audit, video, n):
    stream = read_json((audit / "checks/video" / video).with_suffix(".json"))["streams"][0]
    assert stream["n"] == n and not stream["errors"] and stream["pts_missing"] == 0
    hist = dict(stream["pts_delta_hist"])
    # The historical audit picked the first most-frequent difference in presentation order.
    exceptions = dict(stream["pts_anomalies"])
    for mode, count in hist.items():
        if count != max(hist.values()):
            continue
        pts = [stream["pts_first"][0]]
        for i in range(1, n):
            pts.append(exceptions.get(i, pts[-1] + mode))
        if pts[-1] == stream["pts_last"][0] and np.all(np.diff(pts) > 0):
            tb = Fraction(stream["time_base"])
            ns = np.rint((np.array(pts)-pts[0]) * (float(tb)*1e9)).astype("int64")
            return np.array(pts), ns
    raise ValueError(f"Cannot reconstruct presentation times for {video}")


def derive(audit, out, source, spec, meta, ep):
    idx = ep["episode_index"]
    fmt = dict(episode_chunk=idx//meta["chunks_size"], episode_index=idx, video_key=spec["camera"])
    path = Path(source) / meta["data_path"].format(**fmt)
    video = Path(source) / meta["video_path"].format(**fmt)
    table = pq.read_table(audit/"raw"/path)
    state, action = [np.stack(table[k].to_numpy()) for k in (spec["state"], spec["action"])]
    n = len(state)
    assert n == ep["length"] and state.shape == action.shape == (n, spec["dims"])
    assert np.array_equal(table["frame_index"].to_numpy(), np.arange(n))
    assert np.all(table["episode_index"].to_numpy() == idx)
    timestamp = table["timestamp"].to_numpy()
    clocks = {}
    if spec["clock"] == "nominal_frame_30hz":
        # Use the declared rational clock, avoiding float32 round-off at coincident edges.
        assert np.allclose(timestamp, np.arange(n)/30, atol=2e-6, rtol=0)
        ns = (np.arange(n, dtype="int64") * 1_000_000_000 + 15)//30
    else:
        original = table[spec["clock"]].to_numpy()
        ns = np.rint((original-original[0])*1e9).astype("int64")
        for k in ("real_observation_timestamp_s","real_observation_wall_time_ns",
                  "real_action_timestamp_s","real_action_wall_time_ns"):
            clocks[k] = table[k].to_numpy()
        assert np.array_equal(action[:-1], state[1:])
    assert np.all(np.diff(ns) > 0)
    pts, video_ns = video_clock(audit, video, n)
    ticks = np.arange(0, ns[-1]+1, PERIOD)
    future = ticks + PERIOD
    obs = np.searchsorted(ns, ticks, side="right") - 1
    target = np.searchsorted(ns, future, side="right") - 1
    frame = np.searchsorted(video_ns, ticks, side="right") - 1
    assert np.all(ns[obs] <= ticks) and np.all(ns[target] <= future) and np.all(video_ns[frame] <= ticks)
    segments = np.r_[0, np.cumsum(np.diff(ns) > CONFIG["max_gap_ns"])]
    missing = (future > ns[-1]) | (ns[target] <= ticks)
    crossing = (segments[obs] != segments[target]) | (segments[frame] != segments[obs])
    # A tick inside a long gap is invalid even if a following tick lands well beyond it.
    waiting = (obs < n-1) & (segments[np.minimum(obs+1,n-1)] != segments[obs]) & (ticks > ns[obs])
    stale = (ticks-ns[obs] > PERIOD) | (ticks-video_ns[frame] > PERIOD)
    finite = np.all(np.isfinite(state), axis=1)
    invalid_prefix = np.r_[0,np.cumsum(~finite)]
    invalid = invalid_prefix[target+1] != invalid_prefix[obs]
    valid = ~(missing | crossing | waiting | stale | invalid)
    starts = np.flatnonzero(np.lib.stride_tricks.sliding_window_view(valid,HORIZON).all(axis=1)) if len(valid)>=HORIZON else np.array([],dtype=int)
    if len(starts):
        assert np.all(segments[obs[starts]] == segments[target[starts+HORIZON-1]])
    target_values = state[target].copy()
    target_values[missing] = np.nan
    directory = out/source/f"{idx:06d}"
    directory.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(directory/"grid.npz", query_ns=ticks, target_query_ns=future,
                        obs_row=obs, target_row=target, image_frame=frame, image_pts=pts[frame],
                        image_ns=video_ns[frame], obs_ns=ns[obs], target_ns=ns[target],
                        obs_age_ns=ticks-ns[obs], image_age_ns=ticks-video_ns[frame],
                        target_age_ns=future-ns[target], span_ns=ns[target]-ns[obs],
                        obs_raw_timestamp=timestamp[obs], target_raw_timestamp=timestamp[target],
                        obs_repeat=np.r_[False,np.diff(obs)==0], target_repeat=np.r_[False,np.diff(target)==0],
                        image_repeat=np.r_[False,np.diff(frame)==0], missing=missing,
                        gap=crossing|waiting, stale=stale, invalid_source=invalid,
                        padded=np.zeros(len(ticks),bool), segment=segments[obs], valid=valid,
                        state=state[obs], original_action=action[obs], future_state=target_values,
                        starts=starts, **{"obs_"+k:v[obs] for k,v in clocks.items()},
                        **{"target_"+k:v[target] for k,v in clocks.items()})
    note = dict(source=source,episode=idx,revision=spec["revision"],parquet=str(path),
                video=str(video),camera=spec["camera"],prompt=ep["tasks"][0],clock=spec["clock"],
                label="derived from future source state",version=CONFIG["version"],local_eligible=False)
    (directory/"source.json").write_text(json.dumps(note,indent=2))
    span = (ns[target]-ns[obs])[valid]/1e6
    return dict(**note,source_rows=n,grid_rows=len(ticks),valid_rows=int(valid.sum()),starts=len(starts),
                start_ranges=ranges(starts),gap_after_source_rows=ranges(np.flatnonzero(np.diff(ns)>CONFIG["max_gap_ns"])),
                missing_rows=int(missing.sum()),gap_rows=int((crossing|waiting).sum()),stale_rows=int(stale.sum()),
                span_min_ms=span.min(),span_p50_ms=np.median(span),span_max_ms=span.max(),
                span_33ms=int(np.sum(np.round(span)==33)),span_67ms=int(np.sum(np.round(span)==67)),
                pad_slots=0,second_arm_max_joint_range=float(np.ptp(state[:,7:13],axis=0).max()) if spec["dims"]==14 else "",
                second_gripper_range=float(np.ptp(state[:,13])) if spec["dims"]==14 else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audit",type=Path)
    ap.add_argument("out",type=Path)
    ap.add_argument("--pilot",action="store_true")
    args=ap.parse_args()
    if args.out.resolve().is_relative_to(args.audit.resolve()):
        ap.error("Use a separate output directory")
    rows=[]
    pilot={"A":{0,152},"C":{31},"stack-bowls":{0,203,260,319,371}}
    for source,spec in CONFIG["sources"].items():
        lock=read_json(args.audit/"sources"/(source+".json"))
        assert lock["sha"] == spec["revision"]
        base=args.audit/"raw"/source/"meta"
        meta=read_json(base/"info.json")
        for line in (base/"episodes.jsonl").read_text().splitlines():
            ep=json.loads(line)
            if not args.pilot or ep["episode_index"] in pilot[source]:
                rows.append(derive(args.audit,args.out,source,spec,meta,ep))
    write_csv(args.out/("pilot.csv" if args.pilot else "episodes.csv"),rows)


if __name__=="__main__":
    main()
