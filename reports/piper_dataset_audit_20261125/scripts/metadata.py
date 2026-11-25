"""Inspect serialized sidecars, per-episode metadata, feature statistics and CoT keys."""
import builtins
import json
import pickle
import pickletools
from collections import Counter
from pathlib import Path
import sys
import numpy as np
import pyarrow.parquet as pq
from acquire import SOURCES,write_json


class IndexReader(pickle.Unpickler):
    # These five source indices use NumPy integer scalars. No arbitrary module imports.
    def find_class(self,module,name):
        if module in ("numpy.core.multiarray","numpy._core.multiarray") and name=="scalar":
            return np.core.multiarray.scalar
        if module=="numpy" and name=="dtype":
            return np.dtype
        raise ValueError((module,name))


def nonfinite(x):
    if isinstance(x,dict):
        return sum(nonfinite(v) for v in x.values())
    if isinstance(x,list):
        return sum(nonfinite(v) for v in x)
    return int(isinstance(x,float) and not np.isfinite(x))


def main(root):
    rows=[]
    for k in SOURCES:
        base=next((root/"raw"/k).rglob("meta/info.json")).parent.parent
        lens={v["episode_index"]:v["length"] for v in map(json.loads,(base/"meta/episodes.jsonl").read_text().splitlines())}
        for path in sorted((root/"raw"/k).rglob("*")):
            if not path.is_file() or path.suffix not in (".json",".jsonl",".pkl",".parquet"):
                continue
            if path.suffix==".parquet" and path.parent.parent.name=="data":
                continue
            r=dict(source=k,path=str(path.relative_to(root/"raw"/k)))
            if path.suffix in (".json",".jsonl"):
                content=[json.loads(s) for s in path.read_text().splitlines()] if path.suffix==".jsonl" else json.loads(path.read_text())
                r.update(type=type(content).__name__,n=len(content),nonfinite=nonfinite(content))
                if path.name=="episodes_stats.jsonl":
                    r["missing_or_extra_episode_ids"]=sorted(set(lens)^set(e["episode_index"] for e in content))
                    comparisons=Counter()
                    bad=[]
                    for e in content:
                        ep=e["episode_index"]
                        detail=json.loads((root/"checks"/"arrays"/k/f"episode_{ep:06}.json").read_text())
                        for field,name in (("observation.state","state"),("state","state"),("action","action"),("actions","action")):
                            st=e["stats"].get(field,{})
                            for attr,ix in (("min",0),("max",-1)):
                                if attr not in st:
                                    continue
                                delta=np.abs(np.asarray(st[attr])-np.asarray(detail["profile"][name]["q"][ix]))
                                comparisons["checked"]+=1
                                if np.max(delta)>1e-6:
                                    comparisons["different"]+=1
                                    bad.append([ep,field,attr,float(np.max(delta))])
                    r.update(comparisons=comparisons,mismatches=bad)
            elif path.suffix==".pkl":
                ops=Counter(op.name for op,_,_ in pickletools.genops(path.read_bytes()))
                with path.open("rb") as stream:
                    index=IndexReader(stream).load()
                computed=Counter()
                missing=0
                last={}
                for ep,i in index["steps"]:
                    ep,i=int(ep),int(i)
                    if ep not in lens or not 0<=i<lens[ep] or i!=last.get(ep,-1)+1:
                        missing+=1
                    last[ep]=i
                    computed[ep]+=1
                r.update(opcodes=ops,keys=list(index),rows=len(index["steps"]),order_or_bounds_issues=missing,
                         count_mismatch={str(e):[computed[e],n] for e,n in lens.items() if computed[e]!=n})
            else:
                t=pq.read_table(path)
                ep=t["episode_index"].to_numpy()
                fr=t["frame_index"].to_numpy()
                r.update(n=len(t),schema=str(t.schema.remove_metadata()),nulls={c:t[c].null_count for c in t.column_names},
                         empty_text={c:sum(not str(x or "").strip() for x in t[c].to_pylist()) for c in ("long_plan","reason","movement")},
                         nonfinite={c:int((~np.isfinite(t[c].to_numpy())).sum()) for c in ("gripper_u","gripper_v")},
                         negative_uv={c:int((t[c].to_numpy()<0).sum()) for c in ("gripper_u","gripper_v")},
                         duplicate_keys=len(t)-len(set(zip(ep,fr))),
                         episode_mismatch=[e for e,n in lens.items() if not np.array_equal(np.sort(fr[ep==e]),np.arange(n))])
                invalid=(t["gripper_u"].to_numpy()<0)|(t["gripper_v"].to_numpy()<0)
                r["negative_uv_keys"]=np.column_stack((ep[invalid],fr[invalid])).tolist()
            rows.append(r)
    write_json(root/"tables"/"sidecars.json",rows)


if __name__=="__main__":
    main(Path(sys.argv[1]))
