"""Create a passive capture setup from a verified installation and controller readback."""
import argparse
import json
import math
import os
from pathlib import Path
import tempfile

from width_contract import require_setup


def load(path):
    return json.loads(path.read_text())


def prepare(target, source):
    target, source = target.resolve(), source.resolve()
    allocation = load(target / "session.json")
    donor = load(source / "session.json")
    if (target == source or allocation["session_id"] == donor["session_id"]
            or Path(allocation["session_directory"]).resolve() != target
            or Path(donor["session_directory"]).resolve() != source):
        raise ValueError("Use distinct allocated collection sessions")
    destination = target / "setup.json"
    if destination.exists() or (target / "hold.json").exists():
        raise FileExistsError(f"Session already has a setup or an arm hold: {target}")
    setup_path = source / "setup.json"
    cfg = load(setup_path)
    require_setup(cfg)
    if cfg["session_id"] != donor["session_id"] or cfg["split"] != donor["split"]:
        raise ValueError("Source formal setup differs from its allocation")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    ifindex = int(Path("/sys/class/net/can0/ifindex").read_text())
    held = load(source / "hold.json")
    if held["boot_id"] != boot or held["ifindex"] != ifindex:
        raise ValueError("Source arm hold is from another boot or CAN interface")
    latest = None
    for path in source.glob("*/run.json"):
        run = load(path)
        if (not run.get("complete") or run.get("boot_id") != boot or run.get("session") != source.name
                or not run.get("limits")):
            continue
        # home verifies the previous interface across its readback queries;
        # other operations can legitimately replace a disconnected interface.
        current_hold_run = path.parent.name == held["run"]
        verified_home = (run["kind"] == "home"
                         and run.get("previous_hold", {}).get("ifindex") == ifindex)
        if not (current_hold_run or verified_home):
            continue
        limits = run["limits"]
        if ([m["joint"] for m in limits] != list(range(1, 7))
                or any(m.get("source") != "controller_readback" for m in limits)):
            continue
        bounds = [m["controller"] for m in limits]
        if any(not (math.isfinite(lo) and math.isfinite(hi) and lo < hi) for lo, hi in bounds):
            raise ValueError(f"Invalid controller bounds in {path}")
        received = max(m["received_unix_s"] for m in limits)
        if latest is None or received > latest[0]:
            latest = received, path, bounds
    if latest is None:
        raise ValueError("No six-joint controller readback for the current source boot and interface")
    _, path, bounds = latest
    fields = ("commissioning_only", "terminal_kind", "terminal_version", "gripper_basis",
              "installation", "measurement_file", "pad_measurements", "open_m", "close_m", "force_N")
    inherited = {key: cfg[key] for key in fields}
    inherited.update(session_id=allocation["session_id"], split=allocation["split"],
                     passive_setup=True, installation_source_file=str(setup_path),
                     bounds=bounds, bounds_run=path.parent.name, bounds_source_file=str(path),
                     bounds_boot_id=boot, bounds_ifindex=ifindex)
    require_setup(inherited)
    with tempfile.NamedTemporaryFile(mode="w", dir=target) as tmp:
        json.dump(inherited, tmp, ensure_ascii=False, indent=2, allow_nan=False)
        tmp.write("\n")
        tmp.flush()
        os.link(tmp.name, destination)
    print(f"{destination} ({allocation['split']}); controller bounds from {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_session", type=Path)
    parser.add_argument("source_session", type=Path)
    args = parser.parse_args()
    prepare(args.target_session, args.source_session)
