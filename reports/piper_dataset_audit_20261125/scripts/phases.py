"""Whole-arm motion phases with native thresholds, complementing exact per-channel phases."""
from pathlib import Path
import sys
import json
import numpy as np
import pyarrow.parquet as pq
from collections import defaultdict
from acquire import SOURCES
from arrays import LAGS
from tables_io import csv_gz

root=Path(sys.argv[1])
agg={}
phases=[]
for k in SOURCES:
    base=next((root/"raw"/k).rglob("meta/info.json")).parent.parent
    for path in sorted(base.glob("data/*/*.parquet")):
        t=pq.read_table(path,use_threads=False)
        ep=int(path.stem.split("_")[-1])
        task=int(t["task_index"][0].as_py())
        state=np.array(t["state" if k=="C" else "observation.state"].to_pylist())
        act=np.array(t["actions" if k=="C" else "action"].to_pylist())
        for side in range(state.shape[1]//7):
            st=state[:,7*side:7*side+7]
            ac=act[:,7*side:7*side+7]
            diff=np.abs(np.diff(st,axis=0))
            moving=np.any(diff[:,:6]>0.001,axis=1) | (diff[:,6]>0.0005)
            cuts=np.flatnonzero(np.diff(moving))+1
            for a,b in zip(np.r_[0,cuts],np.r_[cuts,len(moving)]):
                if a<b:
                    phases.append(dict(source=k,episode=ep,side=side,first=int(a),end_exclusive=int(b),moving=int(moving[a])))
            for lag in LAGS:
                lo=max(0,-lag)
                hi=min(len(st)-1,len(st)-lag)
                if hi<=lo:
                    continue
                err=np.abs(ac[lo:hi].astype(float)-st[lo+lag:hi+lag])
                for flag in (False,True):
                    v=err[moving[lo:hi]==flag]
                    ix=(k,task,side,lag,flag)
                    accum=agg.setdefault(ix,np.zeros((3,7)))
                    accum[0]+=len(v)
                    accum[1]+=(v==0).sum(axis=0)
                    accum[2]+=v.sum(axis=0)
out=[]
for (k,task,side,lag,flag),a in agg.items():
    for j,(n,eq,err) in enumerate(a.T):
        out.append(dict(source=k,task=task,side=side,dim=j,lag=lag,moving=int(flag),n=int(n),exact=int(eq),mae=err/n if n else None))
csv_gz(root/"tables"/"arm_phases.csv.gz",phases)
csv_gz(root/"tables"/"arm_phase_lags.csv.gz",out)
