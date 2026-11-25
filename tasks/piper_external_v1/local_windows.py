"""Read the frozen valid starts, quality flags, event timestamps and group identities."""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from derive import ranges, read_json, write_csv


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    ap.add_argument("out",type=Path)
    args=ap.parse_args()
    records=[]
    phases=[]
    groups={}
    totals={}
    metadata=read_json(args.root/"dataset.json")
    alignment=read_json(args.root/metadata["timestamp_alignment_source"])
    aligned={e["directory"]:e for e in alignment["episodes"]}
    for e in read_json(args.root/"index.json"):
        key=e["directory"]
        p=args.root/key
        n=e["frames"]
        starts=np.load(p/e["valid_action_starts"],mmap_mode="r")
        ticks=np.load(p/"policy_timestamps_ns.npy",mmap_mode="r")
        trace=[json.loads(line) for line in (p/"row_sources.jsonl").read_text().splitlines()]
        valid=np.array([r["training_row_valid"] for r in trace])
        window=np.minimum(np.arange(n)[:,None]+np.arange(10),n-1)
        assert np.array_equal(np.flatnonzero(valid[window].all(axis=1)),starts)
        pads=np.maximum(starts+10-n,0)
        a=aligned[key]
        for k in ["session_id","placement_id","source_trajectory_id"]:
            assert groups.setdefault((k,a[k]),e["split"])==e["split"]
        events={r["event"]:r["mono_ns"] for r in read_json(p/"quality.json")["events"]}
        # C/O are operator marks AFTER grasp/release. Use an explicit +/- 0.5 s neighborhood.
        close,opened=events["close"],events["open"]
        phase=np.select([ticks<close-500_000_000,ticks<=close+500_000_000,
                         ticks<opened-500_000_000,ticks<=opened+500_000_000],
                        ["approach","close_marker","carry","open_marker"],default="retreat")
        for name in np.unique(phase):
            mask=phase==name
            surviving=int(mask[starts].sum())
            phases.append(dict(episode=key,split=e["split"],phase=name,rows=int(mask.sum()),
                               usable_starts=surviving,excluded_starts=int(mask.sum())-surviving,
                               invalid_rows=int((mask & ~valid).sum())))
        reasons=Counter(reason for r in trace for reason in r["excluded_reasons"])
        record=dict(episode=key,split=e["split"],color=e["target_color"],
                    session=a["session_id"],placement=a["placement_id"],trajectory=a["source_trajectory_id"],
                    rows=n,invalid_rows=int((~valid).sum()),starts=len(starts),padded_windows=int((pads>0).sum()),
                    padded_slots=int(pads.sum()),start_ranges=ranges(starts),reasons=json.dumps(reasons,sort_keys=True))
        records.append(record)
        totals.setdefault(e["split"],Counter()).update({k:record[k] for k in
                       ["rows","invalid_rows","starts","padded_windows","padded_slots"]})
    args.out.mkdir(parents=True,exist_ok=True)
    write_csv(args.out/"local_episodes.csv",records)
    write_csv(args.out/"local_phases.csv",phases)
    print(json.dumps(totals))


if __name__=="__main__":
    main()
