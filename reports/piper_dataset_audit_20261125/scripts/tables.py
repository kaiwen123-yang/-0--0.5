"""Publish compact evidence tables; raw arrays, frames and source code stay on the data host."""
import csv
import gzip
import json
import sys
from datetime import datetime,timezone
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from scipy.spatial import cKDTree
from acquire import SOURCES,write_json
from arrays import distribution,runs

root=Path(sys.argv[1])
out=root/"tables"
out.mkdir(exist_ok=True)
issues=[]
episodes=[]
videos=[]
lags=[]
fields={}
tasks=[]
stats={}
signatures=defaultdict(list)
duplicates=[]


def table(name,rows):
    if not rows:
        (out/name).write_text("")
        return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    writer=gzip.open if name.endswith(".gz") else open
    with writer(out/name,"wt",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=keys,quoting=csv.QUOTE_ALL if name=="tasks.csv" else csv.QUOTE_MINIMAL)
        w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False,separators=(",",":")) if isinstance(v,(dict,list,tuple)) else v for k,v in row.items()})


def flag(k,ep,code,path,location,detail):
    issues.append(dict(source=k,episode=ep,code=code,path=path,location=location,detail=detail))


receipts={}
for log in ("downloads","relay","fill",*("xet-"+s for s in SOURCES)):
    f=root/"checks"/(log+".jsonl")
    if f.exists():
        for row in map(json.loads,f.read_text().splitlines()):
            if row[-1]=="verified":
                receipts.setdefault((row[0],row[1]),row)
