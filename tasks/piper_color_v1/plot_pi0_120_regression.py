"""Source-backed trajectory figures; PNG QA precedes optional vector export."""
import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "outputs/pi0-120-demo-v2-20261101"
OUT = ROOT / "outputs/pi0-120-regression-diagnosis-20261101"
sys.path.insert(0, str(ROOT / "runtime/pi0-analysis-tools"))
from visual_qa import audit_layout

COLORS = ("red", "green", "blue")
STYLE = {"old": ("#0072B2", "-"), "new2010": ("#CC79A7", ":"),
         "new4020": ("#E69F00", "-."), "new8040": ("#D55E00", "--"), "teacher": ("#333333", "-")}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                    "axes.spines.right": False, "pdf.fonttype": 42, "svg.fonttype": "none"})


def finish(fig, name, vector, qa):
    path = OUT / "figures"
    path.mkdir(exist_ok=True)
    fig.savefig(path / f"{name}.png", dpi=300)
    qa[name] = audit_layout(fig)
    if vector:
        fig.savefig(path / f"{name}.svg")
        fig.savefig(path / f"{name}.pdf")
    plt.close(fig)


def load_case(label, layout, color, seed):
    group = f"baseline_old2010_v2_validation_seed{seed}" if label == "old" else f"update_{label[3:]}_validation_seed{seed}"
    with np.load(RUN / "evaluations" / group / f"layout_{layout:05d}_{color}.npz", allow_pickle=False) as x:
        return {k: x[k] for k in x.files}


