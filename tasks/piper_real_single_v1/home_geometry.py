"""Read-only swept-path check for the fixed Piper H table setup. Run with system VTK."""
import itertools
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
import vtk
from vtk.util.numpy_support import vtk_to_numpy


REPO = Path(__file__).resolve().parents[2]
RESEARCH = Path("/home/kaiwen/research")
MODEL = RESEARCH / "OSCBF-research/models/piper_h_with_gripper.urdf"
MESH_ROOT = RESEARCH / "OSCBF-research/ros_ws/src/agx_arm_ros/src/agx_arm_description"
AUDIT = REPO / "results/calibration-audit/20261122"
sys.path.insert(0, str(AUDIT))
from field_evidence import flange, sdk_mdh


def origin(node):
    pose = np.eye(4)
    element = node.find("origin")
    if element is not None:
        pose[:3, 3] = np.fromstring(element.get("xyz", "0 0 0"), sep=" ")
        angles = np.fromstring(element.get("rpy", "0 0 0"), sep=" ")
        pose[:3, :3] = Rotation.from_euler("xyz", angles).as_matrix()
    return pose


def segment(start, end):
    count = max(1, math.ceil(np.abs(np.degrees(end - start)).max() / .25))
    return np.linspace(start, end, count + 1)


def joint_vector(values):
    q = np.asarray(values)
    if q.shape != (6,) or q.dtype.kind not in "fiu" or not np.isfinite(q).all():
        raise ValueError("Expected six finite joint coordinates")
    return q


def separating_axis(a, b, previous_axis, margin):
    """A positive projected gap separates every point of both triangle meshes.

    Search directions using support points of their convex hulls. Failure to
    find a plane, including overlapping hulls, always falls through to VTK.
    """
    axis = a.mean(axis=0) - b.mean(axis=0) if previous_axis is None else previous_axis
    for _ in range(16):
        length = np.linalg.norm(axis)
        if length < 1e-12:
            break
        nearest = a[np.argmin(a @ axis)] - b[np.argmax(b @ axis)]
        if nearest @ axis > (margin + 1e-9) * length:
            return axis
        # Move the direction toward the closest point on [axis, nearest].
        delta = nearest - axis
        squared = delta @ delta
        if squared < 1e-24:
            break
        step = min(1., -(axis @ delta) / squared)
        if step <= 0:
            break
        axis = axis + step * delta
    return None


