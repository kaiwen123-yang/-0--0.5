"""Decode every presentation frame once and record frame-level PTS and corruption."""
import argparse
import concurrent.futures as cf
from collections import Counter
from pathlib import Path
import json
import time
import av

from acquire import SOURCES, write_json


def inspect(job):
    raw, path, record = job
    out=dict(path=str(path.relative_to(raw)), errors=[], streams=[])
    with av.open(str(path),options={"err_detect":"explode"}) as container:
        for stream in container.streams.video:
            stream.codec_context.thread_count=1
            pts=[]
            errors=[]
            try:
                for frame in container.decode(stream):
                    if frame.is_corrupt:
                        errors.append([len(pts),frame.pts,"corrupt"])
                    pts.append(frame.pts)
            except Exception as e:
                errors.append([len(pts),pts[-1] if pts else None,str(e)])
            diffs=Counter(b-a for a,b in zip(pts,pts[1:]) if a is not None and b is not None)
            tb=stream.time_base
            out["streams"].append(dict(codec=stream.codec_context.name,width=stream.width,
                height=stream.height,stream_index=stream.index,time_base=str(tb),
                fps=str(stream.average_rate),header_n=stream.frames,n=len(pts),pts_first=pts[:1],
                pts_last=pts[-1:],duration_s=float(stream.duration*tb) if stream.duration is not None else None,
                pts_delta_hist=sorted(diffs.items()),pts_missing=pts.count(None),
                pts_anomalies=[[i,b] for i,(a,b) in enumerate(zip(pts,pts[1:]),1)
                               if a is None or b is None or b<=a or (diffs and b-a!=diffs.most_common(1)[0][0])],
                errors=errors))
    if not out["streams"]:
        out["errors"].append("no video stream")
    write_json(record,out)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    ap.add_argument("--workers",type=int,default=8)
    ap.add_argument("--watch",action="store_true")
    args=ap.parse_args()
    raw=args.root/"raw"
    paths=[]
    for k in SOURCES:
        lock=json.loads((args.root/"sources"/(k+".json")).read_text())
        paths.extend(raw/k/f["rfilename"] for f in lock["files"] if f["rfilename"].endswith(".mp4"))
    remaining=set(paths)
    with cf.ThreadPoolExecutor(args.workers) as pool:
        while remaining:
            batch=[]
            for path in sorted(remaining):
                record=args.root/"checks"/"video"/path.relative_to(raw).with_suffix(".json")
                if record.exists():
                    remaining.remove(path)
                elif path.exists():
                    record.parent.mkdir(exist_ok=True,parents=True)
                    batch.append((raw,path,record))
            for job, result in zip(batch,pool.map(safe_inspect,batch)):
                remaining.remove(job[1])
            print("awaiting",len(remaining),"of",len(paths),flush=True)
            if remaining and args.watch:
                time.sleep(3)
            else:
                break


def safe_inspect(job):
    try:
        inspect(job)
    except Exception as e:
        raw,path,record=job
        write_json(record,dict(path=str(path.relative_to(raw)),streams=[],errors=[repr(e)]))


if __name__=="__main__":
    main()