def case_figure(layout, color, seed, vector, qa):
    ds = {label: load_case(label, layout, color, seed) for label in ("old", "new2010", "new4020", "new8040")}
    with np.load(OUT / "teacher_reference" / f"trace_{layout}_{color}.npz", allow_pickle=False) as x:
        teacher = {k: x[k] for k in x.files}
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.4), layout="constrained")
    ax = axes[0, 0]
    objects = ds["old"]["object_positions"][0]
    for i, name in enumerate(COLORS):
        ax.scatter(*objects[i, :2] * 1000, s=130, marker="s", color={"red":"#D55E00","green":"#009E73","blue":"#0072B2"}[name], alpha=.5)
        ax.annotate(name + (" (target)" if name == color else ""), objects[i, :2] * 1000, xytext=(4, 7), textcoords="offset points", fontsize=9)
    for label in ("old", "new8040"):
        d = ds[label]
        close = int(np.flatnonzero(d["executed_command"][:, 6] < .06)[0])
        ax.plot(*d["tcp"][:close + 1, :2].T * 1000, color=STYLE[label][0], ls=STYLE[label][1], lw=1.7, label=label)
        ax.scatter(*d["tcp"][close, :2] * 1000, marker="x", s=55, color=STYLE[label][0])
    ax.plot(*teacher["tcp"][:73, :2].T * 1000, color=STYLE["teacher"][0], lw=1, alpha=.7, label="teacher")
    ax.set(xlabel="TCP x (mm)", ylabel="TCP y (mm)", title="a  Approach until first close (<60 mm)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(loc="lower left", fontsize=8)
    ax = axes[0, 1]
    for label, d in ds.items():
        err = np.linalg.norm(d["tcp"][:, :2] - d["diagnostic_target_position"][:, :2], axis=1) * 1000
        ax.plot(np.arange(len(err)) / 20, err, color=STYLE[label][0], ls=STYLE[label][1], label=label)
    err = np.linalg.norm(teacher["tcp"][:, :2] - teacher["target_position"][:, :2], axis=1) * 1000
    ax.plot(np.arange(len(err)) / 20, err, color="#333333", lw=1, label="teacher")
    ax.set(xlim=(0, 7), ylim=(0, None), xlabel="Simulation time (s)", ylabel="Target XY offset (mm)", title="b  Target alignment during approach/grasp")
    ax.legend(fontsize=8, ncol=2, loc="upper left")
    ax = axes[1, 0]
    for label in ("old", "new8040"):
        d = ds[label]
        ax.plot(np.arange(len(d["state"])) / 20, d["state"][:, 6] * 1000,
                color=STYLE[label][0], ls=STYLE[label][1], label=label + " measured")
    ax.plot(np.arange(len(teacher["state"])) / 20, teacher["state"][:, 6] * 1000, color="#333333", lw=1, label="teacher measured")
    ax.set(xlim=(0, 7), ylim=(0, 110), xlabel="Simulation time (s)", ylabel="Measured gripper opening (mm)", title="c  Closing the gripper does not identify the object")
    ax.legend(fontsize=8, loc="lower left")
    ax = axes[1, 1]
    for i, name in enumerate(COLORS):
        d = ds["new8040"]
        heights = (d["object_positions"][:, i, 2] - d["object_positions"][0, i, 2]) * 1000
        ax.plot(np.arange(len(heights)) / 20, heights, label="new8040 " + name,
                color=("#D55E00", "#009E73", "#56B4E9")[i], ls=("--", "-.", ":")[i])
    d = ds["old"]; i = COLORS.index(color)
    ax.plot(np.arange(len(d["state"])) / 20, (d["object_positions"][:, i, 2] - d["object_positions"][0, i, 2]) * 1000,
            color=STYLE["old"][0], label="old target", lw=1.7)
    ax.axhline(50, color="0.6", lw=.7, ls=":")
    ax.set(ylim=(-5, None), xlabel="Simulation time (s)", ylabel="Object rise from initial position (mm)", title="d  Which object was actually lifted?")
    ax.legend(fontsize=8, loc="upper right")
    fig.suptitle(f"Paired validation: layout {layout}, target {color}, seed {seed}", fontsize=13)
    finish(fig, f"case_{layout}_{color}_seed{seed}", vector, qa)


def overview(vector, qa):
    rows = json.loads((OUT / "trajectory_metrics.json").read_text())
    pairs = json.loads((OUT / "paired_validation.json").read_text())
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.3), layout="constrained")
    ax = axes[0]
    for p in pairs:
        lost = p["old_success"] and not p["new_success"]
        ax.scatter(p["old_close_target_mm"], p["new_close_target_mm"], color="#D55E00" if lost else "#0072B2", marker="x" if lost else "o", s=35)
    ax.plot([0, 230], [0, 230], color="0.65", ls="--", lw=1)
    ax.set(xlim=(0, 230), ylim=(0, 230), xlabel="Old: target offset at close (mm)", ylabel="New8040: target offset at close (mm)",
           title="a  Same-layout paired targeting error")
    ax.text(.98, .03, "Orange x: old success -> new failure\n30 trials / 5 layouts / 2 seeds", transform=ax.transAxes, ha="right", va="bottom", fontsize=8)
    ax = axes[1]
    groups = ("baseline", "update_2010", "update_4020", "update_8040")
    labels = ("old", "2010", "4020", "8040")
    data = [[r["close_target_xy_mm"] for r in rows if r["split"] == "validation" and r["evaluation"].startswith(g)] for g in groups]
    ax.boxplot(data, tick_labels=labels, showfliers=False, widths=.45, medianprops={"color":"black"})
    for i, values in enumerate(data):
        jitter = np.linspace(-.14, .14, len(values))
        ax.scatter(i + 1 + jitter, values, s=12, color=("#0072B2", "#CC79A7", "#E69F00", "#D55E00")[i], alpha=.7)
    ax.set(ylabel="Target XY offset at first close (mm)", xlabel="Model / optimizer updates", title="b  All validation trials, both seeds", ylim=(0, None))
    ax = axes[2]
    for i, field in enumerate(("target_lifted_5cm", "non_target_lifted_5cm", "success")):
        counts = [sum(r[field] for r in rows if r["split"] == "validation" and r["evaluation"].startswith(g)) for g in groups]
        ax.bar(np.arange(4) + (i - 1) * .24, counts, width=.23, label=("Target lifted", "Wrong object lifted", "Full success")[i],
               color=("#0072B2", "#D55E00", "#009E73")[i], hatch=("", "//", "..")[i])
    ax.set(xticks=np.arange(4), xticklabels=labels, ylim=(0, 30), ylabel="Count out of 30 trials", xlabel="Model / optimizer updates", title="c  Grasp identity and complete success")
    ax.legend(fontsize=8)
    finish(fig, "targeting_overview", vector, qa)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--vector", action="store_true")
    args = parser.parse_args(); qa = {}
    overview(args.vector, qa)
    for case in ((1000, "red", 42), (1001, "blue", 42), (1003, "red", 42)):
        case_figure(*case, args.vector, qa)
    (OUT / "figure_layout_checks.json").write_text(json.dumps(qa, indent=2, default=str))
    print(json.dumps(qa, default=str))
