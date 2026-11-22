"""Recompute Q12 baseline evidence from the selected b3bb539 artifacts, offline."""
import argparse
import ast
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tasks/piper_real_single_v1"))
import calibration as cal

SOURCE = "b3bb539109af287f7963fc750dc2dcb0b0549baa"
RAW_IMAGES = {
    "t01": "t01_rgb.png", "h01": "h01_rgb.png", "h02": "h02_rgb.png",
    "u06": "final_seven/u06_rgb.png", "u08": "final_seven/u08_rgb.png",
}


def read(path):
    return json.loads(path.read_text())


def sdk_mdh(path):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ROBOT_MDH_PRESET" for t in node.targets):
            return ast.literal_eval(node.value)["piper_h"]
    raise ValueError("Piper H MDH preset missing from SDK constants")


def flange(q_deg, mdh):
    T = np.eye(4)
    for q, (d, a, alpha, offset) in zip(np.deg2rad(q_deg), mdh):
        c, s = np.cos(q + offset), np.sin(q + offset)
        ca, sa = np.cos(alpha), np.sin(alpha)
        T = T @ [[c,-s,0,a], [ca*s,ca*c,-sa,-sa*d], [sa*s,sa*c,ca,ca*d], [0,0,0,1]]
    return T


def project(points, T, K, D):
    r = cv2.Rodrigues(T[:3, :3])[0]
    return cv2.projectPoints(points, r, T[:3, 3], K, D)[0].reshape(-1, 2)


def pixel_rms(observed, predicted):
    return float(np.sqrt(np.mean(np.sum((observed - predicted)**2, axis=1))))


def fixed_metrics(C, G, X, reference):
    delta = np.linalg.inv(reference) @ G @ X @ C
    return {"fixed_board_mm": float(1000 * np.linalg.norm(delta[:3, 3])),
            "fixed_board_deg": float(np.rad2deg(np.arccos(np.clip((delta[:3,:3].trace()-1)/2,-1,1))))}


def triangulate(ids, rims, cameras, K, D):
    # Four separate least-squares intersections of unit rays in base_link.
    origins = np.array([cameras[i][:3, 3] for i in ids])
    rays = []
    for i in ids:
        undistorted = cv2.undistortPoints(np.array(rims[i], dtype=float), K, D).reshape(4, 2)
        rays.append(np.column_stack([undistorted, np.ones(4)]) @ cameras[i][:3,:3].T)
    rays = np.array(rays)
    rays /= np.linalg.norm(rays, axis=2, keepdims=True)
    proj = np.eye(3) - rays[:,:,:,None] * rays[:,:,None,:]
    xyz = np.linalg.solve(proj.sum(axis=0), np.einsum("ncij,nj->ci", proj, origins)[..., None])[...,0]
    edges = np.linalg.norm(np.roll(xyz, -1, axis=0) - xyz, axis=1) * 1000
    return xyz, {"base_corners_m": xyz.tolist(), "cyclic_edges_mm": edges.tolist(),
                 "max_abs_edge_difference_mm": float(max(abs(edges - [290,230,290,230])))}


def summary(rows):
    return {k: cal.rms_summary([r[k] for r in rows], np) for k in rows[0]}


