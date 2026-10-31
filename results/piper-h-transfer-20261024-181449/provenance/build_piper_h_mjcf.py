"""Build workspace MJCF from the pinned official Piper H and AgileX gripper URDFs.

Run in the existing LIBERO environment. No ROS, CAN, or robot drivers are used.
URDF link transforms, inertias, meshes and joint limits are retained. Simulation
actuators, damping, contact parameters, TCP and cameras are explicit additions.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "repos/agx_arm_urdf"
OUTPUT = ROOT / "models/piper_h"


def numbers(values):
    return " ".join(f"{v:.12g}" for v in values)


def pose(origin):
    if origin is None:
        return {"pos": "0 0 0", "quat": "1 0 0 0"}
    xyz = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ")
    rpy = np.fromstring(origin.get("rpy", "0 0 0"), sep=" ")
    quat = Rotation.from_euler("xyz", rpy).as_quat()[[3, 0, 1, 2]]
    return {"pos": numbers(xyz), "quat": numbers(quat)}


def convert(urdf, root_link, model_name):
    links = {x.get("name"): x for x in urdf.findall("link")}
    children = {}
    for joint in urdf.findall("joint"):
        children.setdefault(joint.find("parent").get("link"), []).append(joint)
    model = ET.Element("mujoco", model=model_name)
    ET.SubElement(model, "compiler", angle="radian", autolimits="true")
    asset = ET.SubElement(model, "asset")
    world = ET.SubElement(model, "worldbody")
    actuator = ET.SubElement(model, "actuator")
    contact = ET.SubElement(model, "contact")
    used = []

    def add(parent, name, joint=None):
        body = ET.SubElement(parent, "body", name=name, **pose(joint.find("origin") if joint is not None else None))
        link = links[name]
        inertial = link.find("inertial")
        if inertial is not None:
            inertia = inertial.find("inertia")
            origin = pose(inertial.find("origin"))
            assert np.allclose(np.fromstring(origin["quat"], sep=" "), [1, 0, 0, 0])
            ET.SubElement(body, "inertial", pos=origin["pos"], mass=inertial.find("mass").get("value"),
                          fullinertia=" ".join(inertia.get(k) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")))
        for index, geometry in enumerate(link.findall("collision")):
            mesh = geometry.find("geometry/mesh")
            if mesh is None:
                raise ValueError(f"Unsupported source geometry: {name}")
            relative = mesh.get("filename").split("agx_arm_urdf/", 1)[1]
            path = SOURCE / relative
            assert path.is_file(), path
            used.append(path)
            mesh_name = f"{model_name}_{name}_{index}"
            ET.SubElement(asset, "mesh", name=mesh_name, file=str(path), scale=mesh.get("scale", "1 1 1"))
            # Use the official STL geometry for both rendering and convex contact.
            color = "0.08 0.1 0.13 1" if name in ("base_link", "link1", "link4", "link6", "gripper_base") else "0.7 0.73 0.77 1"
            ET.SubElement(body, "geom", name=f"{name}_visual", type="mesh", mesh=mesh_name,
                          group="1", contype="0", conaffinity="0", rgba=color, **pose(geometry.find("origin")))
            ET.SubElement(body, "geom", name=f"{name}_collision", type="mesh", mesh=mesh_name,
                          group="0", contype="1", conaffinity="1", friction="1 0.01 0.001",
                          solref="0.01 1", **pose(geometry.find("origin")))
        if joint is not None and joint.get("type") != "fixed":
            limit = joint.find("limit")
            jname = joint.get("name")
            ET.SubElement(body, "joint", name=jname, type="hinge" if joint.get("type") == "revolute" else "slide",
                          axis=joint.find("axis").get("xyz"), limited="true",
                          range=f"{limit.get('lower')} {limit.get('upper')}",
                          damping="0.2" if joint.get("type") == "revolute" else "8",
                          armature="0.02" if joint.get("type") == "revolute" else "0.01", frictionloss="0.01")
            if joint.get("type") == "revolute":
                effort=float(limit.get("effort"))
                ET.SubElement(actuator, "motor", name=f"torq_{jname}", joint=jname, gear="1", ctrllimited="true",
                              ctrlrange=numbers([-effort, effort]))
            else:
                ET.SubElement(actuator, "position", name=f"position_{jname}", joint=jname, kp="1000",
                              ctrllimited="true", ctrlrange=f"{limit.get('lower')} {limit.get('upper')}",
                              forcelimited="true", forcerange="-10 10")
        for child_joint in children.get(name, []):
            child = child_joint.find("child").get("link")
            if child == "gripper_link":
                continue  # URDF's massless mimic driver is not a physical joint.
            add(body, child, child_joint)
            ET.SubElement(contact, "exclude", body1=name, body2=child)
        return body

    add(world, root_link)
    return model, used


def write_xml(root, path):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    arm_source = SOURCE / "piper_h/urdf/piper_h_description.urdf"
    combined_source = SOURCE / "piper_h/urdf/piper_h_with_gripper_description.xacro"
    arm = ET.parse(arm_source).getroot()
    combined = ET.parse(combined_source).getroot()
    # Preserve the official flange and the 4.5 mm attachment offset.
    for element in combined:
        if element.get("name") in ("flange_link", "flange_joint"):
            arm.append(element)
    robot, arm_meshes = convert(arm, "base_link", "piper_h")
    flange = robot.find(".//body[@name='flange_link']")
    ET.SubElement(flange, "body", name="right_hand", pos="0 0 0.0045", quat="1 0 0 0")
    # Camera is a simulation mount, not a measured real camera extrinsic.
    ET.SubElement(flange, "camera", name="eye_in_hand", pos="0.065 0 0.035",
                  quat="0 0.707106781187 0.707106781187 0", fovy="75")
    camera_pos=np.array([1.25,1.4,1.9])
    target=np.array([-0.10,0,1.0])
    z=camera_pos-target; z/=np.linalg.norm(z)
    x=np.cross([0,0,1],z); x/=np.linalg.norm(x)
    y=np.cross(z,x)
    quat=Rotation.from_matrix(np.column_stack([x,y,z])).as_quat()[[3,0,1,2]]
    ET.SubElement(robot.find("worldbody"), "camera", name="panorama", pos=numbers(camera_pos),
                  quat=numbers(quat), fovy="52")
    write_xml(robot, OUTPUT / "robot.xml")

    grip_source=SOURCE / "agx_gripper/urdf/agx_gripper_description.urdf"
    gripper, grip_meshes = convert(ET.parse(grip_source).getroot(), "gripper_base", "agx_gripper")
    base = gripper.find("worldbody/body")
    ET.SubElement(base, "site", name="ft_frame", pos="0 0 0", size="0.002", rgba="0 0 0 0", group="1")
    tcp = ET.SubElement(base, "body", name="eef", pos="0 0 0.125", quat="1 0 0 0")
    for name in ("grip_site", "grip_site_cylinder", "ee", "ee_x", "ee_y", "ee_z"):
        ET.SubElement(tcp, "site", name=name, pos="0 0 0", size="0.002", rgba="0 0 0 0", group="1")
    sensors = ET.SubElement(gripper, "sensor")
    ET.SubElement(sensors, "force", name="force_ee", site="ft_frame")
    ET.SubElement(sensors, "torque", name="torque_ee", site="ft_frame")
    equality = ET.SubElement(gripper, "equality")
    ET.SubElement(equality, "joint", joint1="gripper_joint2", joint2="gripper_joint1", polycoef="0 -1 0 0 0", solref="0.005 1")
    write_xml(gripper, OUTPUT / "gripper.xml")
    sources = [arm_source, combined_source, grip_source, *arm_meshes, *grip_meshes]
    report = {
        "source_commit":"680fa925cd00db7e2628563d2edc5540963045de",
        "source_url":"https://github.com/agilexrobotics/agx_arm_urdf",
        "arm_dof":6, "physical_finger_joints":2, "gripper_command_dof":1,
        "nominal_max_opening_m":0.1, "gripper_tcp_in_base_m":[0,0,0.125],
        "retained":"official link transforms, joint axes/limits, link inertias and STL geometry",
        "simulation_additions":"motors, position actuators, damping, armature, friction, TCP and wrist camera; not identified from hardware",
        "visuals":"official STL shapes with neutral display colors; DAE materials not reproduced",
        "contacts":"MuJoCo convex hull of each official collision mesh; not calibrated real gripper contact",
        "mimic":"removed massless virtual driver; physical fingers coupled q_right=-q_left",
        "files":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }
    (OUTPUT / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"models":str(OUTPUT),"source_files":len(sources),"arm_dof":6,"max_opening_m":0.1}))


if __name__ == "__main__":
    main()
