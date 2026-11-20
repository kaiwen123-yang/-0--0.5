"""Read explicitly labeled real episodes; observation-only recordings are not demonstrations.

Expected dataset files:
  dataset.json: data_kind='real_demonstrations', camera_mount, policy_hz=20,
                timestamp_alignment_source (actual alignment report path),
                action_representation='absolute_joint_targets_and_total_opening'
  index.json: [{directory, frames, split, prompt}, ...]
  <directory>/{state,actions,camera_rgb,policy_timestamps_ns}.npy

Each index entry is one complete episode. State and actions are [N,7]; RGB
is [N,H,W,3] uint8. Creating actual labels and dataset splits is a later task;
this reader does not infer commands from measured state or invent episodes.
Rows must already be aligned to a 50 ms policy grid, with original source
timestamps documented by timestamp_alignment_source. There is no implicit
resampling, and policy-grid time does not claim camera exposure synchronization.
"""

import json
from pathlib import Path

import numpy as np


POLICY_HZ = 20
POLICY_PERIOD_NS = 50_000_000


def training_data_requirements(root, camera_mount, policy_hz):
    """Return missing prerequisites without opening a GPU or synthesizing data."""
    root = Path(root).expanduser()
    missing = [str(root / name) for name in ("dataset.json", "index.json") if not (root / name).is_file()]
    if missing:
        return missing
    metadata = json.loads((root / "dataset.json").read_text())
    if metadata.get("data_kind") != "real_demonstrations":
        return ["dataset.json must identify real_demonstrations; observation_only is not labeled training data"]
    if metadata.get("camera_mount") != camera_mount:
        return ["dataset camera_mount does not match the selected model input slot"]
    if metadata.get("action_representation") != "absolute_joint_targets_and_total_opening":
        return ["actual absolute joint targets and total gripper opening labels have not been declared"]
    if policy_hz != POLICY_HZ or metadata.get("policy_hz") != policy_hz:
        return ["dataset.json and spec must declare policy_hz=20 after actual timestamp alignment"]
    source = metadata.get("timestamp_alignment_source")
    if not source:
        return ["dataset.json lacks timestamp_alignment_source for the actual recordings"]
    if not (root / source).is_file():
        return [str(root / source)]
    entries = json.loads((root / "index.json").read_text())
    training = [entry for entry in entries if entry["split"] == "train"]
    if not training:
        return ["index.json contains no labeled training episodes"]
    return [
        str(root / entry["directory"] / name)
        for entry in training
        for name in ("state.npy", "actions.npy", "camera_rgb.npy", "policy_timestamps_ns.npy")
        if not (root / entry["directory"] / name).is_file()
    ]


def read_policy_timestamps(directory, frames):
    timestamps = np.load(Path(directory) / "policy_timestamps_ns.npy", mmap_mode="r", allow_pickle=False)
    if timestamps.shape != (frames,) or not np.issubdtype(timestamps.dtype, np.integer):
        raise ValueError(f"{directory}: policy_timestamps_ns must be one integer timestamp per aligned row")
    if np.any(np.diff(timestamps) != POLICY_PERIOD_NS):
        raise ValueError(f"{directory}: rows are not on the declared 20 Hz policy grid; no implicit resampling")
    return timestamps


class SingleCameraDataset:
    def __init__(self, root, split, horizon, policy_hz):
        self.root = Path(root).expanduser()
        metadata = json.loads((self.root / "dataset.json").read_text())
        if policy_hz != POLICY_HZ or metadata.get("policy_hz") != policy_hz:
            raise ValueError("SingleCameraDataset requires explicit, aligned policy_hz=20 data")
        self.entries = [entry for entry in json.loads((self.root / "index.json").read_text()) if entry["split"] == split]
        self.ends = np.cumsum([entry["frames"] for entry in self.entries])
        self.horizon = horizon
        self.cache = {}

    def __len__(self):
        return int(self.ends[-1])

    def __getitem__(self, index):
        episode = int(np.searchsorted(self.ends, index, side="right"))
        frame = int(index - (self.ends[episode - 1] if episode else 0))
        entry = self.entries[episode]
        if episode not in self.cache:
            read_policy_timestamps(self.root / entry["directory"], entry["frames"])
            self.cache[episode] = {
                key: np.load(self.root / entry["directory"] / f"{key}.npy", mmap_mode="r", allow_pickle=False)
                for key in ("state", "actions", "camera_rgb")
            }
        arrays = self.cache[episode]
        indices = np.minimum(np.arange(frame, frame + self.horizon), entry["frames"] - 1)
        return {
            "state": arrays["state"][frame].copy(),
            "actions": arrays["actions"][indices].copy(),
            "camera_rgb": arrays["camera_rgb"][frame].copy(),
            "prompt": entry["prompt"],
        }
