"""Compare decoded presentation clocks with array clocks, and paired wrist motion."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json
import av
import numpy as np
import pyarrow.parquet as pq
from acquire import write_json,SOURCES
from arrays import distribution,runs


def inspect(job):
    root,key,ep,base,paths,out=job
    array=next(base.glob(f"data/*/episode_{ep:06}.parquet"))
    tab=pq.read_table(array,use_threads=False)
    ts=tab["timestamp"].to_numpy().astype(float)
    ref=ts-ts[0]
    clocks=[]
    cams={}
    for path in paths:
        with av.open(str(path)) as c:
            st=c.streams.video[0]
            st.codec_context.thread_count=1
            pts=[]
            change=[]
            last=None
            blocks=[]
            for fr in c.decode(st):
                pts.append(float(fr.pts*fr.time_base) if fr.pts is not None else np.nan)
                # Small spatial average is a motion proxy, not a physical camera calibration.
                current=fr.reformat(width=32,height=24,format="gray").to_ndarray().astype(np.int16)
                if last is not None:
                    change.append(float(np.abs(current-last).mean()))
                last=current
            if not pts:
                cams[path.parent.name]=dict(n=0)
                continue
            clock=np.asarray(pts)
            clocks.append(clock)
            count=min(len(clock),len(ts))
            rel=clock[:count]-clock[0]
            err=np.abs(rel-ref[:count])
            row=dict(n=len(clock),peak_vs_array_s=float(err.max()),peak_row=int(err.argmax()),
                end_vs_array_s=float(rel[-1]-ref[count-1]),motion_mean=float(np.mean(change)) if change else None,
                motion_p=distribution(change),unchanged_32x24_intervals=int(np.sum(np.asarray(change)==0)),
                still_run=runs(np.asarray(change)==0))
            if "real_observation_timestamp_s" in tab.column_names:
                ob=tab["real_observation_timestamp_s"].to_numpy()
                row["peak_vs_real_obs_s"]=float(np.max(np.abs(rel-(ob[:count]-ob[0]))))
            cams[path.parent.name]=row
    m=min(map(len,clocks)) if clocks else 0
    z=np.stack([c[:m] for c in clocks]) if m else None
    result=dict(source=key,episode=ep,cameras=cams,n_common=m,
                max_cross_camera_pts_spread_s=float(np.ptp(z,axis=0).max()) if m else None)
    if "real_observation_timestamp_s" in tab.column_names:
        ob=tab["real_observation_timestamp_s"].to_numpy()
        result["max_timestamp_minus_real_obs_s"]=float(np.max(np.abs(ts-ob)))
    write_json(out,result)


def safe(job):
    try:
        inspect(job)
    except Exception as e:
        write_json(job[-1],dict(source=job[1],episode=job[2],error=str(e)))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    ap.add_argument("--workers",type=int,default=8)
    args=ap.parse_args()
    jobs=[]
    for k in SOURCES:
        info=next((args.root/"raw"/k).rglob("meta/info.json"))
        base=info.parent.parent
        meta=json.loads(info.read_text())
        cameras=[k for k,v in meta["features"].items() if v["dtype"]=="video"]
        target=args.root/"checks"/"synchrony"/k
        target.mkdir(parents=True,exist_ok=True)
        for ep in range(meta["total_episodes"]):
            paths=[base/meta["video_path"].format(episode_chunk=ep//meta["chunks_size"],video_key=v,episode_index=ep) for v in cameras]
            out=target/f"{ep:06}.json"
            if not out.exists() and all(p.exists() for p in paths):
                jobs.append((args.root,k,ep,base,paths,out))
    with ProcessPoolExecutor(args.workers) as pool:
        list(pool.map(safe,jobs,chunksize=2))
    print("new",len(jobs))


if __name__=="__main__":
    main()
