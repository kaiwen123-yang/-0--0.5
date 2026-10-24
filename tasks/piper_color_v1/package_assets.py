"""Make portable asset copies without modifying the existing LIBERO benchmark."""
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
destination = HERE / "assets"
destination.mkdir(exist_ok=True)
records = []
for name in ("robot.xml", "gripper.xml"):
    root = ET.parse(PROJECT / "models/piper_h" / name)
    for mesh in root.iter("mesh"):
        source = Path(mesh.get("file"))
        target = destination / "meshes" / source.parent.parent.name / source.name
        target.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(source, target)
        mesh.set("file", str(target.relative_to(destination)))
        records.append(dict(path=str(target.relative_to(HERE)), sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    root.write(destination / name, encoding="unicode")
metadata = dict(source="https://github.com/agilexrobotics/agx_arm_urdf",
                commit="680fa925cd00db7e2628563d2edc5540963045de",
                upstream_license_file="No LICENSE file present in pinned sparse checkout; no new license assigned to vendor meshes.",
                local_conversion="models/piper_h/robot.xml and gripper.xml; only portable mesh paths changed", files=records)
(destination / "provenance.json").write_text(json.dumps(metadata, indent=2))
print(json.dumps({"meshes":len(records), "destination":str(destination)}))
