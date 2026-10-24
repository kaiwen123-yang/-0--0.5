#!/usr/bin/env python3
"""Summarize paired LIBERO episodes without ML dependencies or GPU access."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import html
import io
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo


Z_95 = 1.959963984540054
LABELS = {"pi0": "π0", "pi05": "π0.5"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def unique_list(value: Any, label: str, item_type: type) -> list:
    require(isinstance(value, list) and bool(value), f"{label} must be a nonempty list")
    require(all(type(x) is item_type for x in value), f"{label} contains invalid values")
    require(len(value) == len(set(value)), f"{label} contains duplicates")
    return value


def wilson(successes: int, total: int) -> list[float] | None:
    """Two-sided 95% Wilson score interval, returned as fractions."""
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + Z_95**2 / total
    center = (p + Z_95**2 / (2 * total)) / denominator
    margin = Z_95 * math.sqrt(p * (1 - p) / total + Z_95**2 / (4 * total**2)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def metric(rows: list[dict], expected: int) -> dict:
    successes = sum(row["success"] for row in rows)
    errors = sum(row["status"] == "error" for row in rows)
    total = len(rows)
    return {
        "expected": expected,
        "episodes": total,
        "missing": expected - total,
        "successes": successes,
        "failures": total - successes - errors,
        "errors": errors,
        "success_rate": successes / total if total else None,
        "wilson_95": wilson(successes, total),
        "elapsed_seconds": sum(row["elapsed_seconds"] for row in rows),
        "complete": total == expected,
    }


def read_run(run_dir: Path) -> tuple[dict, list[dict], dict[str, list[int]], set[tuple]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    models = unique_list(manifest.get("models"), "manifest.models", str)
    suites = unique_list(manifest.get("suites"), "manifest.suites", str)
    trials = manifest.get("trials_per_task")
    require(integer(trials) and trials > 0, "manifest.trials_per_task must be positive integer")
    ids_spec = manifest.get("task_ids", list(range(10)))
    if isinstance(ids_spec, dict):
        require(set(ids_spec) == set(suites), "manifest.task_ids keys must exactly match suites")
        task_ids = {suite: unique_list(ids_spec[suite], f"task_ids.{suite}", int) for suite in suites}
    else:
        ids = unique_list(ids_spec, "manifest.task_ids", int)
        task_ids = {suite: ids for suite in suites}
    require(all(i >= 0 for ids in task_ids.values() for i in ids), "task_ids must be nonnegative")
    expected = {(m, s, i, t) for m in models for s in suites for i in task_ids[s] for t in range(trials)}
    rows = []
    seen = set()
    episodes_path = run_dir / "episodes.jsonl"
    lines = episodes_path.read_text(encoding="utf-8").splitlines() if episodes_path.exists() else []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        row = json.loads(line)
        prefix = f"episodes.jsonl line {line_number}"
        require(isinstance(row, dict), f"{prefix}: must be an object")
        for field in ("model", "suite", "task_name"):
            require(isinstance(row.get(field), str), f"{prefix}: invalid {field}")
        for field in ("task_id", "trial_index", "initial_state_index", "seed", "steps", "video_frames"):
            require(integer(row.get(field)) and row[field] >= 0, f"{prefix}: invalid {field}")
        require(type(row.get("success")) is bool, f"{prefix}: success must be boolean")
        require(row.get("status") in ("success", "failure", "error"), f"{prefix}: invalid status")
        require(row["success"] == (row["status"] == "success"), f"{prefix}: success/status disagree")
        elapsed = row.get("elapsed_seconds")
        require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
                f"{prefix}: invalid elapsed_seconds")
        require(row.get("video_path") is None or isinstance(row["video_path"], str), f"{prefix}: invalid video_path")
        require(row.get("error") is None or isinstance(row["error"], str), f"{prefix}: invalid error")
        key = (row["model"], row["suite"], row["task_id"], row["trial_index"])
        require(key not in seen, f"{prefix}: duplicate episode {key}; refusing to choose a result")
        require(key in expected, f"{prefix}: unexpected episode {key} outside manifest")
        seen.add(key)
        rows.append(row)
    return manifest, rows, task_ids, expected - seen


def paired(rows: list[dict], expected: int) -> dict:
    indexed: dict[tuple, dict[str, dict]] = {}
    for row in rows:
        if row["model"] in ("pi0", "pi05"):
            key = (row["suite"], row["task_id"], row["trial_index"])
            indexed.setdefault(key, {})[row["model"]] = row
    result = {
        "expected_pairs": expected, "paired_episodes": 0, "missing_pairs": 0,
        "mismatched_pairs": [], "pi05_wins": 0, "pi05_losses": 0,
        "both_success": 0, "both_failure": 0, "pairs_with_errors": 0,
    }
    present_pairs = 0
    for key, models in sorted(indexed.items()):
        if not {"pi0", "pi05"} <= models.keys():
            continue
        present_pairs += 1
        a, b = models["pi0"], models["pi05"]
        matching_fields = ("seed", "initial_state_index", "initial_state_sha256", "policy_seed")
        if any(a.get(field) != b.get(field) for field in matching_fields):
            result["mismatched_pairs"].append({
                "suite": key[0], "task_id": key[1], "trial_index": key[2],
                "pi0": {field: a.get(field) for field in matching_fields},
                "pi05": {field: b.get(field) for field in matching_fields},
            })
            continue
        result["paired_episodes"] += 1
        result["pairs_with_errors"] += a["status"] == "error" or b["status"] == "error"
        outcome = (("both_success" if a["success"] else "pi05_wins") if b["success"]
                   else ("pi05_losses" if a["success"] else "both_failure"))
        result[outcome] += 1
    result["missing_pairs"] = expected - present_pairs
    total = result["paired_episodes"]
    result["pi05_minus_pi0_percentage_points"] = (
        100 * (result["pi05_wins"] - result["pi05_losses"]) / total if total else None
    )
    result["complete"] = total == expected
    return result


def build_summary(manifest: dict, rows: list[dict], task_ids: dict, missing: set[tuple]) -> dict:
    trials = manifest["trials_per_task"]
    expected_per_model = sum(map(len, task_ids.values())) * trials
    overall = {m: metric([r for r in rows if r["model"] == m], expected_per_model) for m in manifest["models"]}
    per_suite, per_task = [], []
    for suite in manifest["suites"]:
        for model in manifest["models"]:
            selected = [r for r in rows if r["model"] == model and r["suite"] == suite]
            per_suite.append({"model": model, "suite": suite, **metric(selected, len(task_ids[suite]) * trials)})
            for task_id in task_ids[suite]:
                task_rows = [r for r in selected if r["task_id"] == task_id]
                names = sorted({r["task_name"] for r in task_rows})
                per_task.append({"model": model, "suite": suite, "task_id": task_id,
                                 "task_name": " / ".join(names), **metric(task_rows, trials)})
    comparison = None
    if {"pi0", "pi05"} <= overall.keys():
        comparison = {
            "overall": paired(rows, expected_per_model),
            "per_suite": {
                s: paired([r for r in rows if r["suite"] == s], len(task_ids[s]) * trials)
                for s in manifest["suites"]
            },
        }
    errors = [r for r in rows if r["status"] == "error"]
    complete = not missing
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "incomplete" if missing else ("complete_with_errors" if errors else "complete"),
        "complete": complete,
        "manifest": manifest,
        "expected_episodes": expected_per_model * len(manifest["models"]),
        "recorded_episodes": len(rows),
        "missing_episodes": [dict(zip(("model", "suite", "task_id", "trial_index"), key)) for key in sorted(missing)],
        "error_episodes": errors,
        "overall": overall, "per_suite": per_suite, "per_task": per_task,
        "paired_comparison": comparison,
        "method": {
            "rate_denominator": "Recorded episodes, including error episodes as unsuccessful; missing episodes are excluded and explicitly reported.",
            "interval": "Two-sided Wilson score 95% interval with z=1.959963984540054; descriptive episode-level binomial interval, not a task-cluster-adjusted interval.",
            "paired_difference": "100*(pi05_wins-pi05_losses)/matched_pairs; equal suite, task_id, trial_index, environment seed, initial state index/hash and policy seed are required. Error episodes count as unsuccessful.",
            "scope": "Results apply to this manifest and checkpoints; this report does not establish paper benchmark replication or statistical superiority.",
        },
    }


def csv_text(rows: list[dict], leading: list[str]) -> str:
    stream = io.StringIO(newline="")
    fields = leading + ["expected", "episodes", "missing", "successes", "failures", "errors",
                        "success_rate", "wilson_95_lower", "wilson_95_upper", "elapsed_seconds", "complete"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        item = dict(row)
        interval = item.pop("wilson_95")
        item["wilson_95_lower"], item["wilson_95_upper"] = interval if interval else (None, None)
        writer.writerow(item)
    return stream.getvalue()


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def display_metric(row: dict) -> str:
    interval = row["wilson_95"]
    ci = "—" if interval is None else f"{pct(interval[0])}–{pct(interval[1])}"
    return (f"<td>{row['successes']} / {row['episodes']}</td><td>{pct(row['success_rate'])}</td>"
            f"<td>{ci}</td><td>{row['errors']}</td><td>{row['missing']}</td>")


def render_html(summary: dict, rows: list[dict], run_dir: Path) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    complete = summary["complete"]
    status = ("评测已完成（包含运行错误）" if summary["error_episodes"] else "评测已完成") if complete else "评测未完成 · 当前为阶段结果"
    trials = summary["manifest"]["trials_per_task"]
    scope_note = (f"本轮每项任务 {trials} 次试验，属于初轮小样本对比（pilot）；官方默认每任务 50 次。"
                  if trials < 50 else f"本轮每项任务 {trials} 次试验。")
    cards = []
    for model, stats in summary["overall"].items():
        cards.append(f"<section class='card'><div>{esc(LABELS.get(model, model))}</div><strong>{pct(stats['success_rate'])}</strong>"
                     f"<p>成功 {stats['successes']} / 已记录 {stats['episodes']}<br>计划 {stats['expected']} · 缺测 {stats['missing']} · 错误 {stats['errors']}</p></section>")
    header = "<th>成功 / 已记录</th><th>成功率</th><th>Wilson 95% 区间</th><th>错误</th><th>缺测</th>"
    suite_rows = "".join(f"<tr><td>{esc(r['suite'])}</td><td>{esc(LABELS.get(r['model'], r['model']))}</td>{display_metric(r)}</tr>" for r in summary["per_suite"])
    task_rows = "".join(f"<tr><td>{esc(r['suite'])} / {r['task_id']}</td><td>{esc(r['task_name'])}</td><td>{esc(LABELS.get(r['model'], r['model']))}</td>{display_metric(r)}</tr>" for r in summary["per_task"])
    comparison_rows = []
    comparison = summary["paired_comparison"]
    if comparison:
        for label, stats in [("全部", comparison["overall"]), *comparison["per_suite"].items()]:
            delta = stats["pi05_minus_pi0_percentage_points"]
            delta_text = "—" if delta is None else f"{delta:+.1f} 个百分点"
            comparison_rows.append(f"<tr><td>{esc(label)}</td><td>{stats['paired_episodes']} / {stats['expected_pairs']}</td>"
                                   f"<td>{stats['pi05_wins']}</td><td>{stats['pi05_losses']}</td><td>{stats['both_success']}</td>"
                                   f"<td>{stats['both_failure']}</td><td>{stats['pairs_with_errors']}</td><td>{esc(delta_text)}</td>"
                                   f"<td>{stats['missing_pairs']} / {len(stats['mismatched_pairs'])}</td></tr>")
    video_rows, missing_videos = [], 0
    for row in sorted(rows, key=lambda r: (r["suite"], r["task_id"], r["trial_index"], r["model"])):
        raw_path = row.get("video_path")
        video_link = "无视频"
        if raw_path:
            path = Path(raw_path)
            path = path if path.is_absolute() else run_dir / path
            if path.is_file():
                url = quote(os.path.relpath(path, run_dir).replace(os.sep, "/"), safe="/.-_")
                video_link = f"<a href='{esc(url)}'>查看视频 ({row['video_frames']} 帧)</a>"
            else:
                missing_videos += 1
                video_link = f"<span class='warning'>视频文件缺失</span> ({esc(raw_path)})"
        state = {"success": "成功", "failure": "失败", "error": "运行错误"}[row["status"]]
        video_rows.append(f"<tr><td>{esc(LABELS.get(row['model'], row['model']))}</td><td>{esc(row['suite'])} / {row['task_id']}</td>"
                          f"<td>{esc(row['task_name'])}</td><td>{row['trial_index']}</td><td>{row['initial_state_index']}</td>"
                          f"<td>{row['seed']}</td><td>{state}</td><td>{row['steps']}</td><td>{row['elapsed_seconds']:.1f}s</td>"
                          f"<td>{video_link}</td><td>{esc(row.get('error') or '')}</td></tr>")
    missing_note = "" if complete else f"<p class='warning'>还缺 {len(summary['missing_episodes'])} 个 episode；成功率仅描述已记录部分，不能作为完整评测结论。</p>"
    pair_note = ""
    if comparison and comparison["overall"]["mismatched_pairs"]:
        pair_note = "<p class='warning'>存在初始状态或随机种子不一致的配对，已排除；详见 summary.json。</p>"
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>π0 / π0.5 · LIBERO 仿真对比</title>
<style>
:root{{color-scheme:light;--ink:#172c39;--muted:#546875;--line:#dbe3e8;--accent:#005f73}}
*{{box-sizing:border-box}}body{{margin:0;background:#f4f7f8;color:var(--ink);font:15px/1.6 system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:32px 24px 64px}}h1{{font-size:28px;margin-bottom:4px}}h2{{font-size:20px;margin-top:32px}}
p{{color:var(--muted)}}.cards{{display:flex;gap:16px;flex-wrap:wrap}}.card{{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;min-width:240px;flex:1}}strong{{font-size:36px;color:var(--accent)}}
.table{{overflow:auto;background:white;border:1px solid var(--line);border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{background:#eaf0f3;white-space:nowrap}}a{{color:var(--accent)}}.warning{{color:#a34308;font-weight:600}}.meta{{font-size:12px}}details{{margin-top:24px}}summary{{cursor:pointer;font-weight:600}}
</style><main>
<h1>π0 / π0.5 · LIBERO 仿真对比</h1><p>{esc(status)} · {summary['recorded_episodes']} / {summary['expected_episodes']} episodes</p>
{missing_note}<div class="cards">{''.join(cards)}</div>
<p>{esc(scope_note)}本结果不是论文表值复现，仅适用于本次配置与权重。</p>
<p>成功率分母包含运行错误，错误计为未成功；缺测不进入分母并单独列出。区间为 episode 层面的 Wilson 95% 区间，仅作描述，未校正同任务重复试验的相关性。</p>
<h2>按套件统计</h2><div class="table"><table><thead><tr><th>Suite</th><th>模型</th>{header}</tr></thead><tbody>{suite_rows}</tbody></table></div>
<h2>相同初始条件的配对比较</h2><p>“π0.5 胜 / 负”分别表示仅 π0.5 成功 / 仅 π0 成功；双方失败包含运行错误。差值 = 100 × (胜 − 负) / 有效配对数。</p>{pair_note}
<div class="table"><table><thead><tr><th>范围</th><th>配对 / 计划</th><th>π0.5 胜</th><th>π0.5 负</th><th>双方成功</th><th>双方失败</th><th>含错误配对</th><th>π0.5 − π0</th><th>缺配对 / 条件不符</th></tr></thead><tbody>{''.join(comparison_rows)}</tbody></table></div>
<details><summary>每项任务结果</summary><div class="table"><table><thead><tr><th>Suite / task</th><th>任务</th><th>模型</th>{header}</tr></thead><tbody>{task_rows}</tbody></table></div></details>
<h2>Episode 与视频</h2><p>试验编号与初始状态编号均从 0 开始。已声明但缺失的视频文件：{missing_videos}。视频链接相对于本报告文件，可直接本地打开。</p>
<div class="table"><table><thead><tr><th>模型</th><th>Suite / task</th><th>任务</th><th>试验</th><th>初始状态</th><th>Seed</th><th>结果</th><th>步数</th><th>耗时</th><th>视频</th><th>错误详情</th></tr></thead><tbody>{''.join(video_rows)}</tbody></table></div>
<p><a href="summary.json">完整 JSON</a> · <a href="per_suite.csv">套件 CSV</a> · <a href="per_task.csv">任务 CSV</a> · <a href="manifest.json">运行配置</a> · <a href="episodes.jsonl">逐轮原始结果</a></p>
<p class="meta">生成时间 (Asia/Shanghai)：{esc(datetime.fromisoformat(summary['generated_at']).astimezone(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'))}</p></main></html>
"""


def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        manifest, rows, task_ids, missing = read_run(run_dir)
        summary = build_summary(manifest, rows, task_ids, missing)
        outputs = {
            "summary.json": json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            "per_task.csv": csv_text(summary["per_task"], ["model", "suite", "task_id", "task_name"]),
            "per_suite.csv": csv_text(summary["per_suite"], ["model", "suite"]),
            "comparison.html": render_html(summary, rows, run_dir),
        }
        for filename, text in outputs.items():
            atomic_write(run_dir / filename, text)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Cannot summarize run: {exc}\n")
    print(json.dumps({"status": summary["status"], "recorded": len(rows),
                      "expected": summary["expected_episodes"], "report": str(run_dir / "comparison.html")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
