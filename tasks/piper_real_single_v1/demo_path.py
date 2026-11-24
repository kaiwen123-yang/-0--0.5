"""Plan from the recorded dense samples. Preserve event indices and bound deviation."""
import csv
import json
import math

from demo_io import gap, read


from width_contract import RETREAT, TERMINAL_VERSION, require_width


def plan(path, bounds, speed_deg_s, retreat_window=None):
    teach = read(path / "run.json")
    if teach["kind"] != "teach":
        raise ValueError("Expected a taught source")
    marks = list(teach["marks"])
    if retreat_window is None:
        if not teach["complete"]:
            raise ValueError("Incomplete source trajectory")
    else:
        observed_end = read(path / "operator_retreat_end.json")
        cam = read(path / "rgb_status.json")
        if (teach["run_id"] != retreat_window["source_id"] or
                not retreat_window["operator_selected"] or teach["complete"] or
                teach.get("error") != "KeyboardInterrupt('operator interrupt')" or
                teach["interface_before"]["tx_packets"] != teach["interface_after"]["tx_packets"] or
                cam["error"] or cam["queue_drops"] or cam["received"] != cam["written"] or
                cam["boot_id"] != teach["boot_id"] or
                not marks[-1]["joint_id"] < retreat_window["end_joint_id"] <= observed_end["joint_id"]):
            raise ValueError("Selected retreat requires a traceable, receive-only operator-ended recording")
        marks.append(dict(event="end",joint_id=retreat_window["end_joint_id"]))
    return plan_samples(path, teach, marks, bounds, speed_deg_s, retreat_window)


def plan_samples(path, teach, marks, bounds, speed_deg_s, retreat_window=None):
    terminal = teach.get("terminal_kind")
    if terminal is not None:
        require_width(teach)
        if terminal != RETREAT or teach.get("terminal_version") != TERMINAL_VERSION or retreat_window:
            raise ValueError("Unknown or mixed task terminal")
        end = read(path / "task_end.json")
        if end != marks[-1] or not end.get("operator_empty_retreat"):
            raise ValueError("Missing recorded normal E at retreat")
        with (path / "rgb.csv").open() as f:
            image = next((r for r in csv.DictReader(f) if int(r["index"]) == end["image_id"]), None)
        if (not image or int(image["mono_ns"]) != end["image_ns"]
                or not 0 <= end["mono_ns"] - end["image_ns"] <= 100_000_000
                or not (path / "rgb" / f"{end['image_id']:07d}.png").is_file()):
            raise ValueError("No causal original RGB for E")
    if [m["event"] for m in marks] != ["start", "close", "open", "end"]:
        raise ValueError("Expected start, close, open, end")
    with (path / "feedback.csv").open() as f:
        rows = [(int(r["id"]), int(r["mono_ns"]), json.loads(r["values"]))
                for r in csv.DictReader(f) if r["kind"] == "arm"
                and marks[0]["joint_id"] <= int(r["id"]) <= marks[-1]["joint_id"]]
    keys = {r[0]: i for i,r in enumerate(rows)}
    locked = [keys[m["joint_id"]] for m in marks]
    if len(set(locked)) != 4 or locked != sorted(locked):
        raise ValueError("Invalid marker positions")
    for i, (_, ns, q) in enumerate(rows):
        if any(not lo <= x <= hi for x,(lo,hi) in zip(q, bounds, strict=True)):
            raise ValueError(f"Taught sample {rows[i][0]} outside limits")
        if i and (not 0 < ns-rows[i-1][1] <= 50_000_000 or gap(q, rows[i-1][2]) > 2):
            raise ValueError(f"Gap or discontinuity near taught sample {rows[i][0]}")
    if terminal == RETREAT and any((rows[k][1],rows[k][2]) != (m["mono_ns"],m["q"])
                                      for k,m in zip(locked,marks,strict=True)):
        raise ValueError("Task mark differs from recorded feedback")
    if terminal is None and retreat_window is None and gap(rows[0][2], rows[-1][2]) > .35:
        raise ValueError("End the taught path at its measured starting hold (within 0.35 deg)")
    for k in locked:
        window = [r for r in rows if abs(r[1]-rows[k][1]) <= 500_000_000]
        if window[-1][1]-window[0][1] < 480_000_000 or any(gap(r[2], rows[k][2]) > .2 for r in window):
            raise ValueError(f"Missing stationary dwell at marker {rows[k][0]}")

    boundaries = set(locked)
    for start, stop in teach.get("breaks", []):
        i,j = keys[start["joint_id"]],keys[stop["joint_id"]]
        if i >= j or any(gap(r[2],start["q"]) > .2 for r in rows[i:j+1]):
            raise ValueError("Discontinuity across taught sections")
        boundaries.update((i,j))

    # Split where linear interpolation in recorded time misses any measured joint
    # by more than 0.08 degree. Every source sample participates in this check.
    kept = set(boundaries)
    ordered = sorted(boundaries)
    todo = list(zip(ordered, ordered[1:]))
    while todo:
        a, b = todo.pop()
        if b <= a+1:
            continue
        _, ta, qa = rows[a]
        _, tb, qb = rows[b]
        worst, split = .08, None
        for k in range(a+1, b):
            frac = (rows[k][1]-ta)/(tb-ta)
            err = gap(rows[k][2], [x+(y-x)*frac for x,y in zip(qa,qb)])
            if err > worst:
                worst, split = err, k
        if split is not None:
            kept.add(split)
            todo.extend(((a, split), (split, b)))
    events = {m["joint_id"]: m["event"] for m in marks}
    points = []
    for idx in sorted(kept):
        ident, ns, q = rows[idx]
        n = 0
        if points:
            # Cubic smoothstep along each verified chord, zero speed at both ends.
            # max |ds/du|=1.5, max |d2s/du2|=6. Conservative reference limits.
            deg = gap(q, points[-1]["q"])
            duration = max((ns-points[-1]["ns"])/1e9, 1.5*deg/speed_deg_s, math.sqrt(6*deg/8))
            n = max(1, math.ceil(duration/.05))
        points.append(dict(id=ident, ns=ns, q=q, ticks=n, marker=events.get(ident)))
    if max(gap(p["q"], points[0]["q"]) for p in points) <= .5:
        raise ValueError("No substantive task path")
    return points
