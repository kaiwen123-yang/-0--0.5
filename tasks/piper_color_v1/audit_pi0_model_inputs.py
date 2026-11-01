"""Inspect real transformed samples to test whether training loses prompt tokens."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, os.environ["PIPER_OPENPI"])
import numpy as np
from openpi.training import data_loader as D
from dataset import PiperDataset
from train_pi0_120 import config, DATA, RUN

cfg = config()
dc = cfg.data.create(cfg.assets_dirs, cfg.model)
raw = PiperDataset(DATA, "train", 10)
ds = D.transform_dataset(raw, dc)
rows = []
offset = 0
for entry in raw.entries:
    sample = ds[offset]
    ids = np.asarray(sample["tokenized_prompt"])
    rows.append({"layout": entry["layout_seed"], "target": entry["target"], "prompt": entry["prompt"],
        "token_ids": ids.tolist(), "token_mask": np.asarray(sample["tokenized_prompt_mask"]).tolist(),
        "token_sha256": hashlib.sha256(ids.tobytes()).hexdigest(),
        "padded_action_dimensions_zero": bool(np.all(np.asarray(sample["actions"])[:, 7:] == 0)),
        "action_shape": list(np.asarray(sample["actions"]).shape)})
    offset += entry["frames"]
unique = {c: sorted({r["token_sha256"] for r in rows if r["target"] == c}) for c in ("red", "green", "blue")}
report = {"actual_transformed_samples": len(rows), "color_token_hashes": unique,
    "distinct_prompt_token_sequences": len({r["token_sha256"] for r in rows}),
    "all_samples_padded_25_dimensions_zero": all(r["padded_action_dimensions_zero"] for r in rows),
    "freeze_filter": repr(cfg.freeze_filter), "action_dim": cfg.model.action_dim,
    "rows": rows, "diagnostic_only": True, "optimizer_updates": 0}
assert report["distinct_prompt_token_sequences"] == 3
out = RUN.parent / "pi0-120-regression-diagnosis-20261101/model_input_audit.json"
out.write_text(json.dumps(report, indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
