"""Versioned contact environment; original v1 defaults remain available."""
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import mujoco
import sim

VERSION = "piper_h_color_contact_v2_impratio10"


def scene_xml():
    root = ET.fromstring(sim.scene_xml())
    root.set("model", VERSION)
    option = root.find("option")
    option.set("impratio", "10")
    option.set("noslip_iterations", "0")
    assert option.get("cone") == "elliptic"
    return ET.tostring(root, encoding="unicode")


class ColorEnvV2(sim.ColorEnv):
    def __init__(self, render=False):
        xml = scene_xml()
        frozen = Path(os.environ["PIPER_COLOR_RUN"]) / "scene/scene.xml"
        if frozen.exists() and frozen.read_text() != xml:
            raise ValueError("Current scene differs from the frozen v2 XML")
        super().__init__(render=render, xml=xml)
        assert self.model.opt.impratio == 10
        assert self.model.opt.noslip_iterations == 0
        assert self.model.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC


def freeze(run):
    directory = Path(run) / "scene"
    directory.mkdir(exist_ok=False)
    xml = scene_xml()
    (directory / "scene.xml").write_text(xml)
    assets = sim.HERE / "assets"
    record = {
        "version": VERSION, "scene_sha256": hashlib.sha256(xml.encode()).hexdigest(),
        "mujoco_version": mujoco.__version__,
        "contact": {"cone": "elliptic", "impratio": 10, "noslip_iterations": 0},
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (Path(__file__), sim.HERE / "sim.py")},
        "assets_sha256": {str(p.relative_to(assets)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(assets.rglob("*")) if p.is_file()},
        "other_physics_and_success_conditions": "unchanged from v1",
        "hardware_execution": False,
    }
    (directory / "version.json").write_text(json.dumps(record, indent=2))
    return record
