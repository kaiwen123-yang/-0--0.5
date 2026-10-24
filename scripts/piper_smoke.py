"""Import-only Piper H SDK check; never creates or connects a robot."""

from datetime import datetime
from importlib import metadata
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import can
import pyAgxArm
from pyAgxArm import ArmModel


root = Path(__file__).resolve().parents[1]
expected_python = Path("/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python")
sdk_file = Path(pyAgxArm.__file__).resolve()
assert Path(sys.executable) == expected_python, sys.executable
assert sdk_file.is_relative_to(root / "envs" / "piper"), sdk_file
assert ArmModel.PIPER_H == "piper_h", ArmModel.PIPER_H

result = {
    "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    "status": "passed",
    "scope": "imports_and_piper_h_model_constant_only",
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "sdk_path": str(sdk_file),
    "sdk_version": metadata.version("pyAgxArm"),
    "python_can_version": can.__version__,
    "arm_model": ArmModel.PIPER_H,
    "hardware_connected": False,
    "can_interface_changed": False,
    "robot_instance_created": False,
    "ros_build_status": "pending_separate_ros_python_compatibility_validation",
}
output = root / "results" / "piper_smoke.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
