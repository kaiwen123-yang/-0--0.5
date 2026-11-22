#!/usr/bin/env python3
"""Single RGB camera calibration from real, stationary captures. No robot I/O.

Requires the existing Python environment with numpy and OpenCV (4.x, with
findChessboardCornersSB). Do not replace the project's ROS/SDK environment.

Commands (all paths below are local files, not ROS topic names):
  python calibration.py detect --spec calibration_spec.json \
      --manifest captures.jsonl --out results/calibration/detect
  python calibration.py intrinsics --spec calibration_spec.json \
      --manifest captures.jsonl --out results/calibration/intrinsics
  python calibration.py handeye --spec calibration_spec.json \
      --manifest captures.jsonl \
      --intrinsics results/calibration/intrinsics/intrinsics.json \
      --method park --out results/calibration/handeye

Copy calibration_spec.example.json and enter the *received* board geometry.
The example intentionally contains unconfirmed values and cannot fit anything.
Inner corners are one fewer than squares in each direction; lengths are metres.

Each JSONL row represents one actual captured RGB image. Relative image paths
are resolved against the manifest directory. Required fields for fitting:
  sample_id: unique string
  image_path: path to the current RGB stream's unchanged frame (no extra
              undistortion or resizing by the capture/calibration tool)
  split: "train" or "heldout" (choose before fitting)
  pose_group: capture/pose identifier; frames from one pose share this value
Optional corner_order: "detected" (default) or "reverse_180". Square boards also
allow "rotate_90_cw" and "rotate_90_ccw". Inspect the labelled origin in overlays
and choose ordering so it always denotes the SAME physical board corner.

Hand-eye additionally requires, for EVERY used row:
  T_base_gripper: measured/verified-FK 4x4 rigid transform, translation in metres
  pose_verified: true
  static_capture_verified: true
  board_orientation_verified: true
No pose is inferred from a commanded joint target, cached SDK poll or guessed
FK model. The spec records the exact verified base/gripper frames and FK source.
Image and feedback timestamps belong in the recording manifest; this tool does
not turn nearest receive-time association into exposure synchronisation.

Convention: T_a_b maps coordinates in frame b into frame a. Let G_i be
T_base_gripper and C_i be T_camera_target obtained by PnP using RGB intrinsics.
The camera frame is the optical frame of the calibrated RGB image model, not
the camera housing or the unregistered depth camera.

external_fixed (supported alternative): camera stays fixed to the base/
world; board is rigidly fixed to a fixed part of the gripper/flange. The board
must not move relative to that frame, e.g. with moving gripper jaws. Supply
inverse(G_i) and C_i to OpenCV calibrateHandEye; its result is X=T_base_camera.
    inverse(G_i) @ X @ C_i = T_gripper_target (constant)

wrist (confirmed installation on 2026-11-20): camera is rigidly fixed to the gripper/flange; board stays fixed relative
to the robot base/world. Supply G_i and C_i; X=T_gripper_camera.
    G_i @ X @ C_i = T_base_target (constant)

The robot base itself must stay fixed during either acquisition. A fixed
external camera observing a board also fixed on the table cannot establish the
arm-camera transform using these hand-eye equations.

Intrinsics use training views only. Held-out reprojection holds K,D fixed and
estimates only each held-out board pose. That measures image-model performance,
not independent metric accuracy. Hand-eye held-out residuals compare each
held-out constant transform with a constant fitted from TRAINING views only.
No result is labelled physically validated or automatically published as TF.
Do not choose poses/parameters repeatedly against the same held-out set.

Select the current stream's image_domain before fitting. "received" fits an
effective K and five residual Brown-Conrady coefficients to the unchanged,
reproducible received pixels. Record the observed processing chain and retain
unknown device-internal rectification as null; proving the ISP implementation
is not required. image_domain_verified then confirms the recorded pixel
pipeline, not raw-sensor or rectification status. This approximate image model
still requires held-out validation and does not model arbitrary ISP warps.
"raw" requires evidence of raw geometric pixels and fits five coefficients;
"rectified" requires rectification evidence, holds D=0 and fits effective K.
All modes use the same unchanged frames; none applies another undistortion.
For "received", the fitted optical axes are +x right, +y down, +z forward.
The ROS frame name binds this image model; it does not independently establish
coincidence with the physical sensor axes if internal virtual rotation exists.
This tool accepts only its own real checkerboard-fit intrinsics for hand-eye;
H0 CameraInfo D=[0,0,0,0,0] does not establish which domain the stream uses.
It neither changes the camera driver nor registers raw depth into RGB.

Exit codes: 0 = artifacts produced, 2 = NOT_RUN (missing/unconfirmed inputs),
1 = invalid inputs/processing error. Reports never contain placeholder poses.
"""

