"""Inspect every HDF dataset and decode every embedded RGB JPEG and depth PNG."""
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import sys
import hashlib
import numpy as np
import cv2
import h5py
from arrays import distribution, relation, runs
from acquire import write_json

cv2.setNumThreads(1)


def inspect(path):
    root=Path(sys.argv[1])
    fields={}
    with h5py.File(path,"r") as f:
        def read(k,v):
            if not isinstance(v,h5py.Dataset):
                return
            out=dict(dtype=str(v.dtype),shape=list(v.shape))
            fields[k]=out
            if "camera_observations/" in k and "_images/" in k:
                shapes=Counter()
                encodings=Counter()
                errors=[]
                adjacent=0
                prev=None
                for i,img in enumerate(v):
                    buf=np.frombuffer(img,dtype=np.uint8)
                    digest=hashlib.sha256(buf).digest()
                    adjacent+=int(digest==prev)
                    prev=digest
                    encodings["JPEG" if bytes(buf[:2])==b"\xff\xd8" else "PNG" if bytes(buf[:4])==b"\x89PNG" else "other"]+=1
                    try:
                        a=cv2.imdecode(buf,cv2.IMREAD_UNCHANGED)
                        if a is None:
                            raise ValueError("could not decode")
                        shapes[str((a.shape,str(a.dtype)))]+=1
                    except Exception as exc:
                        errors.append([i,str(exc)])
                out.update(decoded=sum(shapes.values()),formats=encodings,shapes=shapes,
                           errors=errors,identical_adjacent=adjacent,pts=None)
            elif v.shape==():
                val=v[()]
                out["value"]=val.decode(errors="replace") if isinstance(val,bytes) else str(val)
            elif v.dtype.kind in "iufb":
                x=v[:]
                out.update(nan=int(np.isnan(x).sum()),inf=int(np.isinf(x).sum()),q=distribution(x.astype(float)))
                if "timestamp" in k:
                    delta=np.diff(x)
                    vals,counts=np.unique(delta,return_counts=True)
                    out.update(interval=distribution(delta),repeats=int(np.sum(delta==0)),
                               backward_rows=np.flatnonzero(delta<0).tolist(),
                               delta_counts=list(zip(vals.tolist(),counts.tolist())) if len(vals)<20 else None,
                               camera_stamp_equal=bool(np.array_equal(x,f["camera_observations/timestamp"][:])))
                if k.endswith("/data"):
                    d=np.abs(np.diff(x,axis=0)).reshape(len(x)-1,-1)
                    out["max_step_row"]=(np.argmax(d,axis=0)+1).tolist()
                    out["max_step"]=d.max(axis=0).tolist()
                    out["constant_runs"]=[runs(y==0) for y in d.T]
                if "intervene" in k:
                    out["true"]=int(x.sum())
        f.visititems(read)
        arms=[]
        for role in ("puppet","master"):
            arrays=[]
            for side in ("left","right"):
                arrays.extend([f[f"{role}/arm_{side}_position_align/data"][:],
                               f[f"{role}/end_effector_{side}_position_align/data"][:].reshape(-1,1)])
            arms.append(np.column_stack(arrays))
        detail=dict(path=str(path.relative_to(root/"raw")),fields=fields,n=len(arms[0]),
                    source_numeric_sha256=hashlib.sha256(np.column_stack(arms).tobytes()).hexdigest(),
                    master_vs_puppet=relation(*arms))
        if "metadata" in f:
            detail["metadata"]={key:str(val) for key,val in f["metadata"].attrs.items()
                                if key in ("data_type","language_instruction","trajectory_length","collection_time","robot_type")}
        out=root/"checks"/"hdf"/(path.parts[-3]+".json")
        out.parent.mkdir(exist_ok=True)
        write_json(out,detail)


if __name__=="__main__":
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(inspect,(Path(sys.argv[1])/"raw"/"E").rglob("trajectory.hdf5")))
