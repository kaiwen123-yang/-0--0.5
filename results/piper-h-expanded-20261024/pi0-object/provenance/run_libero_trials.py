"""Evaluate one official LIBERO suite, retaining every rollout and its outcome.

Run through scripts/run.sh libero. Model serving is a separate process; this
client never connects to a real robot. Infrastructure errors abort the run and
remain distinct from completed policy failures.
"""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time
import traceback


SUITES = ("libero_spatial", "libero_object", "libero_goal", "libero_10")
MAX_STEPS = dict(zip(SUITES, (220, 280, 300, 520), strict=True))
WAIT_STEPS = 10
REPLAN_STEPS = 5
IMAGE_SIZE = 224
VIDEO_FPS = 20
RECEIVE_TIMEOUT = 180


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def episode_key(record: dict) -> tuple:
    return record["model"], record["suite"], record["task_id"], record["trial_index"]


def load_records(path: Path) -> dict:
    records = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"Blank episode record at {path}:{line_number}")
            try:
                record = json.loads(line)
                key = episode_key(record)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f"Invalid episode record at {path}:{line_number}: {error}") from error
            if key in records:
                raise ValueError(f"Duplicate episode record {key} at {path}:{line_number}")
            if record.get("status") not in ("success", "failure", "error"):
                raise ValueError(f"Invalid status at {path}:{line_number}")
            if record.get("success") is not (record["status"] == "success"):
                raise ValueError(f"Inconsistent success/status at {path}:{line_number}")
            records[key] = record
    return records


def append_record(path: Path, record: dict, records: dict) -> None:
    key = episode_key(record)
    if key in records:
        raise ValueError(f"Refusing duplicate episode {key}")
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    records[key] = record


def update_progress(run_dir: Path, args, records: dict, *, state: str, current=None, error=None) -> None:
    selected = [
        row for row in records.values()
        if row["model"] == args.model and row["suite"] == args.suite
        and row["task_id"] in args.task_ids and row["trial_index"] < args.trials
    ]
    counts = {status: sum(row["status"] == status for row in selected) for status in ("success", "failure", "error")}
    atomic_json(run_dir / "progress-episodes.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name,
        "model": args.model,
        "suite": args.suite,
        "state": state,
        "current_episode": current,
        "planned_episodes_this_invocation": len(args.task_ids) * args.trials,
        "completed_valid_episodes_this_invocation": counts["success"] + counts["failure"],
        "counts_this_invocation": counts,
        "all_recorded_episodes": len(records),
        "error": error,
    })


def load_upstream_main(root: Path):
    name = "_openpi_official_libero_eval"
    path = root / "repos/openpi/examples/libero/main.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import official LIBERO helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def connect_client(host: str, port: int):
    """Use the official wire protocol with bounded connect/receive operations."""
    from openpi_client import msgpack_numpy
    from openpi_client import websocket_client_policy
    import websockets.sync.client

    class BoundedClient(websocket_client_policy.WebsocketClientPolicy):
        def _wait_for_server(self):
            deadline = time.monotonic() + RECEIVE_TIMEOUT
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Policy server did not become ready within {RECEIVE_TIMEOUT}s: {self._uri}")
                try:
                    connection = websockets.sync.client.connect(
                        self._uri,
                        compression=None,
                        max_size=None,
                        open_timeout=min(30, remaining),
                        close_timeout=10,
                    )
                except (ConnectionRefusedError, TimeoutError):
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                    continue
                try:
                    metadata = msgpack_numpy.unpackb(connection.recv(timeout=max(0.1, deadline - time.monotonic())))
                except BaseException:
                    connection.close()
                    raise
                return connection, metadata

        def infer(self, observation):
            self._ws.send(self._packer.pack(observation))
            response = self._ws.recv(timeout=RECEIVE_TIMEOUT)
            if isinstance(response, str):
                raise RuntimeError(f"Policy server error: {response}")
            result = msgpack_numpy.unpackb(response)
            if not isinstance(result, dict):
                raise ValueError("Policy server response is not a dictionary")
            return result

    return BoundedClient(host=host, port=port)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", choices=("pi0", "pi05"), required=True)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--render-backend", choices=("gpu", "cpu"), default="gpu")
    parser.add_argument("--egl-device", type=int, default=0)
    parser.add_argument("--task-ids", type=int, nargs="+", default=list(range(10)))
    args = parser.parse_args()
    if not args.run_dir.is_absolute():
        parser.error("--run-dir must be absolute")
    if args.trials < 1 or args.seed < 0 or args.egl_device < 0:
        parser.error("--trials must be positive; --seed and --egl-device must be nonnegative")
    if len(set(args.task_ids)) != len(args.task_ids) or any(task < 0 for task in args.task_ids):
        parser.error("--task-ids must contain distinct nonnegative task indices")
    return args


