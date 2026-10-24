#!/usr/bin/env python3
"""Render final LIBERO comparison figures and selected paired episode videos."""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import quote


MODELS = ("pi0", "pi05")
LABELS = {"pi0": "pi0", "pi05": "pi0.5"}
COLORS = {"pi0": "#176D8D", "pi05": "#CB643C"}
SUITE_LABELS = {
    "libero_spatial": "LIBERO-Spatial",
    "libero_object": "LIBERO-Object",
    "libero_goal": "LIBERO-Goal",
    "libero_10": "LIBERO-Long (10)",
}
OUTCOMES = ("pi05_win", "pi0_win", "both_success", "both_failure")
OUTCOME_LABELS = {
    "pi05_win": "仅 π0.5 成功",
    "pi0_win": "仅 π0 成功",
    "both_success": "双方成功",
    "both_failure": "双方失败",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def valid_count(value: object) -> bool:
    return type(value) is int and value >= 0


def check_metric(row: dict, label: str) -> None:
    for key in ("episodes", "successes", "failures", "errors", "expected", "missing"):
        require(valid_count(row.get(key)), f"{label}: invalid {key}")
    n, k = row["episodes"], row["successes"]
    require(row.get("complete") is True and row["errors"] == row["missing"] == 0,
            f"{label}: only complete metrics with zero errors/missing are supported")
    require(n > 0 and n == row["expected"] and k + row["failures"] == n, f"{label}: inconsistent counts")
    rate = row.get("success_rate")
    require(type(rate) in (int, float) and math.isfinite(rate) and math.isclose(rate, k / n),
            f"{label}: inconsistent success rate")
    interval = row.get("wilson_95")
    require(isinstance(interval, list) and len(interval) == 2
            and all(type(v) in (int, float) and math.isfinite(v) for v in interval)
            and 0 <= interval[0] <= rate + 1e-12 and rate - 1e-12 <= interval[1] <= 1,
            f"{label}: invalid Wilson interval")
    z = 1.959963984540054
    denominator = 1 + z**2 / n
    center = (rate + z**2 / (2 * n)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / n + z**2 / (4 * n**2)) / denominator
    calculated = (max(0.0, center - half), min(1.0, center + half))
    require(all(math.isclose(a, b, abs_tol=1e-10) for a, b in zip(interval, calculated)),
            f"{label}: interval is not the expected 95% Wilson interval")


def read_summary(run_dir: Path) -> tuple[dict, list[str], dict[tuple[str, str], dict]]:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    require(summary.get("status") == "complete" and summary.get("complete") is True,
            "summary must have status='complete' and complete=true; unfinished/error runs cannot be plotted")
    require(summary.get("error_episodes") == [] and summary.get("missing_episodes") == [],
            "summary contains error or missing episodes")
    manifest = summary["manifest"]
    require(sorted(manifest.get("models", [])) == sorted(MODELS), "exactly pi0 and pi05 are required")
    suites = manifest.get("suites")
    require(isinstance(suites, list) and len(suites) == 4 and all(isinstance(s, str) for s in suites)
            and len(set(suites)) == 4, "exactly four distinct suites are required")
    require(type(manifest.get("trials_per_task")) is int and manifest["trials_per_task"] > 0,
            "invalid trials_per_task")
    indexed = {}
    for row in summary["per_suite"]:
        key = (row["model"], row["suite"])
        require(key not in indexed, f"duplicate suite metric: {key}")
        require(key[0] in MODELS and key[1] in suites, f"unexpected suite metric: {key}")
        check_metric(row, str(key))
        indexed[key] = row
    require(len(indexed) == 8, "missing suite metrics")
    for model in MODELS:
        overall = summary["overall"][model]
        check_metric(overall, model + " overall")
        for field in ("episodes", "successes", "failures", "expected"):
            require(overall[field] == sum(indexed[(model, s)][field] for s in suites),
                    f"{model}: overall {field} does not match suites")
        indexed[(model, "overall")] = overall
    total = sum(summary["overall"][model]["episodes"] for model in MODELS)
    require(summary.get("recorded_episodes") == summary.get("expected_episodes") == total,
            "recorded/expected episode count mismatch")
    return summary, suites, indexed


def read_episodes(run_dir: Path, summary: dict) -> list[dict]:
    rows, keys = [], set()
    for number, line in enumerate((run_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        require(row.get("model") in MODELS and row.get("suite") in summary["manifest"]["suites"],
                f"episode {number}: unexpected model/suite")
        require(type(row.get("success")) is bool and row.get("status") in ("success", "failure")
                and row["success"] == (row["status"] == "success"), f"episode {number}: invalid outcome")
        require(valid_count(row.get("task_id")) and valid_count(row.get("trial_index")),
                f"episode {number}: invalid task/trial index")
        key = tuple(row[field] for field in ("model", "suite", "task_id", "trial_index"))
        require(key not in keys, f"duplicate episode: {key}")
        keys.add(key)
        rows.append(row)
    require(len(rows) == summary["recorded_episodes"], "episode file does not match final summary count")
    for stats in summary["per_suite"]:
        selected = [r for r in rows if r["model"] == stats["model"] and r["suite"] == stats["suite"]]
        require(len(selected) == stats["episodes"] and sum(r["success"] for r in selected) == stats["successes"],
                f"episode results do not match final summary for {stats['model']}/{stats['suite']}")
    return rows


def matched(a: dict, b: dict) -> bool:
    for field in ("seed", "policy_seed", "initial_state_index"):
        if not valid_count(a.get(field)) or not valid_count(b.get(field)) or a[field] != b[field]:
            return False
    for row in (a, b):
        value = row.get("initial_state_sha256")
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            return False
    return a["initial_state_sha256"] == b["initial_state_sha256"]


def video_url(row: dict, run_dir: Path) -> str | None:
    raw = row.get("video_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    path = (path if path.is_absolute() else run_dir / path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        return None
    return quote(os.path.relpath(path, run_dir).replace(os.sep, "/"), safe="/.-_")


def select_highlights(rows: list[dict], run_dir: Path) -> tuple[list[tuple], dict]:
    pairs = {}
    for row in rows:
        key = tuple(row[field] for field in ("suite", "task_id", "trial_index"))
        pairs.setdefault(key, {})[row["model"]] = row
    selected, skipped = {}, Counter()
    for key, pair in sorted(pairs.items()):
        if set(pair) != set(MODELS):
            skipped["unpaired"] += 1
            continue
        a, b = pair["pi0"], pair["pi05"]
        if not matched(a, b):
            skipped["mismatched_or_missing_conditions"] += 1
            continue
        urls = (video_url(a, run_dir), video_url(b, run_dir))
        if not all(urls):
            skipped["missing_video"] += 1
            continue
        category = (("both_success" if a["success"] else "pi05_win") if b["success"]
                    else ("pi0_win" if a["success"] else "both_failure"))
        if category not in selected:
            selected[category] = (category, key, a, b, urls)
    return [selected[k] for k in OUTCOMES if k in selected], dict(skipped)


def highlights_html(summary: dict, selected: list[tuple], skipped: dict) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    model_labels = {"pi0": "π0", "pi05": "π0.5"}
    skipped_labels = {
        "unpaired": "缺少另一模型的记录",
        "mismatched_or_missing_conditions": "配对条件缺失或不一致",
        "missing_video": "视频缺失或为空",
    }
    skipped_text = "；".join(f"{skipped_labels.get(key, key)}：{count} 对" for key, count in sorted(skipped.items())) or "无"
    sections = []
    for category, key, a, b, urls in selected:
        videos = []
        for row, url in zip((a, b), urls):
            result = "成功" if row["success"] else "失败"
            videos.append(f"<div class='video'><h3>{model_labels[row['model']]} <span>{result}</span></h3>"
                          f"<video controls preload='metadata' playsinline src='{esc(url)}'></video>"
                          f"<p>环境步数：{row.get('steps', '—')} · "
                          f"<a href='{esc(url)}'>打开视频</a></p></div>")
        sections.append(f"<section><h2>{OUTCOME_LABELS[category]}</h2><p>{esc(key[0])} · 任务 {key[1]} · 试验 {key[2]}<br>"
                        f"{esc(a.get('task_name', ''))}</p><p class='conditions'>初始状态编号：{a['initial_state_index']} · "
                        f"环境随机种子：{a['seed']} · 策略随机种子：{a['policy_seed']}<br>"
                        f"初始状态 SHA-256：<code>{esc(a['initial_state_sha256'])}</code></p>"
                        f"<div class='pair'>{''.join(videos)}</div></section>")
    missing_categories = [OUTCOME_LABELS[k] for k in OUTCOMES if not any(pair[0] == k for pair in selected)]
    no_pairs = "<p>未找到符合条件的配对视频。</p>" if not selected else ""
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LIBERO 仿真 · 配对视频精选</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f8;color:#18323e;font:15px/1.6 system-ui,sans-serif}}
main{{max-width:1240px;padding:28px 24px 60px;margin:auto}}h1{{font-size:29px}}h2{{font-size:22px;margin:0}}h3{{font-size:18px}}p{{color:#506673}}
section{{margin:26px 0;background:white;padding:24px;border:1px solid #dce5e9;border-radius:12px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}video{{width:100%;background:#111;border-radius:6px}}h3 span{{float:right;font-size:13px;color:#506673}}
.conditions{{font-size:12px;overflow-wrap:anywhere}}a{{color:#176d8d}}.note{{border-left:4px solid #cb643c;padding-left:16px}}img{{width:100%;height:auto}}@media(max-width:760px){{.pair{{grid-template-columns:1fr}}section{{padding:16px}}}}</style>
<main><h1>LIBERO 仿真：π0 与 π0.5 对比</h1><p><a href="comparison.html">完整结果与全部视频</a> · <a href="summary.json">汇总 JSON</a> · <a href="per_suite.csv">套件结果 CSV</a> · <a href="episodes.jsonl">逐轮原始记录 JSONL</a> · <a href="comparison.svg">矢量图 SVG</a></p>
<img src="comparison.png" alt="π0 与 π0.5 成功率及描述性的 Wilson 95% 区间">
<p class="note">本页展示各类结果的示例，不代表整体分布。每类最多选取一对，按套件、任务、试验顺序选择；初始状态编号与哈希、环境随机种子、策略随机种子均须一致。视频需手动播放，两侧播放进度不自动同步。成功率比较请以完整结果为准。</p>
<p>每项任务使用 {summary['manifest']['trials_per_task']} 个初始状态；本轮属于初步小样本评测，不是论文表值复现。任务、试验与初始状态编号均从 0 开始。</p>
{no_pairs}{''.join(sections)}<p>以下类别没有符合条件的视频配对：{esc('、'.join(missing_categories) or '无')}。</p>
<p>排除的配对：{esc(skipped_text)}。</p></main></html>
"""


def render_figure(summary: dict, suites: list[str], indexed: dict, run_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 13,
        "svg.fonttype": "none", "axes.labelcolor": "#263E49", "text.color": "#263E49",
        "xtick.color": "#263E49", "ytick.color": "#526773",
    })
    fig, ax = plt.subplots(figsize=(13.6, 7.8), facecolor="white")
    fig.subplots_adjust(left=0.075, right=0.98, bottom=0.245, top=0.79)
    categories = suites + ["overall"]
    ax.axvspan(3.52, 4.52, color="#F0F4F6", zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color="#DCE5E9", linewidth=0.8)
    for model, offset in zip(MODELS, (-0.19, 0.19)):
        stats = [indexed[(model, suite)] for suite in categories]
        positions = [i + offset for i in range(5)]
        rates = [100 * row["success_rate"] for row in stats]
        low = [max(0, 100 * (row["success_rate"] - row["wilson_95"][0])) for row in stats]
        high = [max(0, 100 * (row["wilson_95"][1] - row["success_rate"])) for row in stats]
        ax.bar(positions, rates, width=0.32, color=COLORS[model], label=LABELS[model], zorder=3)
        ax.errorbar(positions, rates, yerr=[low, high], fmt="none", ecolor="#263E49",
                    elinewidth=1.25, capsize=4, capthick=1.25, zorder=4)
        for x, rate, row in zip(positions, rates, stats):
            inside = rate >= 24
            y = rate * 0.43 if inside else min(95, row["wilson_95"][1] * 100 + 3)
            ax.text(x, y, f"{rate:.1f}%\n{row['successes']}/{row['episodes']}", ha="center",
                    va="center" if inside else "bottom", fontsize=10,
                    color="white" if inside else "#263E49", fontweight="bold", linespacing=1.5, zorder=5)
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Success rate (%)", labelpad=12)
    ax.set_xlim(-0.55, 4.55)
    ax.set_xticks(range(5), [SUITE_LABELS.get(s, s) for s in suites] + ["Overall"])
    ax.tick_params(axis="both", length=0, pad=10)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#DCE5E9")
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.05), ncol=2, frameon=False, fontsize=12)
    trials = summary["manifest"]["trials_per_task"]
    counts = [summary["overall"][model]["episodes"] for model in MODELS]
    count_label = f"{counts[0]} episodes per model" if counts[0] == counts[1] else f"pi0: {counts[0]}; pi0.5: {counts[1]} episodes"
    fig.text(0.075, 0.935, "LIBERO simulation | pi0 vs pi0.5", fontsize=23, fontweight="bold")
    fig.text(0.075, 0.885, f"Pilot evaluation  /  4 suites  /  {count_label}  /  zero execution errors", fontsize=12, color="#526773")
    fig.text(0.075, 0.15, f"{trials} initial states/task. Bar labels: success rate and successful / total episodes.", fontsize=11)
    fig.text(0.075, 0.112, "Error bars: descriptive episode-level 95% Wilson CI (not task-cluster adjusted).", fontsize=11)
    fig.text(0.075, 0.074, "Repeated trials within a task may be correlated. This pilot does not reproduce the paper's reported benchmark scores.", fontsize=10, color="#526773")
    try:
        for extension in ("png", "svg"):
            target = run_dir / f"comparison.{extension}"
            temporary = target.with_name(f"comparison.tmp.{os.getpid()}.{extension}")
            fig.savefig(temporary, format=extension, dpi=200, facecolor="white",
                        metadata={"Creator" if extension == "svg" else "Software": "LIBERO comparison reporting script"})
            temporary.replace(target)
    finally:
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        summary, suites, indexed = read_summary(run_dir)
        rows = read_episodes(run_dir, summary)
        selected, skipped = select_highlights(rows, run_dir)
        page = highlights_html(summary, selected, skipped)
        render_figure(summary, suites, indexed, run_dir)
        target = run_dir / "highlights.html"
        temporary = target.with_name(f"highlights.tmp.{os.getpid()}.html")
        temporary.write_text(page, encoding="utf-8")
        temporary.replace(target)
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        parser.exit(2, f"Cannot plot comparison: {exc}\n")
    print(json.dumps({"figures": [str(run_dir / "comparison.png"), str(run_dir / "comparison.svg")],
                      "highlights": str(run_dir / "highlights.html"), "highlight_pairs": len(selected),
                      "excluded_pairs": skipped}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
