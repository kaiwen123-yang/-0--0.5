"""Per-episode numeric checks. All diagnostics retain the native values and indices."""
import argparse
import concurrent.futures as cf
import hashlib
import json
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from acquire import SOURCES, write_json

LAGS = list(range(-5, 9))


def lists(a):
    return np.asarray(a).tolist()


def runs(mask):
    edges=np.flatnonzero(np.diff(np.r_[False,mask,False]))
    if not len(edges):
        return [0,None]
    pairs=edges.reshape(-1,2)
    i=np.argmax(pairs[:,1]-pairs[:,0])
    return [int(pairs[i,1]-pairs[i,0]),int(pairs[i,0])]


def distribution(x):
    if not len(x):
        return None
    return lists(np.nanpercentile(x,[0,1,50,99,100],axis=0))


def fingerprint(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def relation(state,action):
    """Compare action(t) to state(t+lag). Phase is per-dimension next feedback change."""
    out={}
    delta=np.abs(np.diff(state,axis=0))
    # Native threshold only for phase diagnostics: exact and near-zero counted separately.
    for lag in LAGS:
        lo=max(0,-lag)
        hi=min(len(state)-1,len(state)-lag)
        if hi<=lo:
            continue
        err=np.abs(action[lo:hi].astype(float)-state[lo+lag:hi+lag])
        motion=delta[lo:hi]>0
        phases={}
        for key,mask in (("moving",motion),("still",~motion)):
            mask=mask & np.isfinite(err)
            phases[key]=[lists(np.sum(mask,axis=0)),lists(np.sum(mask & (err==0),axis=0)),
                         lists(np.sum(np.where(mask,err,0),axis=0))]
        out[str(lag)]=phases
    return out


def inspect(job):
    key,base,path,fps,meta=job
    ep=int(path.stem.split("_")[-1])
    table=pq.read_table(path,use_threads=False)
    n=len(table)
    fields={}
    cols={}
    for name in table.column_names:
        col=table[name].combine_chunks()
        x=np.asarray(col.to_pylist())
        fields[name]=dict(type=str(col.type),shape=list(x.shape),null=col.null_count)
        if x.dtype.kind in "ifu":
            fields[name].update(nan=int(np.isnan(x).sum()),inf=int(np.isinf(x).sum()))
            if not np.all(np.isfinite(x)):
                fields[name]["nonfinite_row_dim"]=lists(np.argwhere(~np.isfinite(x)))
        cols[name]=x
    state=cols["state" if key=="C" else "observation.state"]
    action=cols["actions" if key=="C" else "action"]
    f=cols["frame_index"]
    times={}
    for name,x in cols.items():
        if "time" not in name and "fps" not in name and "delta_s" not in name:
            continue
        v=dict(bounds=[x.min().item(),x.max().item()] if len(x) else [])
        if "fps" not in name and "delta_s" not in name:
            d=np.diff(x)
            med=np.median(d) if len(d) else 0
            v.update(interval=distribution(d),repeated_rows=lists(np.flatnonzero(d==0)+1),
                     backward_rows=lists(np.flatnonzero(d<0)+1),
                     over_1p5_median_rows=lists(np.flatnonzero(d>1.5*med)+1) if med>0 else [])
        times[name]=v
    profile={}
    for name,x in (("state",state),("action",action)):
        change=np.abs(np.diff(x,axis=0))
        profile[name]=dict(q=distribution(x),delta_q=distribution(change),
            max_delta_row=lists(np.argmax(change,axis=0)+1) if len(change) else [],
            constant_runs=[runs(v==0) for v in change.T],negative=lists((x<0).sum(axis=0)),
            start=lists(x[0]),end=lists(x[-1]))
    detail=dict(source=key,episode=ep,path=str(path.relative_to(base)),n=n,declared=meta,
        fields=fields,frame_errors=lists(np.flatnonzero(f!=np.arange(n))),
        episode_errors=lists(np.flatnonzero(cols["episode_index"]!=ep)),
        index_first=int(cols["index"][0]),index_last=int(cols["index"][-1]),
        index_gaps=lists(np.flatnonzero(np.diff(cols["index"])!=1)+1),
        task_indices=lists(np.unique(cols["task_index"])),times=times,
        grid_max_diff_s=float(np.max(np.abs(cols["timestamp"]-f/fps))),
        profile=profile,relation=relation(state,action),last_equals_state=lists(action[-1]==state[-1]),
        numeric_sha256=fingerprint(np.column_stack((state,action))),
        repeat_transitions=int(np.sum(np.all(np.diff(np.column_stack((state,action)),axis=0)==0,axis=1))),
        # uniformly selected observed values for a near-duplicate screening distance only.
        trajectory_signature=lists(np.round(state[np.linspace(0,n-1,24).astype(int)],5)))
    if "real_action_timestamp_s" in cols:
        for a,b in (("real_action_timestamp_s","real_observation_timestamp_s"),
                    ("real_action_wall_time_ns","real_observation_wall_time_ns"),
                    ("action.ee_pose","observation.ee_pose")):
            err=cols[a][:-1]-cols[b][1:]
            detail[a+"_vs_next"]=[int(np.count_nonzero(err)),float(np.max(np.abs(err))) if err.size else None]
        detail["transition_formula_error_s"]=float(np.max(np.abs(cols["real_action_timestamp_s"]-
                  cols["real_observation_timestamp_s"]-cols["real_transition_delta_s"])))
    return detail


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    ap.add_argument("--workers",type=int,default=4)
    args=ap.parse_args()
    jobs=[]
    for key in SOURCES:
        info=next((args.root/"raw"/key).rglob("meta/info.json"))
        base=info.parent.parent
        fps=json.loads(info.read_text())["fps"]
        episodes={m["episode_index"]:m for m in map(json.loads,(info.parent/"episodes.jsonl").read_text().splitlines())}
        for path in sorted(base.glob("data/*/*.parquet")):
            ep=int(path.stem.split("_")[-1])
            out=args.root/"checks"/"arrays"/key/(path.stem+".json")
            if not out.exists():
                jobs.append(((key,base,path,fps,episodes.get(ep)),out))
    with cf.ProcessPoolExecutor(args.workers) as pool:
        for (job,out),res in zip(jobs,pool.map(inspect,[j for j,out in jobs],chunksize=8)):
            out.parent.mkdir(parents=True,exist_ok=True)
            write_json(out,res)
    print("new episode reports",len(jobs))


if __name__=="__main__":
    main()