def check_route(request):
    tree = ET.parse(MODEL)
    joints = []
    for joint in tree.findall("joint"):
        axis = joint.find("axis")
        vector = None if axis is None else np.fromstring(axis.get("xyz"), sep=" ")
        joints.append((joint.get("name"), joint.get("type"), joint.find("parent").get("link"),
                       joint.find("child").get("link"), origin(joint), vector))

    width = request["sdk_width_m"]
    if type(width) not in (int, float) or not 0 <= width <= .1:
        raise ValueError("Invalid SDK opening")
    if type(request["ctrl_mode"]) is not int or request["ctrl_mode"] not in (0, 1, 2):
        raise ValueError("Invalid starting control mode")
    openings = {"gripper": width, "gripper_joint1": width / 2, "gripper_joint2": -width / 2}
    def transforms(q):
        frames = {"world": np.eye(4)}
        for name, kind, parent, child, offset, axis in joints:
            motion = np.eye(4)
            if kind == "revolute":
                motion[:3, :3] = Rotation.from_rotvec(axis * q[int(name[-1]) - 1]).as_matrix()
            elif kind == "prismatic":
                motion[:3, 3] = axis * openings[name]
            frames[child] = frames[parent] @ offset @ motion
        return frames

    meshes, hulls, offsets = {}, {}, {}
    for link in tree.findall("link"):
        mesh = link.find("collision/geometry/mesh")
        if mesh is None:
            continue
        name = link.get("name")
        path = MESH_ROOT / mesh.get("filename").split("package://agx_arm_description/")[1]
        reader = vtk.vtkSTLReader()
        reader.SetFileName(str(path))
        reader.Update()
        meshes[name] = reader.GetOutput()
        points = vtk_to_numpy(meshes[name].GetPoints().GetData())
        hulls[name] = points[ConvexHull(points).vertices].astype(float)
        offsets[name] = origin(link.find("collision"))

    def link_order(name):
        if name == "base_link":
            return 0
        return int(name[-1]) if name.startswith("link") else 7

    filters = {}
    for a, b in itertools.combinations(meshes, 2):
        if abs(link_order(a) - link_order(b)) > 1:
            test = vtk.vtkCollisionDetectionFilter()
            test.SetInputData(0, meshes[a])
            test.SetInputData(1, meshes[b])
            test.SetCollisionModeToFirstContact()
            filters[a, b] = test

    def boxes(frames):
        bounds, matrices, world_hulls = {}, {}, {}
        for name, points in hulls.items():
            tf = frames[name] @ offsets[name]
            xyz = points @ tf[:3, :3].T + tf[:3, 3]
            world_hulls[name] = xyz
            bounds[name] = xyz.min(axis=0), xyz.max(axis=0)
            matrix = vtk.vtkMatrix4x4()
            matrix.DeepCopy(tf.ravel().tolist())
            matrices[name] = matrix
        return bounds, matrices, world_hulls

    def gripper_z(bounds):
        return float(np.min([bounds[name][0][2] for name in ("gripper_base", "gripper_link1", "gripper_link2")]))

    a01 = json.loads((REPO / "results/pi-readiness/20261123/local_commissioning/A01_selected_retreat.json").read_text())
    pick = next(m["q"] for m in a01["marks"] if m["event"] == "close")
    references = [pick]
    if request.get("pick_q_rad") is not None:
        references.append(request["pick_q_rad"])
    pick_z = float(np.max([gripper_z(boxes(transforms(joint_vector(q)))[0]) for q in references]))
    if not math.isfinite(pick_z):
        raise ValueError("Invalid pick-height reference")
    mount = json.loads((AUDIT/"ssh_multiview/wrist_rgb_calibration.json").read_text())
    camera = np.asarray(mount["T_flange_camera"])
    mdh = sdk_mdh(RESEARCH/"OSCBF-research/src/pyAgxArm/pyAgxArm/api/constants.py")
    start = joint_vector(request["start_q_rad"])
    first = joint_vector(request["first_target_rad"])
    goal = joint_vector(request.get("goal_q_rad", np.zeros(6)))
    held = joint_vector(request["previous_target_rad"])
    paths = {"commanded": np.concatenate([segment(start, first), segment(first, goal)])}
    # The previous CAN target can be present briefly during the control-source change.
    if request["ctrl_mode"] != 1:
        paths["previous_target"] = segment(start, held)
    hits = set()
    min_z = min_camera_z = math.inf
    fk_error = 0.
    heights = {}
    previous_axes = {}
    for q in np.concatenate(list(paths.values())):
        key = tuple(q)
        if key in heights:
            continue
        frames = transforms(q)
        tf = frames["flange_link"]
        fk = np.abs(tf - flange(np.degrees(q), mdh)).max()
        camera_z = (tf @ camera)[2, 3]
        if not np.isfinite([fk, camera_z]).all():
            raise ValueError("Nonfinite forward kinematics")
        fk_error = max(fk_error, fk)
        min_camera_z = min(min_camera_z, camera_z)
        bounds, matrices, world_hulls = boxes(frames)
        if not np.isfinite(list(bounds.values())).all():
            raise ValueError("Nonfinite collision geometry")
        z = gripper_z(bounds)
        min_z = min(min_z, z)
        heights[key] = z - pick_z
        for (a, b), test in filters.items():
            lo, hi = bounds[a]
            other_lo, other_hi = bounds[b]
            if (hi < other_lo).any() or (other_hi < lo).any():
                continue
            axis = separating_axis(world_hulls[a], world_hulls[b], previous_axes.get((a, b)),
                                   test.GetBoxTolerance())
            if axis is not None:
                previous_axes[a, b] = axis
                continue
            test.SetMatrix(0, matrices[a])
            test.SetMatrix(1, matrices[b])
            test.Update()
            if test.GetNumberOfContacts():
                hits.add((a, b))
    # Retain the ordered clearance evidence for each possible complete motion.
    # A stationary segment or the common endpoint of two segments counts once.
    profiles = {}
    for name, path in paths.items():
        distinct = np.r_[True, np.any(np.diff(path, axis=0) != 0, axis=1)]
        profiles[name] = [heights[tuple(q)] for q in path[distinct]]
    return dict(samples=len(heights), mesh_pairs=len(filters), intersections=sorted(hits),
                clearance_profiles_m=profiles,
                pick_reference_base_z_m=pick_z, gripper_min_base_z_m=min_z,
                clearance_above_pick_m=min_z-pick_z, camera_center_min_base_z_m=min_camera_z,
                max_fk_difference=fk_error, **request)


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    result = check_route(json.loads((directory / "home_request.json").read_text()))
    (directory / "route_check.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
