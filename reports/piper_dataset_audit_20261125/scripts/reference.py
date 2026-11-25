"""Reconcile the existing frozen local demonstrations, using read-only numpy access."""
import json
import sys
from collections import Counter
from pathlib import Path
import numpy as np
from acquire import write_json

source,out=map(Path,sys.argv[1:3])
rows=[]
for meta in json.loads((source/"index.json").read_text()):
    path=source/meta["directory"]
    quality=json.loads((path/"quality.json").read_text())
    trace=[json.loads(s) for s in (path/"row_sources.jsonl").open()]
    state=np.load(path/"state.npy",mmap_mode="r")
    action=np.load(path/"actions.npy",mmap_mode="r")
    times=np.load(path/"policy_timestamps_ns.npy",mmap_mode="r")
    agreement=np.all(action[:-1]==state[1:],axis=1)
    rows.append(dict(id=meta["directory"],n=len(state),shape=list(action.shape),
        sources=dict(Counter(str((v["arm_action_source"],v["gripper_action_source"],v["action_at_ns"]-v["t"])) for v in trace)),
        dt_ns=np.unique(np.diff(times)).tolist(),next_exact=int(agreement.sum()),next_pairs=len(agreement),
        provenance_next_match=sum(a["future_joint_id"]==b["q"] and a["future_grip_id"]==b["grip"] for a,b in zip(trace,trace[1:])),
        arm_submissions=quality["arm_submissions"],grip_submissions=quality["gripper_submissions"],
        tx=quality["interface_delta"]["tx_packets"],grip_basis=meta["gripper_basis"],
        mode=meta["collection_mode"],range_m=[float(state[:,6].min()),float(state[:,6].max())],
        split=meta["split"],color=meta["target_color"]))
write_json(out,rows)
