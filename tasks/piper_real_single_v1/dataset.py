"""Read explicitly labeled real episodes; observation-only recordings are not demonstrations.

Expected dataset files:
  dataset.json: data_kind='real_demonstrations' or 'real_kinesthetic_demonstrations',
                camera_mount, policy_hz=20,
                timestamp_alignment_source (actual alignment report path),
                gripper_basis='piper_h_sdk_width_m_v1' for formal data
  index.json: [{directory, frames, split, prompt}, ...]
  <directory>/{state,actions,camera_rgb,policy_timestamps_ns}.npy

Each index entry is one complete episode. State and actions are [N,7]; RGB
is [N,H,W,3] uint8. Direct kinesthetic episodes explicitly label future measured
joint positions as targets. The gripper target is a submitted width for powered
grasping or a future measured width for manual finger demonstrations.
An optional valid_action_starts.npy selects complete usable chunks while keeping
the original arrays and 50 ms sequence, including excluded rows, unchanged.
Rows must already be aligned to a 50 ms policy grid, with original source
timestamps documented by timestamp_alignment_source. There is no implicit
resampling, and policy-grid time does not claim camera exposure synchronization.
"""

import json
from pathlib import Path

import numpy as np


if __package__:
    from .color_task import BLUE_RED, recorded_task
    from .width_contract import CAMERA, REPRESENTATION, RETREAT, WIDTH
else:
    from color_task import BLUE_RED, recorded_task
    from width_contract import CAMERA, REPRESENTATION, RETREAT, WIDTH


POLICY_HZ = 20
POLICY_PERIOD_NS = 50_000_000
DIRECT_MODE = "kinesthetic_direct_v1"
DIRECT_DATA_KIND = "real_kinesthetic_demonstrations"
FUTURE_JOINT_SOURCE = "future_measured_joint_positions"
GRIP_COMMAND_SOURCE = "actual_submitted_sdk_width_target"
MANUAL_MODE = "kinesthetic_manual_gripper_v1"
FUTURE_GRIP_SOURCE = "future_measured_sdk_width"
GRIP_SOURCES = {DIRECT_MODE: GRIP_COMMAND_SOURCE, MANUAL_MODE: FUTURE_GRIP_SOURCE}


def formal_entries(root, camera_mount, policy_hz):
    metadata = json.loads((root/"dataset.json").read_text())
    if (metadata.get("training_eligible") is not True or metadata.get("gripper_basis") != WIDTH
            or metadata.get("action_representation") != REPRESENTATION
            or metadata.get("data_kind") not in ("real_demonstrations", DIRECT_DATA_KIND) or camera_mount != "wrist"
            or metadata.get("camera_mount") != camera_mount or metadata.get("camera_id") != CAMERA
            or metadata.get("policy_hz") != POLICY_HZ or policy_hz != POLICY_HZ):
        raise ValueError("Formal data requires training eligibility and the explicit single wrist SDK width contract")
    alignment = json.loads((root/metadata["timestamp_alignment_source"]).read_text())
    entries = json.loads((root/"index.json").read_text())
    by_id = {a["directory"]:a for a in alignment["episodes"]}
    ids = [e["directory"] for e in entries]
    if (alignment.get("gripper_basis") != WIDTH or alignment.get("period_ns") != POLICY_PERIOD_NS
            or not entries or len(set(ids)) != len(ids) or set(ids) != set(by_id)
            or len(alignment["episodes"]) != len(entries)):
        raise ValueError("Index and alignment episode identities or contract differ")
    groups = {}
    for e in entries:
        a = by_id[e["directory"]]
        mode = e.get("collection_mode")
        direct = mode in GRIP_SOURCES
        if a.get("collection_mode") != mode:
            raise ValueError("Index and alignment disagree on the episode collection mode")
        if metadata.get("data_kind") == DIRECT_DATA_KIND and not direct:
            raise ValueError("Kinesthetic collection contains an episode without its action-source contract")
        if metadata.get("collection_view") in ("all_colors", "blue_red"):
            if (recorded_task(e) != recorded_task(a) or a["sources"] != f"{e['directory']}/row_sources.jsonl"
                    or alignment.get("collection_view") != metadata["collection_view"]):
                raise ValueError("Episode instruction or row provenance differs from alignment")
            for record in (e, a):
                if (record["run_id"] != e["directory"] or record["actual_grasped_color"] != e["target_color"]
                        or record["intervention"] != "no" or record["outcome"] != "success"):
                    raise ValueError("Episode does not have a matching reviewed success")
        for r in (e,a):
            if (r.get("training_eligible") is not True or r.get("gripper_basis") != WIDTH
                    or r.get("terminal_kind") != RETREAT or r.get("terminal_version") != 1
                    or r.get("split") != e["split"] or e["split"] not in ("train","validation")):
                raise ValueError("Formal episode has incompatible eligibility, split or source contract")
            if direct and (r.get("arm_action_source") != FUTURE_JOINT_SOURCE
                           or r.get("gripper_action_source") != GRIP_SOURCES[mode]
                           or r.get("future_offset_ns") != POLICY_PERIOD_NS):
                raise ValueError("Kinesthetic target provenance differs from its 50 ms contract")
        if e["frames"] <= 0 or not (root/a["sources"]).is_file():
            raise ValueError("Missing episode rows or their sources")
        if direct and (e.get("valid_action_starts") != "valid_action_starts.npy"
                       or e.get("action_horizon") != 10 or e.get("usable_starts", 0) <= 0
                       or not (root/e["directory"]/e["valid_action_starts"]).is_file()):
            raise ValueError("Kinesthetic episode has no usable ten-step action chunks")
        for key in ("session_id","placement_id","source_trajectory_id"):
            if not a.get(key) or groups.setdefault((key,a[key]),e["split"]) != e["split"]:
                raise ValueError(f"Missing group or cross-split reuse: {key}")
    return entries


