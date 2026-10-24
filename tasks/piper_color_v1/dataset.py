"""Audited NPZ -> memory mapped arrays and OpenPI Dataset adapter.

Action chunks are padded by repeating only the same episode's final command.
All three color targets for a layout stay in the same split. No future state,
object pose, stage label, target coordinates or success flag is a policy input.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def prepare(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    seeds = [set(v) for v in manifest["split_seeds"].values()]
    if any(a & b for i, a in enumerate(seeds) for b in seeds[i+1:]):
        raise ValueError("Layout leakage across splits")
    entries = []
    for e in manifest["episodes"]:
        if not e["success"]:
            raise ValueError(f"Failed teacher episode: {e['file']}")
        path = root / e["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != e["sha256"]:
            raise ValueError(f"Hash mismatch: {path}")
        with np.load(path, allow_pickle=False) as d:
            n = len(d["state"])
            assert d["state"].shape == d["action"].shape == (n, 7)
            assert np.isfinite(d["state"]).all() and np.isfinite(d["action"]).all()
            assert np.allclose(np.diff(d["timestamp"]), 1/20, atol=1e-8)
            assert np.max(np.abs(np.diff(d["action"][:,:6], axis=0))) <= .045001
            assert np.max(np.abs(np.diff(d["action"][:,6]))) <= .010001
            out = path.with_suffix("")
            out.mkdir(exist_ok=True)
            for key in ("state", "action", "external_rgb", "wrist_rgb"):
                a = d[key]
                if key.endswith("rgb"):
                    assert a.shape == (n, 224, 224, 3) and a.dtype == np.uint8
                np.save(out / f"{key}.npy", a, allow_pickle=False)
            prompt = str(d["prompt"])
            assert e["target"] in prompt
            entries.append(dict(directory=str(out.relative_to(root)), frames=n, split=e["split"],
                                layout_seed=e["layout_seed"], target=e["target"], prompt=prompt))
    report = dict(episodes=len(entries), frames=sum(e["frames"] for e in entries),
                  splits={s:sum(e["split"]==s for e in entries) for s in manifest["split_seeds"]},
                  layout_disjoint=True, finite=True, timestamp_hz=20, image_color_order="RGB",
                  labels="actual_command_targets_before_physics_step", hardware_execution=False)
    (root / "index.json").write_text(json.dumps(entries, indent=2))
    (root / "audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


class PiperDataset:
    def __init__(self, root, split="train", horizon=10):
        self.root = Path(root)
        self.entries = [e for e in json.loads((self.root / "index.json").read_text()) if e["split"] == split]
        self.ends = np.cumsum([e["frames"] for e in self.entries])
        self.horizon = horizon
        self.cache = {}

    def __len__(self):
        return int(self.ends[-1])

    def __getitem__(self, index):
        ep = int(np.searchsorted(self.ends, index, side="right"))
        frame = int(index-(self.ends[ep-1] if ep else 0))
        entry = self.entries[ep]
        if ep not in self.cache:
            self.cache[ep] = {k:np.load(self.root / entry["directory"] / f"{k}.npy", mmap_mode="r")
                              for k in ("state", "action", "external_rgb", "wrist_rgb")}
        d = self.cache[ep]
        chunk = np.minimum(np.arange(frame, frame+self.horizon), entry["frames"]-1)
        return dict(state=d["state"][frame].copy(), actions=d["action"][chunk].copy(),
                    external_rgb=d["external_rgb"][frame].copy(), wrist_rgb=d["wrist_rgb"][frame].copy(),
                    prompt=entry["prompt"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    prepare(p.parse_args().root)