def main(session, sdk_path, out):
    f = session / "final_seven"
    val, sel, intr, hand, spec = [read(f / (k+".json")) for k in
                                  ("validation", "selection", "intrinsics", "handeye", "calibration_spec")]
    review = {r["id"]: r for r in read(session / "pose_review.json")}
    extras = {r["actual_pose"]: r for r in sel["added_observations"]}
    samples = {r["sample_id"]: r for r in hand["samples"]}
    train, formal = sel["original_train_included"], sel["original_heldout_included"]
    seven = formal + list(extras)
    ids = train + seven
    assert len(set(ids)) == 34 and set(ids) == set(samples)
    mdh = sdk_mdh(sdk_path)
    K, D, X, F = [np.asarray(val[k]) for k in ("K","D","T_flange_camera","T_base_board_train_mean")]
    points = cal.board_points(spec, np)
    candidate = {r["id"]: r for r in read(session / "candidate_result.json")["per_view"]}
    published = {r["id"]: r for r in val["per_validation_pose"]}
    original_images = dict(zip(intr["train_sample_ids"], intr["train_image_paths"]))
    rimfile = read(session / "outer_rim_cross_validation.json")
    outline = read(f / "board_outline.json")
    rims = {r["id"]: r["rim_pixels"] for r in rimfile["measurements"]}
    for r in outline["views"]:
        if r["id"] in rims:
            np.testing.assert_array_equal(rims[r["id"]], r["measured_exterior_pixels"])
        rims[r["id"]] = r["measured_exterior_pixels"]
    records, cameras, metrics, pixels = [], {}, {}, {}
    for i in ids:
        group = "train" if i in train else ("formal" if i in formal else "retrospective")
        extra = extras.get(i, {})
        s = samples[i]
        q = extra["measured_q_deg"] if extra else review[i]["q_deg"]
        G = flange(q, mdh)
        cameras[i] = G @ X
        row = {"id": i, "group": group, "q_deg": q, "G_base_flange_from_q_m": G.tolist(),
               "C_camera_board_published_m": s["T_camera_target"], "rim_px": rims[i],
               "field_train_image_path": original_images.get(i),
               "frame_index": extra["frame_index"] if extra else review[i]["rgb"],
               "image_receive_monotonic_ns": extra.get("image_receive_monotonic_ns"),
               "pose_receive_monotonic_ns": extra.get("pose_receive_monotonic_ns"),
               "boot_id": extra.get("boot_id"), "recorder_directory": extra.get("recorder_directory"),
               "joint_age_ms": extra["rgb_joint_age_ms"] if extra else review[i]["joint_age_ms"],
               "published_rgb": RAW_IMAGES.get(i), "redetected_corners_px": None}
        metrics[i] = {"pnp_rms_px": s["pnp_reprojection_rms_px"],
                      "full_chain_rms_px": published[i]["full_chain_rms_px"] if i in seven
                      else candidate[i]["fixed_board_prediction_rms_px"],
                      **fixed_metrics(np.asarray(s["T_camera_target"]), G, X, F)}
        if i in RAW_IMAGES:
            image = cv2.imread(str(session / RAW_IMAGES[i]), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            flags = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
            ok, corners = cv2.findChessboardCornersSB(gray, (11,8), flags=flags)
            if not ok or image.shape[:2] != (480,640):
                raise ValueError(f"Missing full board or wrong resolution: {i}")
            xy = corners.reshape(-1, 2)
            # All five originals show the printed lower-right origin; verify axis directions.
            if not (xy[0,0] > xy[1,0] and xy[0,1] > xy[11,1]):
                raise ValueError(f"Review physical corner order: {i}")
            if not extra:
                np.testing.assert_allclose(xy[[0,-1]], [review[i]["O"], review[i]["last"]], atol=0.3)
            C, pnp = cal.target_pose({"sample_id": i, "corners": corners}, points, K, D, cv2, np)
            chain = project(points, np.linalg.inv(cameras[i]) @ F, K, D)
            row["redetected_corners_px"] = xy.tolist()
            pixels[i] = {"pnp_rms_px": pnp, "full_chain_rms_px": pixel_rms(xy, chain),
                         **fixed_metrics(C, G, X, F)}
        records.append(row)
    out.mkdir(parents=True, exist_ok=True)
    (out/"selected_public_evidence.jsonl").write_text("".join(
        json.dumps(r, separators=(",",":"), allow_nan=False)+"\n" for r in records))
    groups = {"train": train, "formal": formal, "retrospective": list(extras), "combined_seven": seven}
    xyz, train_rim = triangulate(train, rims, cameras, K, D)
    _, seven_rim = triangulate(seven, rims, cameras, K, D)
    rim_errors = {i: pixel_rms(rims[i], project(xyz, np.linalg.inv(cameras[i]), K, D)) for i in seven}
    rim_delta = {r["id"]: rim_errors[r["id"]] - r["rms_px"] for r in outline["views"]}
    # Park replay from published PnP poses is possible even without the 27 raw corner arrays.
    gt = [flange(review[i]["q_deg"], mdh) for i in train]
    ct = [np.array(samples[i]["T_camera_target"]) for i in train]
    R,t = cv2.calibrateHandEye([g[:3,:3] for g in gt],[g[:3,3] for g in gt],
                               [c[:3,:3] for c in ct],[c[:3,3] for c in ct],method=cv2.CALIB_HAND_EYE_PARK)
    replay = np.eye(4)
    replay[:3,:3], replay[:3,3] = R, t.ravel()
    ref = cal.mean_transform([g @ replay @ c for g,c in zip(gt,ct)],np)
    result = {"source_commit": SOURCE, "opencv": cv2.__version__, "numpy": np.__version__,
              "mdh_piper_h_d_a_alpha_offset": mdh, "minimum_views": spec["minimum_views"],
              "park_from_published_C_max_abs_X_delta": float(abs(replay-X).max()),
              "max_abs_train_reference_delta": float(abs(ref-F).max()),
              "published_pixel_scalars_and_recomputed_fixed_metrics": {
                  k: summary([metrics[i] for i in rows]) for k, rows in groups.items()},
              "redetected_five_actual_images": pixels,
              "redetected_minus_original": {i: {k: v-metrics[i][k] for k,v in p.items()} for i,p in pixels.items()},
              "rim_from_published_exterior_pixels": {"train": train_rim, "combined_seven": seven_rim,
                  "per_validation_rms_px": rim_errors, "difference_from_published_rms_px": rim_delta,
                  "summary": {k: cal.rms_summary([rim_errors[i] for i in rows],np)
                              for k,rows in groups.items() if k != "train"}},
              "source_selection_added_observations": sel["added_observations"]}
    cal.write_json(out/"baseline.json",result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("field_session", type=Path)
    p.add_argument("sdk_constants", type=Path)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    main(args.field_session, args.sdk_constants, args.out)