def evaluate(args) -> int:
    from libero_bootstrap import ROOT, allow_trusted_initial_states, configure, configure_software_rendering

    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    records_path = run_dir / "episodes.jsonl"
    records = load_records(records_path)
    for task_id in args.task_ids:
        for trial in range(args.trials):
            existing = records.get((args.model, args.suite, task_id, trial))
            if existing and existing["status"] == "error":
                raise ValueError(f"Existing error record for {(args.model, args.suite, task_id, trial)}; refusing to overwrite or silently skip it")
            if existing:
                expected_policy_seed = args.seed + SUITES.index(args.suite) * 10000 + task_id * 100 + trial
                if existing.get("seed") != args.seed or existing.get("policy_seed") != expected_policy_seed:
                    raise ValueError(f"Existing episode has different seeds: {episode_key(existing)}")
                if existing.get("render_backend") != args.render_backend:
                    raise ValueError(f"Existing episode has a different renderer: {episode_key(existing)}")
                for field in ("video_path", "actions_path"):
                    relative_path = existing.get(field)
                    if not relative_path or not (run_dir / relative_path).is_file():
                        raise ValueError(f"Existing episode is missing its {field}: {episode_key(existing)}")

    configure()
    if args.render_backend == "cpu":
        configure_software_rendering()
    else:
        for key in ("__EGL_VENDOR_LIBRARY_FILENAMES", "LIBGL_ALWAYS_SOFTWARE", "MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER", "LP_NUM_THREADS"):
            os.environ.pop(key, None)
        os.environ["MUJOCO_GL"] = "egl"
        os.environ["PYOPENGL_PLATFORM"] = "egl"
        os.environ["MUJOCO_EGL_DEVICE_ID"] = str(args.egl_device)
    allow_trusted_initial_states()

    import imageio.v2 as imageio
    import numpy as np
    from libero.libero import benchmark
    from openpi_client import image_tools

    upstream = load_upstream_main(ROOT)
    task_suite = benchmark.get_benchmark_dict()[args.suite]()
    if any(task_id >= task_suite.n_tasks for task_id in args.task_ids):
        raise ValueError(f"Task IDs out of range for {args.suite}: {args.task_ids}")
    client = connect_client(args.host, args.port)
    server_metadata = client.get_server_metadata()
    if not isinstance(server_metadata, dict) or server_metadata.get("model") != args.model or server_metadata.get("run_id") != run_dir.name:
        client._ws.close()
        raise ValueError(f"Policy server identity mismatch; expected model={args.model}, run_id={run_dir.name}, got {server_metadata!r}")

    def images(observation):
        return tuple(
            image_tools.convert_to_uint8(image_tools.resize_with_pad(
                np.ascontiguousarray(observation[key][::-1, ::-1]), IMAGE_SIZE, IMAGE_SIZE,
            )) for key in ("agentview_image", "robot0_eye_in_hand_image")
        )

    update_progress(run_dir, args, records, state="running")
    try:
        for task_id in args.task_ids:
            pending_trials = [trial for trial in range(args.trials) if (args.model, args.suite, task_id, trial) not in records]
            if not pending_trials:
                logging.info("Skipping completed model=%s suite=%s task=%s", args.model, args.suite, task_id)
                continue
            task = task_suite.get_task(task_id)
            initial_states = task_suite.get_task_init_states(task_id)
            if len(initial_states) < args.trials:
                raise ValueError(f"Task {task_id} has only {len(initial_states)} initial states, requested {args.trials}")
            env = None
            try:
                np.random.seed(args.seed)
                env, task_description = upstream._get_libero_env(task, upstream.LIBERO_ENV_RESOLUTION, args.seed)
                for trial in pending_trials:
                    episode_id = f"{args.suite}/{task_id}/{trial}"
                    policy_seed = args.seed + SUITES.index(args.suite) * 10000 + task_id * 100 + trial
                    initial_state = np.ascontiguousarray(np.asarray(initial_states[trial]))
                    initial_sha256 = hashlib.sha256(initial_state.tobytes(order="C")).hexdigest()
                    update_progress(run_dir, args, records, state="running", current=episode_id)
                    video_directory = run_dir / "videos" / args.model / args.suite / f"task_{task_id:02d}"
                    actions_directory = run_dir / "actions" / args.model / args.suite / f"task_{task_id:02d}"
                    video_directory.mkdir(parents=True, exist_ok=True)
                    actions_directory.mkdir(parents=True, exist_ok=True)
                    temporary_video = video_directory / f"trial_{trial:03d}.partial.mp4"
                    if temporary_video.exists():
                        raise ValueError(f"Uncommitted video exists, refusing to overwrite: {temporary_video}")
                    started = time.monotonic()
                    writer = None
                    writer_closed = False
                    observation = None
                    executed_actions = []
                    video_frames = inference_calls = steps = 0
                    success = False
                    error_text = None
                    status = "failure"
                    try:
                        # Reset independently so resume/skipping earlier trials does
                        # not change this episode's environment random sequence.
                        np.random.seed(args.seed)
                        env.seed(args.seed)
                        env.reset()
                        observation = env.set_init_state(initial_state)
                        for _ in range(WAIT_STEPS):
                            observation, _, _, _ = env.step(upstream.LIBERO_DUMMY_ACTION)
                        action_plan = collections.deque()
                        writer = imageio.get_writer(temporary_video, fps=VIDEO_FPS, codec="libx264", quality=7)
                        for _ in range(MAX_STEPS[args.suite]):
                            image, wrist_image = images(observation)
                            writer.append_data(np.concatenate((image, wrist_image), axis=1))
                            video_frames += 1
                            if not action_plan:
                                request = {
                                    "observation/image": image,
                                    "observation/wrist_image": wrist_image,
                                    "observation/state": np.concatenate((
                                        observation["robot0_eef_pos"],
                                        upstream._quat2axisangle(observation["robot0_eef_quat"].copy()),
                                        observation["robot0_gripper_qpos"],
                                    )),
                                    "prompt": str(task_description),
                                    "evaluation/episode_id": episode_id,
                                    "evaluation/seed": policy_seed,
                                }
                                inference_calls += 1
                                action_chunk = np.asarray(client.infer(request)["actions"])
                                if action_chunk.ndim != 2 or action_chunk.shape[0] < REPLAN_STEPS or action_chunk.shape[1] != 7:
                                    raise ValueError(f"Unexpected policy action shape {action_chunk.shape}")
                                if not np.isfinite(action_chunk).all():
                                    raise ValueError("Policy returned nonfinite actions")
                                action_plan.extend(action_chunk[:REPLAN_STEPS])
                            action = np.asarray(action_plan.popleft())
                            observation, _, done, _ = env.step(action.tolist())
                            executed_actions.append(action.copy())
                            steps += 1
                            if done:
                                success = True
                                status = "success"
                                break
                        # Include the final successful/timeout state in the video.
                        image, wrist_image = images(observation)
                        writer.append_data(np.concatenate((image, wrist_image), axis=1))
                        video_frames += 1
                    except Exception:
                        status = "error"
                        success = False
                        error_text = traceback.format_exc()
                    finally:
                        if writer is not None:
                            try:
                                writer.close()
                                writer_closed = True
                            except Exception:
                                status = "error"
                                success = False
                                error_text = (error_text or "") + "\nVideo finalization failed:\n" + traceback.format_exc()

                    video_path = None
                    if writer_closed and temporary_video.is_file() and temporary_video.stat().st_size > 0:
                        final_video = video_directory / f"trial_{trial:03d}_{status}.mp4"
                        if final_video.exists():
                            raise ValueError(f"Refusing to overwrite video: {final_video}")
                        os.replace(temporary_video, final_video)
                        video_path = str(final_video.relative_to(run_dir))
                    elif status != "error":
                        status = "error"
                        success = False
                        error_text = "Video encoder did not produce a nonempty file"
                    final_actions = actions_directory / f"trial_{trial:03d}_{status}.npy"
                    if final_actions.exists():
                        raise ValueError(f"Refusing to overwrite actions: {final_actions}")
                    temporary_actions = final_actions.with_name(final_actions.name + ".tmp")
                    with temporary_actions.open("wb") as handle:
                        action_array = np.asarray(executed_actions) if executed_actions else np.empty((0, 7), dtype=np.float32)
                        np.save(handle, action_array, allow_pickle=False)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary_actions, final_actions)
                    record = {
                        "model": args.model,
                        "suite": args.suite,
                        "task_id": task_id,
                        "task_name": str(task_description),
                        "trial_index": trial,
                        "initial_state_index": trial,
                        "seed": args.seed,
                        "policy_seed": policy_seed,
                        "episode_id": episode_id,
                        "initial_state_sha256": initial_sha256,
                        "initial_state_dtype": str(initial_state.dtype),
                        "initial_state_shape": list(initial_state.shape),
                        "success": success,
                        "status": status,
                        "steps": steps,
                        "elapsed_seconds": time.monotonic() - started,
                        "video_path": video_path,
                        "video_frames": video_frames,
                        "video_fps": VIDEO_FPS,
                        "actions_path": str(final_actions.relative_to(run_dir)),
                        "error": error_text,
                        "inference_calls": inference_calls,
                        "environment_seed_reset_each_episode": True,
                        "policy_seed_formula": "seed + suite_index*10000 + task_id*100 + trial_index",
                        "policy_seed_reset_protocol": "server resets JAX RNG on first inference for evaluation/episode_id",
                        "suite_index": SUITES.index(args.suite),
                        "render_backend": args.render_backend,
                        "egl_device": os.environ.get("MUJOCO_EGL_DEVICE_ID"),
                        "wait_steps": WAIT_STEPS,
                        "max_action_steps": MAX_STEPS[args.suite],
                        "replan_steps": REPLAN_STEPS,
                        "server_metadata": server_metadata,
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
                    append_record(records_path, record, records)
                    logging.info("EPISODE %s", json.dumps({key: record[key] for key in (
                        "model", "suite", "task_id", "trial_index", "status", "steps", "elapsed_seconds", "video_path",
                    )}, ensure_ascii=False))
                    update_progress(run_dir, args, records, state="error" if status == "error" else "running", current=episode_id, error=error_text)
                    if status == "error":
                        logging.error("Episode aborted with an infrastructure/model-output error:\n%s", error_text)
                        return 1
            finally:
                if env is not None:
                    env.close()
    except Exception:
        update_progress(run_dir, args, records, state="error", error=traceback.format_exc())
        raise
    finally:
        client._ws.close()
    update_progress(run_dir, args, records, state="complete")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    try:
        return evaluate(args)
    except Exception:
        logging.exception("LIBERO evaluation aborted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
