"""Reconcile published tables with locked bytes and all decoded streams; fail on missing coverage."""
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from acquire import SOURCES,REVISIONS,digests,write_json
from tables_io import csv_gz
from arrays import distribution

root=Path(sys.argv[1])
out=root/"tables"
read=lambda n:list(csv.DictReader(gzip.open(out/n,"rt")))
files=read("files.csv.gz")
episodes=read("episodes.csv.gz")
videos=read("videos.csv.gz")
syn=[]
summ={}
for k in SOURCES:
    samples=sorted((root/"checks"/"synchrony"/k).glob("*.json"))
    motion=Counter()
    cross=[]
    peak=[]
    obs=[]
    mismatches=[]
    wall={}
    for file in samples:
        d=json.loads(file.read_text())
        if "error" in d:
            raise ValueError((k,file,d))
        cams=d["cameras"]
        if len(cams)>2:
            l=cams["observation.images.left_wrist"]["motion_mean"]
            r=cams["observation.images.right_wrist"]["motion_mean"]
            cat="no transition" if l is None or r is None else "right greater" if r>l else "left greater" if l>r else "equal"
            motion[cat]+=1
            if cat!="right greater":
                mismatches.append([d["episode"],cat])
        cross.append(d["max_cross_camera_pts_spread_s"])
        if "max_timestamp_minus_real_obs_s" in d:
            obs.append(d["max_timestamp_minus_real_obs_s"])
        for name,v in cams.items():
            syn.append(dict(source=k,episode=d["episode"],camera=name,cross_camera_max_s=cross[-1],
                            **{kk:json.dumps(vv) if isinstance(vv,list) else vv for kk,vv in v.items()}))
            peak.append(v["peak_vs_array_s"])
    if len(samples)!=sum(row["source"]==k for row in episodes):
        raise ValueError("sync coverage "+k)
    summ[k]=dict(episodes=len(samples),max_cross_camera_pts_spread_s=max(cross),
                 max_relative_pts_vs_array_s=max(peak),relative_pts_error_per_video_q=distribution(peak),
                 max_timestamp_minus_real_observation_s=max(obs) if obs else None,
                 wrist_motion_order=motion,exceptions_to_right_greater=mismatches)
csv_gz(out/"synchrony.csv.gz",syn)

source=[]
for key in [*SOURCES,"E"]:
    lock=json.loads((root/"sources"/(key+".json")).read_text())
    if key in REVISIONS and lock["sha"]!=REVISIONS[key]:
        raise ValueError("source lock "+key)
    fs=[f for f in files if f["source"]==key]
    if len(fs)!=len(lock["files"]) or any(f["status"]!="verified" for f in fs):
        raise ValueError("file coverage "+key)
    for f in fs:
        path=Path(f["local"])
        if not path.is_file() or path.stat().st_size!=int(f["size"]) or digests(path)[0]!=f["sha256"]:
            raise ValueError("final SHA-256 "+str(path))
    eps=[e for e in episodes if e["source"]==key]
    vs=[v for v in videos if v["source"]==key]
    if key in SOURCES:
        meta=json.loads(next((root/"raw"/key).rglob("meta/info.json")).read_text())
        required={(e["episode"],name) for e in eps for name,s in meta["features"].items() if s["dtype"]=="video"}
        # Use the exact directory component; nested feature names are preserved.
        actual={(v["episode"],v["camera"]) for v in vs}
        if actual!=required or len(vs)!=len(required) or len(eps)!=meta["total_episodes"]:
            raise ValueError("episode/camera coverage "+key)
    else:
        if len(eps)!=len(lock["selected"]) or len(vs)!=6*len(eps):
            raise ValueError("embedded coverage")
    errors=[v["path"] for v in vs if v["errors"]!="[]" or v["n"]!=v["array_rows"]]
    source.append(dict(source=key,repo=lock["repo"],sha=lock["sha"],locked_utc=lock["locked"],file_count=len(fs),
        bytes=sum(int(f["size"]) for f in fs),episodes=len(eps),rows=sum(int(e["n"]) for e in eps),
        streams=len(vs),decoded_images=sum(int(v["n"]) for v in vs),frame_or_decode_errors=errors,
        first_verify_utc=min(f["verified_utc"] for f in fs),last_verify_utc=max(f["verified_utc"] for f in fs)))
write_json(out/"completion.json",dict(sources=source,sync=summ,
          sha256_verified=sum(e["file_count"] for e in source),
          bytes=sum(e["bytes"] for e in source),episodes=sum(e["episodes"] for e in source)))
