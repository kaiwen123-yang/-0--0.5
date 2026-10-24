"""Produce a self-contained local results page and deployment candidate export."""
import csv
import html
import json
from pathlib import Path
import shutil

from policy_config import RUN


def main():
    validations = {}
    for mode in ("base", "lora", "full"):
        validations[mode] = json.loads((RUN / "evaluations" / f"{mode}_validation" / "summary.json").read_text())
    # Select on validation only. Test outcomes cannot change this choice.
    selected = max(("lora", "full"), key=lambda m: validations[m]["success_rate"])
    training = json.loads((RUN / f"{selected}_training.json").read_text())
    source = Path(training["checkpoint"])
    deployment = RUN / "deployment"
    deployment.mkdir(exist_ok=True)
    for item in ("params", "assets"):
        shutil.copytree(source / item, deployment / "checkpoint" / item, dirs_exist_ok=True)
    for name in ("policy_config.py", "serve.py", "hardware.json", "deployment_io.py", "README.md"):
        shutil.copy2(Path(__file__).parent / name, deployment / name)
    manifest = dict(selected_mode=selected, selection_rule="largest validation success rate; ties choose LoRA",
                    source_checkpoint=str(source), exported_checkpoint=str(deployment / "checkpoint"),
                    validation_successes=validations[selected]["successes"], validation_total=validations[selected]["total"],
                    training_domain="simulation", hardware_validated=False,
                    required_hardware_inputs="DC1 wrist RGB, D435i external RGB, measured joint radians + opening metres",
                    outstanding="real camera enumeration / mounting calibration / joint mapping verification / representative real demonstrations")
    (deployment / "manifest.json").write_text(json.dumps(manifest, indent=2))
    all_results, rows, videos = {}, [], []
    for mode, split in [("base","validation"),("lora","validation"),("full","validation"),("lora","test"),("full","test")]:
        d = json.loads((RUN / "evaluations" / f"{mode}_{split}" / "summary.json").read_text())
        all_results[f"{mode}_{split}"] = {k:v for k,v in d.items() if k!="episodes"}
        rows.append(f"<tr><td>{mode}</td><td>{split}</td><td>{d['successes']}/{d['total']}</td><td>{100*d['success_rate']:.1f}%</td></tr>")
        for e in d["episodes"]:
            relative = Path(e["video"]).relative_to(RUN)
            title = f"{mode} {split} / layout {e['layout_seed']} / {e['target']} / success={e['success']}"
            videos.append(f'<details><summary>{html.escape(title)}</summary><video controls preload="none" width="960" src="{relative}"></video></details>')
    report = dict(results=all_results, selected=manifest, hardware_execution=False,
                  limitations=["Synthetic rigid blocks and one fixed box; limited layout variation.",
                               "Camera extrinsics and actuator response are not measured physical calibration.",
                               "Three color prompts share each layout; episodes are not independent random layouts.",
                               "Simulated time pauses during inference; latency is recorded separately.",
                               "Teacher uses privileged object poses; learned policy does not."])
    (RUN / "summary.json").write_text(json.dumps(report, indent=2))
    with (RUN / "summary.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "split", "successes", "total", "success_rate"])
        for key, r in all_results.items():
            writer.writerow([r[k] for k in ("mode", "split", "successes", "total", "success_rate")])
    body = '<!doctype html><meta charset="utf-8"><title>Piper H 颜色入盒</title><style>body{font:18px system-ui;max-width:1100px;margin:40px auto;background:#f4f5f7;color:#17202a}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:10px}video{max-width:100%}details{margin:16px 0}</style>'
    body += '<h1>Piper H 颜色入盒：π0.5 仿真微调</h1><p>训练 120 条 / 验证 15 条 / 测试 30 条；按布局隔离。成功要求正确颜色入盒、夹爪打开、其他物体不被明显移动，并连续稳定 2 秒。未连接实机。</p>'
    body += '<table><tr><th>模型</th><th>集合</th><th>成功/总数</th><th>成功率</th></tr>'+''.join(rows)+'</table>'
    body += f'<p>根据验证集选择：{selected}。该候选仍需实机相机和动作接口验证，不能据此宣称可以稳定实机抓取。</p>'
    body += '<p><a href="summary.json">完整结果 JSON</a> · <a href="summary.csv">CSV</a> · <a href="deployment/manifest.json">部署清单</a></p>'
    body += '<h2>全景视频</h2>'+''.join(videos)
    (RUN / "index.html").write_text(body)
    print(json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()
