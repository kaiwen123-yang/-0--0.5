"""Read-only hypotheses for D. Summaries are native coordinates; no new label files."""
from pathlib import Path
import sys
import json
import numpy as np
import pyarrow.parquet as pq
from acquire import write_json
from arrays import distribution

root=Path(sys.argv[1])
base=next((root/"raw"/"D").rglob("meta/info.json")).parent.parent
norm=json.loads((base/"norm_stats.json").read_text())["norm_stats"]
parts={k:[] for k in ("state","action","state_minus_first_state","action_minus_first_state","action_minus_current_state","action_minus_first_action")}
first=[]
for path in sorted(base.glob("data/*/*.parquet")):
    t=pq.read_table(path)
    s=np.asarray(t["observation.state"].to_pylist())
    a=np.asarray(t["action"].to_pylist())
    parts["state"].append(s[:,:6])
    parts["action"].append(a[:,:6])
    parts["state_minus_first_state"].append(s[:,:6]-s[0,:6])
    parts["action_minus_first_state"].append(a[:,:6]-s[0,:6])
    parts["action_minus_current_state"].append(a[:,:6]-s[:,:6])
    parts["action_minus_first_action"].append(a[:,:6]-a[0,:6])
    first.append(dict(episode=int(path.stem.split("_")[-1]),state=s[0].tolist(),action=a[0].tolist()))
models={}
for key,seq in parts.items():
    x=np.concatenate(seq)
    ref=norm["state" if key.startswith("state") else "actions"]["mean"][:6]
    mean=x.mean(axis=0)
    models[key]=dict(native_mean=mean.tolist(),sidecar_norm_mean=ref,
                     max_abs_mean_difference=float(np.max(np.abs(mean-ref))))
write_json(root/"checks"/"D_first_rows.json",first)
result=dict(first_state_quantiles=distribution(np.array([v["state"] for v in first])),
        first_action_quantiles=distribution(np.array([v["action"] for v in first])),
        all_first_q_state_zero=sum(not any(v["state"][:6]) for v in first),
        all_first_q_action_zero=sum(not any(v["action"][:6]) for v in first),
        aggregate=models,scope="Diagnostic candidates only. Publication does not identify the exact weighting, reset pose or fitted data windows of each statistics file.")
write_json(root/"tables"/"D_representation.json",result)