import argparse
import json
import math
from pathlib import Path
import re
import sys


class NotReady(RuntimeError):
    pass


CAMERA_MODELS = {
    "raw": "raw_rgb_brown_conrady_5",
    "rectified": "effective_rectified_pinhole",
    "received": "effective_received_rgb_brown_conrady_5",
}


def image_geometry_metadata(spec):
    return {
        "camera_id": spec.get("camera_id"),
        "image_domain_evidence": spec.get("image_domain_evidence"),
        "device_internal_rectification": spec.get("device_internal_rectification"),
        "camera_frame_definition": (
            "Optical frame of this calibrated RGB image model: +x right, +y down, +z forward. "
            "Not a camera-housing or unregistered-depth transform. For received pixels, "
            "coincidence with unprocessed physical sensor axes is not asserted."
        ),
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def load_spec(path, *, fitting):
    spec = json.loads(path.read_text())
    mode = spec.get("mount_mode")
    expected_role = {"external_fixed": "base_0_rgb", "wrist": "left_wrist_0_rgb"}
    if mode not in expected_role or spec.get("camera_role") != expected_role[mode]:
        raise ValueError("Select external_fixed/base_0_rgb or wrist/left_wrist_0_rgb explicitly.")
    if fitting and (spec.get("image_domain_verified") is not True or spec.get("image_domain") is None):
        raise NotReady("Confirm the recorded pixel pipeline and select received, raw or rectified; CameraInfo D=0 alone is insufficient.")
    if fitting and spec.get("image_domain") not in CAMERA_MODELS:
        raise ValueError("image_domain must explicitly be received, raw or rectified.")
    if fitting and spec["image_domain"] == "received":
        evidence = spec.get("image_domain_evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise NotReady("Received-stream fitting needs evidence of the fixed resolution and processing chain.")
    board = spec.get("board", {})
    if board.get("type") != "chessboard":
        raise ValueError("This minimal tool supports a chessboard, not an unspecified ChArUco board.")
    if board.get("geometry_verified") is not True:
        raise NotReady("Received board geometry has not been verified; no calibration was run.")
    for name in ("inner_corners_cols", "inner_corners_rows"):
        value = board.get(name)
        if type(value) is not int or value < 3:
            raise ValueError(f"board.{name} must be an actual inner-corner count >= 3.")
    length = board.get("square_size_m")
    if type(length) not in (int, float) or not math.isfinite(length) or length <= 0:
        raise ValueError("board.square_size_m must be the measured/documented spacing in metres.")
    size = spec.get("image_size")
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise ValueError("image_size must be the actual [width,height] of the unchanged RGB stream.")
    return spec


def load_records(path):
    if not path.is_file():
        raise NotReady(f"No real capture manifest: {path}")
    records, ids, paths, groups = [], set(), set(), {}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in ids:
            raise ValueError(f"Line {line_no}: sample_id must be a unique nonempty string.")
        if not isinstance(row.get("image_path"), str) or not row["image_path"]:
            raise ValueError(f"{sample_id}: image_path is required.")
        image_path = Path(row["image_path"])
        if not image_path.is_absolute():
            image_path = path.parent / image_path
        image_path = image_path.resolve()
        if image_path in paths:
            raise ValueError(f"Same image is listed more than once: {image_path}")
        split, group = row.get("split"), row.get("pose_group")
        if split in ("train", "heldout") and group:
            if group in groups and groups[group] != split:
                raise ValueError(f"pose_group {group!r} appears in both train and heldout.")
            groups[group] = split
        row["image_path"] = str(image_path)
        ids.add(sample_id)
        paths.add(image_path)
        records.append(row)
    if not records:
        raise NotReady("The capture manifest is empty; no real images were processed.")
    return records


def board_points(spec, np):
    board = spec["board"]
    cols, rows = board["inner_corners_cols"], board["inner_corners_rows"]
    points = np.zeros((cols * rows, 3), dtype=np.float32)
    points[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    return points * board["square_size_m"]


def detect(records, spec, out, cv2, np):
    cols = spec["board"]["inner_corners_cols"]
    rows = spec["board"]["inner_corners_rows"]
    width, height = spec["image_size"]
    accepted, report = [], []
    bins = np.zeros((4, 6), dtype=int)
    overlay_dir = out / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    flags = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    for index, row in enumerate(records):
        if row.get("camera_role", spec["camera_role"]) != spec["camera_role"]:
            raise ValueError(f"{row['sample_id']}: camera_role differs from the selected single camera.")
        item = {"sample_id": row["sample_id"], "image_path": row["image_path"],
                "split": row.get("split"), "pose_group": row.get("pose_group")}
        image = cv2.imread(row["image_path"], cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if image is None:
            item.update(status="REJECTED", reason="Image could not be read.")
            report.append(item)
            continue
        if image.shape[:2] != (height, width):
            item.update(status="REJECTED", reason="Image dimensions differ from the selected RGB mode.",
                        actual_image_size=[int(image.shape[1]), int(image.shape[0])])
            report.append(item)
            continue
        found, corners = cv2.findChessboardCornersSB(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                                                    (cols, rows), flags=flags)
        if not found:
            item.update(status="NO_TARGET", reason="The complete specified chessboard was not detected.")
            report.append(item)
            continue
        order = row.get("corner_order", "detected")
        grid = corners.reshape(rows, cols, 2)
        if order == "reverse_180":
            grid = grid[::-1, ::-1]
        elif order in ("rotate_90_cw", "rotate_90_ccw") and cols == rows:
            grid = np.rot90(grid, k=-1 if order == "rotate_90_cw" else 1)
        elif order != "detected":
            raise ValueError(f"{row['sample_id']}: invalid corner_order (90-degree orders require a square board).")
        corners = np.ascontiguousarray(grid.reshape(-1, 1, 2), dtype=np.float32)
        xy = corners.reshape(-1, 2)
        area = float(cv2.contourArea(cv2.convexHull(corners))) / (width * height)
        for x, y in xy:
            bins[min(3, max(0, int(y / height * 4))), min(5, max(0, int(x / width * 6)))] += 1
        cv2.drawChessboardCorners(image, (cols, rows), corners, True)
        for label, point in (("ORIGIN 0", xy[0]), (f"LAST {len(xy)-1}", xy[-1])):
            p = tuple(int(round(v)) for v in point)
            cv2.circle(image, p, 7, (0, 0, 255), 2)
            cv2.putText(image, label, (max(0, p[0] - 35), max(18, p[1] - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", row["sample_id"])[:100]
        overlay = overlay_dir / f"{index:04d}_{safe_id}.png"
        if not cv2.imwrite(str(overlay), image):
            raise OSError(f"Could not write {overlay}")
        item.update(status="DETECTED", corner_order=order, corners_px=xy.tolist(),
                    corner_hull_image_fraction=area,
                    corner_bbox_px=[*xy.min(axis=0).astype(float).tolist(),
                                    *xy.max(axis=0).astype(float).tolist()],
                    overlay_path=str(overlay.resolve()))
        report.append(item)
        accepted.append({**row, "corners": corners})
    write_json(out / "detection.json", {
        "status": "DETECTION_ONLY", "camera_role": spec["camera_role"],
        "image_domain": spec.get("image_domain"), "image_domain_verified": spec.get("image_domain_verified") is True,
        **image_geometry_metadata(spec),
        "image_size": spec["image_size"], "board": spec["board"],
        "detector": "OpenCV findChessboardCornersSB", "opencv_version": cv2.__version__,
        "image_count": len(records), "detected_count": len(accepted),
        "coverage_grid_6_by_4_corner_counts": bins.tolist(),
        "coverage_grid_occupied_fraction": float(np.count_nonzero(bins)) / bins.size,
        "coverage_note": "Image coverage only; this does not establish diverse 3D rotations or accuracy.",
        "samples": report,
    })
    return accepted


def fitting_splits(records, spec):
    for row in records:
        if row.get("split") not in ("train", "heldout"):
            raise ValueError(f"{row['sample_id']}: assign train or heldout before fitting.")
        if not isinstance(row.get("pose_group"), str) or not row["pose_group"]:
            raise ValueError(f"{row['sample_id']}: pose_group is required for independent split checks.")
    train = [r for r in records if r["split"] == "train"]
    heldout = [r for r in records if r["split"] == "heldout"]
    counts = spec.get("minimum_views", {"train": 15, "heldout": 5})
    for name, subset in (("train", train), ("heldout", heldout)):
        minimum = counts.get(name)
        if type(minimum) is not int or minimum < (3 if name == "train" else 1):
            raise ValueError("minimum_views must specify train >= 3 and heldout >= 1.")
        unique_groups = len({r["pose_group"] for r in subset})
        if unique_groups < minimum:
            raise NotReady(f"Only {unique_groups} detected {name} pose groups; requested {minimum}. "
                           "Repeated frames from one pose do not count as new poses.")
    return train, heldout


def rms_summary(values, np):
    a = np.asarray(values, dtype=float)
    return {"count": len(values), "mean": float(a.mean()), "median": float(np.median(a)),
            "p95": float(np.percentile(a, 95)), "max": float(a.max())}


def target_pose(row, points, K, D, cv2, np):
    ok, rvec, tvec = cv2.solvePnP(points, row["corners"], K, D, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok or not np.isfinite(rvec).all() or not np.isfinite(tvec).all():
        raise ValueError(f"{row['sample_id']}: PnP failed.")
    R = cv2.Rodrigues(rvec)[0]
    if np.any((R @ points.T + tvec)[2] <= 0):
        raise ValueError(f"{row['sample_id']}: PnP puts target points behind the camera.")
    projected = cv2.projectPoints(points, rvec, tvec, K, D)[0]
    error = float(np.sqrt(np.mean(np.sum((projected - row["corners"]) ** 2, axis=2))))
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, tvec.reshape(3)
    return T, error


def intrinsics(records, spec, out, cv2, np, *, fix_k3=False):
    train, heldout = fitting_splits(records, spec)
    points = board_points(spec, np)
    flags, flag_names = 0, []
    if fix_k3:
        if spec["image_domain"] != "received":
            raise ValueError("--fix-k3 is for the received-image Brown comparison.")
        flags, flag_names = cv2.CALIB_FIX_K3, ["CALIB_FIX_K3"]
    if spec["image_domain"] == "rectified":
        # With no USE_INTRINSIC_GUESS, fixed radial coefficients are initialized
        # to zero; ZERO_TANGENT_DIST also fixes p1,p2 at zero. No rational model
        # is enabled, so these cover all five coefficients of the selected model.
        flag_names = ["CALIB_ZERO_TANGENT_DIST", "CALIB_FIX_K1", "CALIB_FIX_K2", "CALIB_FIX_K3"]
        for name in flag_names:
            flags |= getattr(cv2, name)
    fit = cv2.calibrateCameraExtended([points.copy() for _ in train],
                                     [r["corners"] for r in train], tuple(spec["image_size"]),
                                     None, None, flags=flags)
    rms, K, D, _, _, std_intrinsics, _, per_view = fit
    if not np.isfinite(K).all() or not np.isfinite(D).all() or K[0, 0] <= 0 or K[1, 1] <= 0:
        raise ValueError("Intrinsic fit is not finite/physically usable; inspect view coverage.")
    if spec["image_domain"] == "rectified" and np.any(D != 0):
        raise ValueError("The rectified pinhole fit must keep all distortion coefficients fixed at zero.")
    heldout_errors = []
    for row in heldout:
        _, error = target_pose(row, points, K, D, cv2, np)
        heldout_errors.append({"sample_id": row["sample_id"], "reprojection_rms_px": error})
    result = {
        "status": "FIT_REQUIRES_REVIEW", "fit_performed": True,
        "intrinsics_origin": "real_checkerboard_fit", "opencv_version": cv2.__version__,
        "camera_role": spec["camera_role"], "camera_frame": spec.get("camera_frame"),
        "image_domain": spec["image_domain"], "image_domain_verified": True,
        **image_geometry_metadata(spec),
        "image_size": spec["image_size"],
        "camera_model": CAMERA_MODELS[spec["image_domain"]],
        "calibration_flags": flag_names,
        "distortion_model": "plumb_bob", "distortion_order": ["k1", "k2", "p1", "p2", "k3"],
        "K": K.tolist(), "D": D.reshape(-1).tolist(), "board": spec["board"],
        "train_sample_ids": [r["sample_id"] for r in train],
        "train_image_paths": [r["image_path"] for r in train],
        "train_pose_groups": sorted({r["pose_group"] for r in train}),
        "heldout_sample_ids": [r["sample_id"] for r in heldout],
        "train_reprojection_rms_px": float(rms),
        "train_per_view_rms_px": [{"sample_id": r["sample_id"], "reprojection_rms_px": float(e)}
                                  for r, e in zip(train, per_view.reshape(-1))],
        "intrinsic_parameter_standard_deviations": std_intrinsics.reshape(-1).tolist(),
        "heldout_reprojection_rms_px": rms_summary([r["reprojection_rms_px"] for r in heldout_errors], np),
        "heldout_per_view": heldout_errors,
        "detection_report": str((out / "detection.json").resolve()),
        "validation_note": "K,D fitted only on training views. Held-out PnP fits each target pose only. "
                           "These are pixel residuals, not independently measured metric accuracy. "
                           "Received-stream K,D describe the observed pixels; they do not establish ISP internals. "
                           "No driver CameraInfo was overwritten and no physical acceptance was inferred.",
    }
    write_json(out / "intrinsics.json", result)
    return result


def rigid_transform(value, name, np):
    T = np.asarray(value, dtype=float)
    if T.shape != (4, 4) or not np.isfinite(T).all() or not np.allclose(T[3], [0, 0, 0, 1], atol=1e-8):
        raise ValueError(f"{name}: expected a finite homogeneous 4x4 transform.")
    R = T[:3, :3]
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(R), 1, atol=1e-5):
        raise ValueError(f"{name}: rotation is not a proper rotation matrix.")
    return T


def inverse(T, np):
    result = np.eye(4)
    result[:3, :3] = T[:3, :3].T
    result[:3, 3] = -result[:3, :3] @ T[:3, 3]
    return result


def mean_transform(transforms, np):
    result = np.eye(4)
    U, _, Vt = np.linalg.svd(sum(T[:3, :3] for T in transforms))
    result[:3, :3] = U @ np.diag([1, 1, np.linalg.det(U @ Vt)]) @ Vt
    result[:3, 3] = np.mean([T[:3, 3] for T in transforms], axis=0)
    return result


def handeye(records, spec, intrinsics_path, method, out, cv2, np):
    if spec.get("installation_verified") is not True:
        raise NotReady("Physically verify the current camera mounting; old wrist topic names are not evidence.")
    robot = spec.get("robot", {})
    if (robot.get("pose_source_verified") is not True or not robot.get("pose_source")
            or not robot.get("base_frame") or not robot.get("gripper_frame")
            or robot.get("translation_unit") != "m" or not spec.get("camera_frame")):
        raise NotReady("Verified FK/pose source, exact frame names and metre units must be recorded.")
    mount = "gripper" if spec["mount_mode"] == "external_fixed" else "base_world"
    board = spec["board"]
    if board.get("rigid_mount_verified") is not True or board.get("mounted_rigidly_to") != mount:
        raise NotReady(f"For {spec['mount_mode']}, verify the board is rigidly fixed to {mount}.")
    if not board.get("origin_description") or not board.get("x_axis_description") or not board.get("y_axis_description"):
        raise NotReady("Describe the same physical board origin and x/y directions in all views.")
    if intrinsics_path is None or not intrinsics_path.is_file():
        raise NotReady("Fit/validate actual RGB intrinsics first; unverified H0 zero-D CameraInfo is not accepted.")
    intr = json.loads(intrinsics_path.read_text())
    if intr.get("intrinsics_origin") != "real_checkerboard_fit" or intr.get("fit_performed") is not True:
        raise ValueError("Use intrinsics.json from a real checkerboard fit; factory zero D is not presumed valid.")
    if intr.get("image_domain_verified") is not True:
        raise NotReady("The intrinsic fit must record the reviewed received/raw/rectified pixel pipeline.")
    for name in ("camera_id", "camera_role", "camera_frame", "image_size", "image_domain"):
        if intr.get(name) != spec.get(name):
            raise ValueError(f"Intrinsics {name} differs from the current capture/spec.")
    K, D = np.asarray(intr["K"], dtype=float), np.asarray(intr["D"], dtype=float)
    if K.shape != (3, 3) or D.size != 5 or not np.isfinite(K).all() or not np.isfinite(D).all():
        raise ValueError("Expected finite 3x3 K and five plumb_bob coefficients from the intrinsic fit.")
    expected_model = CAMERA_MODELS[spec["image_domain"]]
    if intr.get("camera_model") != expected_model:
        raise ValueError("The intrinsic camera model does not match the verified current stream domain.")
    if spec["image_domain"] == "rectified" and np.any(D != 0):
        raise ValueError("Rectified-stream hand-eye requires its fitted effective K with D fixed to zero.")
    train, heldout = fitting_splits(records, spec)
    # The hand-eye held-out set must not have trained the intrinsic camera model.
    if (set(r["sample_id"] for r in heldout) & set(intr.get("train_sample_ids", []))
            or set(r["image_path"] for r in heldout) & set(intr.get("train_image_paths", []))
            or set(r["pose_group"] for r in heldout) & set(intr.get("train_pose_groups", []))):
        raise ValueError("Hand-eye held-out samples/pose groups overlap intrinsic training data.")
    points, prepared = board_points(spec, np), {}
    for row in train + heldout:
        for field in ("pose_verified", "static_capture_verified", "board_orientation_verified"):
            if row.get(field) is not True:
                raise NotReady(f"{row['sample_id']}: confirm {field} from actual capture/review.")
        G = rigid_transform(row.get("T_base_gripper"), row["sample_id"] + ".T_base_gripper", np)
        C, pnp_error = target_pose(row, points, K, D, cv2, np)
        A = inverse(G, np) if spec["mount_mode"] == "external_fixed" else G
        prepared[row["sample_id"]] = (A, C, pnp_error)
    first = prepared[train[0]["sample_id"]][0]
    relative_rotations = [cv2.Rodrigues((inverse(first, np) @ prepared[r["sample_id"]][0])[:3, :3])[0].reshape(3)
                          for r in train[1:]]
    singular = np.linalg.svd(np.asarray(relative_rotations), compute_uv=False)
    if len(singular) < 2 or singular[1] < 1e-6:
        raise ValueError("Robot rotations are degenerate: at least two non-parallel rotation axes are required.")
    methods = {"park": cv2.CALIB_HAND_EYE_PARK, "tsai": cv2.CALIB_HAND_EYE_TSAI,
               "horaud": cv2.CALIB_HAND_EYE_HORAUD}
    A_train = [prepared[r["sample_id"]][0] for r in train]
    C_train = [prepared[r["sample_id"]][1] for r in train]
    R, t = cv2.calibrateHandEye([A[:3, :3] for A in A_train], [A[:3, 3:4] for A in A_train],
                              [C[:3, :3] for C in C_train], [C[:3, 3:4] for C in C_train],
                              method=methods[method])
    X = np.eye(4)
    X[:3, :3], X[:3, 3] = R, np.asarray(t).reshape(3)
    X = rigid_transform(X, "Computed hand-eye transform", np)
    fixed_train = [A @ X @ C for A, C in zip(A_train, C_train)]
    fixed_reference = mean_transform(fixed_train, np)
    residuals = []
    for row in train + heldout:
        A, C, pnp_error = prepared[row["sample_id"]]
        fixed = A @ X @ C
        delta = inverse(fixed_reference, np) @ fixed
        angle = math.degrees(math.acos(float(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1))))
        residuals.append({"sample_id": row["sample_id"], "split": row["split"],
                          "translation_error_m": float(np.linalg.norm(delta[:3, 3])),
                          "rotation_error_deg": angle, "pnp_reprojection_rms_px": pnp_error,
                          "T_camera_target": C.tolist(), "fixed_transform": fixed.tolist()})
    transform_name = "T_base_camera" if spec["mount_mode"] == "external_fixed" else "T_gripper_camera"
    fixed_name = "T_gripper_target" if spec["mount_mode"] == "external_fixed" else "T_base_target"
    summary = {}
    for split in ("train", "heldout"):
        subset = [r for r in residuals if r["split"] == split]
        summary[split] = {key: rms_summary([r[key] for r in subset], np)
                          for key in ("translation_error_m", "rotation_error_deg", "pnp_reprojection_rms_px")}
    result = {
        "status": "FIT_REQUIRES_REVIEW", "fit_performed": True,
        "mount_mode": spec["mount_mode"], "camera_role": spec["camera_role"],
        "image_domain": spec["image_domain"], "image_domain_verified": True,
        **image_geometry_metadata(spec),
        "image_size": spec["image_size"], "camera_model": expected_model,
        "camera_frame": spec["camera_frame"], "robot": robot, "board": board,
        "matrix_convention": "T_a_b maps coordinates from frame b to frame a; translations in metres",
        "method": method, "opencv_version": cv2.__version__,
        "intrinsics_path": str(intrinsics_path.resolve()), transform_name: X.tolist(),
        "fixed_reference_name": fixed_name, "fixed_reference_from_train_only": fixed_reference.tolist(),
        "train_relative_rotation_singular_values_rad": singular.tolist(),
        "train_rotation_second_to_first_ratio": float(singular[1] / singular[0]),
        "residual_summary": summary, "samples": residuals,
        "detection_report": str((out / "detection.json").resolve()),
        "validation_note": "Held-out samples are excluded from both intrinsic fitting and hand-eye fitting. "
                           "All fixed-transform residuals use a reference averaged from TRAINING views only. "
                           "Inspect pose diversity, labelled board origin, residuals and actual metric geometry. "
                           "A nonzero rotation rank alone does not establish adequate excitation. "
                           "No TF was published and no physical accuracy acceptance was inferred.",
    }
    write_json(out / "handeye.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("detect", "intrinsics", "handeye"))
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--intrinsics", type=Path)
    parser.add_argument("--method", choices=("park", "tsai", "horaud"), default="park")
    parser.add_argument("--fix-k3", action="store_true",
                        help="Jointly refit received RGB intrinsics with k3 fixed at zero (intrinsics only).")
    args = parser.parse_args()
    if args.fix_k3 and args.command != "intrinsics":
        parser.error("--fix-k3 is only valid for intrinsics")
    try:
        if args.command != "detect" and (args.out / (args.command + ".json")).exists():
            raise ValueError("A fitted calibration already exists in --out; choose a new result directory.")
        spec, records = load_spec(args.spec, fitting=args.command != "detect"), load_records(args.manifest)
        import cv2
        import numpy as np

        accepted = detect(records, spec, args.out, cv2, np)
        if args.command == "detect":
            print(json.dumps({"status": "DETECTION_ONLY", "detected_count": len(accepted),
                              "report": str((args.out / "detection.json").resolve())}))
            return 0
        if not accepted:
            raise NotReady("No specified board detected in real images; no fit was performed.")
        if args.command == "intrinsics":
            result = intrinsics(accepted, spec, args.out, cv2, np, fix_k3=args.fix_k3)
        else:
            result = handeye(accepted, spec, args.intrinsics, args.method, args.out, cv2, np)
        print(json.dumps({"status": result["status"],
                          "report": str((args.out / (args.command + ".json")).resolve())}))
        return 0
    except Exception as error:
        status = "NOT_RUN" if isinstance(error, (NotReady, ImportError)) else "ERROR"
        result = {"status": status, "fit_performed": False, "reason": str(error), "command": args.command}
        write_json(args.out / (args.command + "_status.json"), result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 2 if status == "NOT_RUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())

