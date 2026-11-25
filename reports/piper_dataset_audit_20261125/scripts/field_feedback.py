"""Read measured CAN payloads and compare to every exported row on the field machine."""
import csv
import json
import math
import struct
import sys
from pathlib import Path
import numpy as np

base=Path(sys.argv[1])
frozen=base/"blue_red_direct_20261124_50_v1"
index={m["directory"]:m for m in json.loads((frozen/"index.json").read_text())}
result=[]
for path in sorted(base.glob("pickplace_20261124_*/*/run.json")):
    meta=json.loads(path.read_text())
    uid=next((str(meta[k]) for k in ("run_id","id","uuid") if meta.get(k) in index),None)
    if uid is None:
        continue
    f=frozen/uid
    state=np.load(f/"state.npy",mmap_mode="r")
    actions=np.load(f/"actions.npy",mmap_mode="r")
    measured={"arm":{},"grip":{}}
    with (path.parent/"feedback.csv").open() as records:
        for row in csv.DictReader(records):
            kind=row["kind"]
            raw=bytes.fromhex(row["raw_hex"])
            if kind=="arm":
                value=[math.radians(v*.001) for v in struct.unpack(">6i",raw)]
            elif kind=="grip":
                value=[int.from_bytes(raw[:4],"big",signed=True)*1e-6]
            else:
                continue
            measured[kind][int(row["id"])]=value
    mismatches=[0,0]
    errors=[0.,0.]
    for i,line in enumerate((f/"row_sources.jsonl").open()):
        row=json.loads(line)
        for j,(aq,ag,x) in enumerate((("q","grip",state),("future_joint_id","future_grip_id",actions))):
            v=np.asarray(measured["arm"][row[aq]]+measured["grip"][row[ag]],dtype=x.dtype)
            diff=float(np.max(np.abs(v-x[i])))
            errors[j]=max(errors[j],diff)
            mismatches[j]+=int(diff!=0)
    result.append(dict(id=uid,raw=str(path.parent.relative_to(base)),frames=len(state),mismatch_rows=mismatches,
                  max_abs_diff=errors,command_lines=len((path.parent/"commands.jsonl").read_text().splitlines()),
                  tx_records=sum(1 for _ in csv.DictReader((path.parent/"tx.csv").open()))))
print(json.dumps(result))
