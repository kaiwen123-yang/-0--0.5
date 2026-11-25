"""Check frozen V01 against local train and the new source-native candidate clips."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from derive import read_json


def moving_keys(states,actions,starts):
    for start in starts:
        # Local reader permits repeated tail targets. Check only ten genuine labels here.
        if start+10>len(actions):
            continue
        chunk=actions[start:start+10,:7]
        if (chunk!=states[start,:7]).any():
            yield np.asarray(np.vstack((states[start,:7],chunk)),dtype="<f4").tobytes()


def main():
    ap=argparse.ArgumentParser()
    for name in ("local","work"):
        ap.add_argument(name,type=Path)
    args=ap.parse_args()
    entries=read_json(args.local/"index.json")
    keys=set()
    counts={}
    for split in ["validation","train"]:
        hits=seen=0
        for e in entries:
            if e["split"]!=split:
                continue
            p=args.local/e["directory"]
            stream=moving_keys(np.load(p/"state.npy"),np.load(p/"actions.npy"),np.load(p/e["valid_action_starts"]))
            for key in stream:
                seen+=1
                if split=="validation":
                    keys.add(key)
                else:
                    hits+=int(key in keys)
        counts[split]={"moving_full_windows":seen,"overlap_with_V01":None if split=="validation" else hits}
    for r in csv.DictReader((args.work/"reports/source_candidates.csv").open()):
        count=counts.setdefault(r["source"],{"moving_full_windows":0,"overlap_with_V01":0})
        with np.load(args.work/"grid"/r["directory"]/"grid.npz") as d:
            for key in moving_keys(d["state"],d["future_state"],d["starts"]):
                count["moving_full_windows"]+=1
                count["overlap_with_V01"]+=int(key in keys)
    assert all(v["overlap_with_V01"] in (None,0) for v in counts.values()),counts
    (args.work/"reports/split_check.json").write_text(json.dumps(counts,indent=2))
    print(counts)


if __name__=="__main__":
    main()