def training_data_requirements(root, camera_mount, policy_hz):
    """Return missing prerequisites without opening a GPU or synthesizing data."""
    root = Path(root).expanduser()
    missing = [str(root / name) for name in ("dataset.json", "index.json") if not (root / name).is_file()]
    if missing:
        return missing
    try:
        entries = formal_entries(root,camera_mount,policy_hz)
        metadata = json.loads((root/"dataset.json").read_text())
        if metadata.get("collection_view") != "blue_red" or metadata.get("target_colors") != list(BLUE_RED):
            return ["Stage A requires the frozen blue_red view of the full collection"]
        for split in ("train", "validation"):
            if {e["target_color"] for e in entries if e["split"] == split} != set(BLUE_RED):
                return [f"Stage A {split} needs reviewed blue and red targets only"]
    except (ValueError, KeyError, OSError) as exc:
        return [str(exc)]
    if {e["split"] for e in entries} != {"train","validation"}:
        return ["training requires both independent train and validation sessions"]
    return [
        str(root / entry["directory"] / name)
        for entry in entries
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
        if split in ("train","validation"):
            entries = formal_entries(self.root,"wrist",policy_hz)
        elif split == "commissioning" and metadata.get("training_eligible") is False:
            entries = json.loads((self.root/"index.json").read_text())
        else:
            raise ValueError("Unknown split or commissioning eligibility mismatch")
        self.entries = [e for e in entries if e["split"] == split]
        if not self.entries:
            raise ValueError(f"No episodes for split {split}")
        self.horizon = horizon
        self.starts = []
        for entry in self.entries:
            starts = None
            if entry.get("valid_action_starts"):
                if entry["action_horizon"] != horizon:
                    raise ValueError("Re-export valid action starts for the requested horizon")
                starts = np.load(self.root/entry["directory"]/entry["valid_action_starts"],
                                 mmap_mode="r", allow_pickle=False)
                if (starts.ndim != 1 or not np.issubdtype(starts.dtype, np.integer)
                        or len(starts) != entry["usable_starts"] or not len(starts)
                        or starts[0] < 0 or starts[-1] >= entry["frames"]
                        or np.any(np.diff(starts) <= 0)):
                    raise ValueError("Invalid action-start indices")
            self.starts.append(starts)
        self.ends = np.cumsum([len(starts) if starts is not None else entry["frames"]
                               for entry, starts in zip(self.entries, self.starts, strict=True)])
        self.cache = {}

    def __len__(self):
        return int(self.ends[-1])

    def __getitem__(self, index):
        episode = int(np.searchsorted(self.ends, index, side="right"))
        frame = int(index - (self.ends[episode - 1] if episode else 0))
        if self.starts[episode] is not None:
            frame = int(self.starts[episode][frame])
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