files=[]
for key in SOURCES:
    lock=json.loads((root/"sources"/(key+".json")).read_text())
    for f in lock["files"]:
        name=f["rfilename"]
        row=receipts.get((key,name))
        files.append(dict(source=key,path=name,local=str(root/"raw"/key/name),size=f["size"],
                      git_blob=f["blobId"],remote_sha256=(f.get("lfs") or {}).get("sha256"),
                      sha256=row[3] if row else None,verified_utc=row[6] if row else None,status="verified" if row else "pending"))
    info=next((root/"raw"/key).rglob("meta/info.json"))
    base=info.parent.parent
    meta=json.loads(info.read_text())
    taskmap={v["task_index"]:v["task"] for v in map(json.loads,(info.parent/"tasks.jsonl").read_text().splitlines())}
    cnt=Counter()
    rel=defaultdict(dict)
    active=[]
    full_equal=Counter()
    terminal=[]
    clock=defaultdict(list)
    first=[]
    grd=Counter()
    neg=Counter()
    extrem=defaultdict(list)
    nrows=0
    prev=-1
    task_samples=defaultdict(list)
    group_stats=defaultdict(list)
    cnotes={}
    if key=="C":
        cnotes={x["episode_index"]:x for x in json.loads((base/"conversion_notes.json").read_text())["episodes"]}
    detail_files=sorted((root/"checks"/"arrays"/key).glob("*.json"))
    for fn in detail_files:
        d=json.loads(fn.read_text())
        ep=d["episode"]
        path=d["path"]
        ep_path=str((base/path).relative_to(root/"raw"/key))
        n=d["n"]
        nrows+=n
        tid=d["task_indices"][0]
        task=taskmap[tid]
        cnt[tid]+=1
        task_samples[tid].append(ep)
        if d["declared"]["tasks"]!=[task] or d["declared"]["length"]!=n or len(d["task_indices"])!=1:
            flag(key,ep,"meta_mismatch",ep_path,"episode",d["declared"])
        if cnotes and (cnotes[ep]["num_frames"]!=n or cnotes[ep]["task"]!=task or cnotes[ep]["source_episode"]!="episode"+str(ep)):
            flag(key,ep,"conversion_notes_mismatch",ep_path,"episode",cnotes[ep])
        for name,v in d["fields"].items():
            if any(v.get(x,0) for x in ("null","nan","inf")):
                flag(key,ep,"null_nonfinite",ep_path,name,v)
        schema={k:v["type"] for k,v in d["fields"].items()}
        fields.setdefault(key,dict(metadata=meta["features"],actual_schemas=[]))
        if schema not in fields[key]["actual_schemas"]:
            fields[key]["actual_schemas"].append(schema)
        for name in ("frame_errors","episode_errors","index_gaps"):
            if d[name]:
                flag(key,ep,name,ep_path,d[name],"indices")
        if prev+1!=d["index_first"]:
            flag(key,ep,"global_index_boundary",ep_path,0,[prev,d["index_first"]])
        prev=d["index_last"]
        for name,t in d["times"].items():
            for code in ("backward_rows","repeated_rows","over_1p5_median_rows"):
                if t.get(code):
                    flag(key,ep,name+"_"+code,ep_path,t[code],t["interval"])
        if n<30:
            flag(key,ep,"shorter_than_one_nominal_second",ep_path,[0,n-1],n)
        tab=pq.read_table(base/path,use_threads=False)
        ss=np.array(tab["state" if key=="C" else "observation.state"].to_pylist())
        aa=np.array(tab["actions" if key=="C" else "action"].to_pylist())
        current=np.all(aa==ss,axis=1)
        nxt=np.all(aa[:-1]==ss[1:],axis=1)
        full_equal.update({"same":int(current.sum()),"next":int(nxt.sum()),"next_pairs":len(nxt)})
        full_equal["episodes_nonempty_all_next"]+=int(len(nxt)>0 and np.all(nxt))
        terminal.append(d["last_equals_state"])
        first.append([ss[0].tolist(),aa[0].tolist()])
        for name,x in (("state",ss),("action",aa)):
            extrem[name].append(x)
            change=np.abs(np.diff(x,axis=0))
            thresholds=np.tile([.2]*6+[.025],x.shape[1]//7)
            loc=np.argwhere(change>thresholds)
            if len(loc):
                flag(key,ep,name+"_step_screen",ep_path,[[int(i+1),int(j)] for i,j in loc],
                     "native absolute step >0.2 (joint) or >0.025 (gripper); inspect conventions")
            neg[name]+=int((x[:,6]<0).sum())
        hold=runs(np.all(np.diff(ss,axis=0)==0,axis=1))
        if hold[0]>=90:
            flag(key,ep,"all_state_exact_hold_ge_90_intervals",ep_path,[hold[1],hold[1]+hold[0]],hold[0])
        ranges=np.ptp(ss,axis=0)
        active.append(ranges.tolist())
        for name in ("timestamp","real_observation_timestamp_s","real_action_timestamp_s",
                     "real_observation_wall_time_ns","real_action_wall_time_ns"):
            if name in tab.column_names:
                delta=np.diff(np.asarray(tab[name]))
                clock[name].extend(delta.tolist())
        gerr=d["grid_max_diff_s"]
        grd["within_1e-4s"]+=int(gerr<1e-4)
        for lag,phases in d["relation"].items():
            for phase,data in phases.items():
                k=(tid,lag,phase)
                if k not in group_stats:
                    group_stats[k]=np.asarray(data,dtype=float)
                else:
                    group_stats[k]+=data
        signatures[ss.shape[1]].append((key,ep,d["numeric_sha256"],d["trajectory_signature"]))
        episodes.append(dict(source=key,episode=ep,path=ep_path,n=n,task=task,task_index=tid,
                  index_first=d["index_first"],index_last=d["index_last"],grid_max_diff_s=gerr,
                  state_range=ranges.tolist(),state_q=d["profile"]["state"]["q"],
                  action_q=d["profile"]["action"]["q"],state_delta_q=d["profile"]["state"]["delta_q"],
                  action_delta_q=d["profile"]["action"]["delta_q"],
                  unchanged_runs=d["profile"]["state"]["constant_runs"],max_step_rows=d["profile"]["state"]["max_delta_row"],
                  same_exact_rows=int(current.sum()),next_exact_rows=int(nxt.sum()),next_pairs=len(nxt),
                  times={f:{kk:vv for kk,vv in t.items() if not kk.endswith("rows")} for f,t in d["times"].items()},
                  repeat_adjacent_state_action=d["repeat_transitions"],numeric_sha256=d["numeric_sha256"]))
    for (tid,lag,phase),data in sorted(group_stats.items()):
        for j,(num,eq,err) in enumerate(data.T):
            lags.append(dict(source=key,task=tid,lag=int(lag),phase=phase,dim=j,n=int(num),
                             exact=int(eq),mae=err/num if num else None))
    sides=np.asarray(active)
    stats[key]=dict(episodes=len(detail_files),n=nrows,declared=meta["total_frames"],equal=full_equal,
        terminal_equal_per_dim=np.sum(terminal,axis=0).tolist(),episode_range_median=np.median(sides,axis=0).tolist(),
        episode_range_max=sides.max(axis=0).tolist(),nonconstant_eps_per_dim=(sides>0).sum(axis=0).tolist(),
        time_delta_quantiles={k:distribution(np.array(v)) for k,v in clock.items()},
        nominal_grid=grd,negative_grip_rows=neg,dimensions={k:distribution(np.concatenate(v)) for k,v in extrem.items()},
        first_row_q=distribution(np.array(first)),task_counts=dict(cnt),fps=meta["fps"])
    if sides.shape[1]==14:
        stats[key]["right_nonconstant_eps"]=int((sides[:,7:].max(axis=1)>0).sum())
    for tid in cnt:
        tasks.append(dict(source=key,task_index=tid,task=taskmap[tid],n=cnt[tid],episodes=task_samples[tid]))

for dim,group in signatures.items():
    scale=np.tile([.01]*6+[.001],dim//7)
    arr=np.stack([np.array(g[3])/scale for g in group]).reshape(len(group),-1)
    for i,j in sorted(cKDTree(arr).query_pairs(1,p=np.inf)):
        a,b=group[i],group[j]
        duplicates.append(dict(kind="exact_numeric" if a[2]==b[2] else "similar_24_observed_rows",
                a=f"{a[0]}/{a[1]}",b=f"{b[0]}/{b[1]}",max_scaled_distance=float(np.max(np.abs(arr[i]-arr[j])))))
for f in json.loads((root/"checks"/"E_files.json").read_text()):
    files.append(dict(source="E",path=f["path"],local=str(root/"raw"/"E"/f["path"]),size=f["size"],
                 remote_sha256=f["remote_sha256"],sha256=f["sha256"],verified_utc=f["verified"],status="verified"))
filegroups=defaultdict(list)
for row in files:
    if row["sha256"]:
        filegroups[row["sha256"]].append(row["source"]+"/"+row["path"])
for digest,paths in filegroups.items():
    if len(paths)>1:
        duplicates.append(dict(kind="exact_file",sha256=digest,paths=paths))
for f in files:
    local=Path(f["local"])
    if local.exists():
        f["last_payload_write_utc"]=datetime.fromtimestamp(local.stat().st_mtime,timezone.utc).isoformat()
byep={(d["source"],d["episode"]):d for d in episodes}
for fn in sorted((root/"checks"/"video").rglob("*.json")):
    v=json.loads(fn.read_text())
    path=Path(v["path"])
    k=path.parts[0]
    ep=int(path.stem.split("_")[-1])
    expected=byep[k,ep]["n"]
    for st in v["streams"] or [{}]:
        errors=v["errors"]+st.get("errors",[])
        intervals=st.get("pts_delta_hist",[])
        if errors or st.get("n")!=expected or any(x<=0 for x,count in intervals) or st.get("pts_missing"):
            flag(k,ep,"video_decode_count_or_pts",str(path),st.get("pts_anomalies"),dict(errors=errors,n=st.get("n"),expected=expected))
        videos.append(dict(source=k,episode=ep,camera=path.parent.name,path=str(path),array_rows=expected,
                           **{k:v for k,v in st.items() if k not in ("errors","pts_anomalies","pts_delta_hist")},
                           pts_interval_types=len(intervals),min_step=intervals[0][0] if intervals else None,
                           max_step=intervals[-1][0] if intervals else None,
                           n_nonmodal_intervals=len(st.get("pts_anomalies",[])),errors=errors))
for f in sorted((root/"checks"/"hdf").glob("*.json")):
    d=json.loads(f.read_text())
    ep=f.stem
    fields.setdefault("E",{})[ep]={k:{n:v[n] for n in ("shape","dtype")} for k,v in d["fields"].items()}
    task=d["path"].split("/")[3]
    instruction=d.get("metadata",{}).get("language_instruction")
    profile={}
    for role in ("puppet","master"):
        cols=[]
        for side in ("left","right"):
            cols.extend([np.array(d["fields"][f"{role}/arm_{side}_position_align/data"]["q"]),
                         np.array(d["fields"][f"{role}/end_effector_{side}_position_align/data"]["q"]).reshape(-1,1)])
        profile[role+"_q"]=np.column_stack(cols).tolist()
    episodes.append(dict(source="E",episode=ep,path=d["path"],task=task,n=d["n"],instruction=instruction,
                         times=d["fields"]["camera_observations/timestamp"],**profile,numeric_sha256=d["source_numeric_sha256"]))
    tasks.append(dict(source="E",task=task,instruction=instruction,n=1,episodes=[ep]))
    for lag,group in d["master_vs_puppet"].items():
        for phase,data in group.items():
            for dim,(num,eq,err) in enumerate(zip(*data)):
                lags.append(dict(source="E",task=task,lag=lag,phase=phase,dim=dim,n=num,exact=eq,mae=err/num if num else None))
    for name,v in d["fields"].items():
        if "decoded" in v:
            videos.append(dict(source="E",episode=ep,camera=name,path=d["path"],array_rows=d["n"],
                               n=v["decoded"],codec=v["formats"],shape=v["shapes"],pts="no container",
                               identical_adjacent=v["identical_adjacent"],errors=v["errors"]))
            if v["errors"] or v["decoded"]!=d["n"]:
                flag("E",ep,"embedded_decode",d["path"],name,v["errors"])
        elif v.get("inf") or v.get("nan"):
            flag("E",ep,"nonfinite",d["path"],name,[v["nan"],v["inf"]])
for entry in json.loads((Path(__file__).parent.parent/"review_issues.json").read_text()):
    issues.append(entry)
counts=Counter((str(x["source"]),str(x["episode"])) for x in issues)
for e in episodes:
    e["issue_groups"]=counts[str(e["source"]),str(e["episode"])]
table("files.csv.gz",files)
table("episodes.csv.gz",episodes)
table("videos.csv.gz",videos)
table("lags.csv.gz",lags)
table("issues.csv.gz",issues)
table("duplicates.csv.gz",duplicates)
table("tasks.csv",tasks)
write_json(out/"summary.json",stats)
write_json(out/"fields.json",fields)
