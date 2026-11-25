"""Freeze reader-compatible V01 evaluation keys and a prospective paired layout order; no predictions."""
import argparse
import hashlib
from itertools import permutations
from pathlib import Path
import numpy as np
from derive import read_json,write_csv


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("local",type=Path)
    ap.add_argument("out",type=Path)
    args=ap.parse_args()
    keys=[]
    for e in read_json(args.local/"index.json"):
        if e["split"]!="validation":
            continue
        p=args.local/e["directory"]
        starts=np.load(p/e["valid_action_starts"])
        times=np.load(p/"policy_timestamps_ns.npy")
        events={r["event"]:r["mono_ns"] for r in read_json(p/"quality.json")["events"]}
        # Include legacy 64/episode for paired comparison. Keep all other valid rows available
        # for event strata and give each episode equal weight when aggregating.
        legacy=set(starts[np.linspace(0,len(starts)-1,64,dtype=int)].tolist())
        for start in starts:
            ns=times[start]
            phase=("close_marker" if abs(ns-events["close"])<=500_000_000 else
                   "open_marker" if abs(ns-events["open"])<=500_000_000 else
                   "approach" if ns<events["close"] else "carry" if ns<events["open"] else "retreat")
            seed=int.from_bytes(hashlib.sha256(f"42:{e['directory']}:{start}".encode()).digest()[:8],"little")
            keys.append(dict(episode=e["directory"],color=e["target_color"],start=start,phase=phase,
                             real_slots=min(10,len(times)-start),legacy64=int(start in legacy),noise_seed=seed))
    assert sum(r["legacy64"] for r in keys)==640
    write_csv(args.out/"v01_evaluation_keys.csv",keys)
    trials=[]
    rng=np.random.default_rng(42)
    for layout in range(1,7):
        # Six layouts balance the six possible orders for the three arms.
        order=list(permutations(["reference9999","local_control","local_plus_A"]))[layout-1]
        for model in order:
            colors=rng.permutation(["blue","red"])
            for color in colors:
                trials.append(dict(trial=len(trials)+1,new_layout=layout,model=model,requested_color=color,
                                   order_within_layout=len(trials)%6+1,status="planned"))
    write_csv(args.out/"field_schedule.csv",trials)


if __name__=="__main__":
    main()
