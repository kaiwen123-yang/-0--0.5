"""Join two fully recorded Piper H evaluations without selecting successful trials."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text())


def check_release(run, row, release):
    """Decode appended footage and verify that the added motion remains in frame."""
    folder = (run / row['trajectory']).parent
    states = np.load(folder / 'release-check-states.npz', allow_pickle=False)
    assert states['qpos'].shape[0] == states['success'].shape[0] == 100
    assert np.isfinite(states['qpos']).all()
    assert bool(states['success'][-40:].all()) == bool(release['last_2s_success_frames'] == 40)
    model = mujoco.MjModel.from_xml_path(str(folder / 'scene.xml'))
    data = mujoco.MjData(model)
    cam = model.camera('robot0_panorama').id
    geoms = [i for i in range(model.ngeom)
             if (model.geom(i).name or '').startswith(('robot0_', 'gripper0_')) and model.geom_group[i] == 1]
    tan = np.tan(np.deg2rad(model.cam_fovy[cam]) / 2)
    extent = 0.0
    target = model.body('akita_black_bowl_1_main').id
    robot_geoms = {i for i in range(model.ngeom)
                   if (model.geom(i).name or '').startswith(('robot0_', 'gripper0_'))}
    robot_contact = []
    arm_ids = [model.joint(f'robot0_joint{i}').id for i in range(1, 7)]
    for qpos in states['qpos']:
        data.qpos[:] = qpos
        mujoco.mj_forward(model, data)
        robot_contact.append(any(
            (c.geom1 in robot_geoms and model.geom_bodyid[c.geom2] == target)
            or (c.geom2 in robot_geoms and model.geom_bodyid[c.geom1] == target)
            for c in data.contact[:data.ncon]))
        centers = (data.geom_xpos[geoms] - data.cam_xpos[cam]) @ data.cam_xmat[cam].reshape(3, 3)
        radii = model.geom_rbound[geoms]
        depth = -centers[:, 2] - radii
        assert np.all(depth > 0)
        projected = np.column_stack(((np.abs(centers[:, 0]) + radii) / (depth * tan * 1280 / 720),
                                     (np.abs(centers[:, 1]) + radii) / (depth * tan)))
        extent = max(extent, float(projected.max()))
        # The phase caption occupies only the top 32 pixels of the panorama.
        assert np.max((centers[:, 1] + radii) / (depth * tan)) < 1 - 64 / 720
        q = qpos[model.jnt_qposadr[arm_ids]]
        limits = model.jnt_range[arm_ids]
        assert np.all(q >= limits[:, 0] - .01) and np.all(q <= limits[:, 1] + .01)
    assert extent < 1
    assert not any(robot_contact[-40:]), 'Target still contacts robot during final stability window'
    path = run / release['video']
    stream = read_json_stream(path)
    frames = row['video_frames'] + 101
    assert [stream['width'], stream['height']] == [1280, 720]
    assert stream['codec_name'] == 'h264' and stream['avg_frame_rate'] == '20/1'
    assert int(stream['nb_frames']) == frames
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                   check=True, timeout=60, stdout=subprocess.DEVNULL)
    return {'video': str(path), 'frames': frames, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'full_decode': True, 'max_robot_projected_extent': extent, 'caption_does_not_cover_robot': True,
            'robot_target_contact_frames_last_2s': sum(robot_contact[-40:])}


def read_json_stream(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,codec_name,avg_frame_rate,nb_frames', '-of', 'json', str(path)],
        text=True))['streams'][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pi0-run', type=Path, required=True)
    parser.add_argument('--pi05-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    runs = {'pi0': args.pi0_run.resolve(), 'pi05': args.pi05_run.resolve()}
    rows, manifests, validations, releases, audits = {}, {}, {}, {}, {}
    expected = {(t, i) for t in range(3) for i in range(2)}
    for model, run in runs.items():
        manifests[model] = read_json(run / 'manifest.json')
        validations[model] = read_json(run / 'validation.json')
        assert manifests[model]['models'] == [model] and manifests[model]['trials'] == 2
        assert manifests[model]['task_ids'] == [0, 1, 2]
        assert validations[model]['status'] == 'passed'
        data = [json.loads(s) for s in (run / 'episodes.jsonl').read_text().splitlines()]
        assert len(data) == 6 and not any(r['error'] for r in data)
        rows[model] = {(r['task_id'], r['trial_index']): r for r in data}
        assert set(rows[model]) == expected
        releases[model] = {(r['task_id'], r['trial_index']): r for r in read_json(run / 'release-check.json')}
        assert set(releases[model]) == {key for key, row in rows[model].items() if row['success']}
        audits[model] = {(r['task_id'], r['trial_index']): r for r in read_json(run / 'diagnostics/failure-audit.json')}
        assert set(audits[model]) == expected
    for field in ('adapter_version', 'home_qpos', 'script_sha256', 'source_commits', 'state_adapter', 'flow_steps', 'replan_steps'):
        assert manifests['pi0'][field] == manifests['pi05'][field], field
    for key in sorted(expected):
        a, b = (rows[m][key] for m in runs)
        for field in ('scene_sha256', 'source_initial_state_sha256', 'environment_seed', 'policy_seed'):
            assert a[field] == b[field], (key, field)
        states = [np.load(runs[m] / rows[m][key]['trajectory'], allow_pickle=False) for m in runs]
        assert all(np.array_equal(states[0][name][0], states[1][name][0]) for name in ('qpos', 'qvel'))
    combined, release_videos = [], []
    for model, run in runs.items():
        for key, row in sorted(rows[model].items()):
            audit = audits[model][key]
            release = releases[model].get(key)
            record = {'model': model, 'task_id': key[0], 'initial_state': key[1],
                      'state_used_during_diagnosis': key[1] == 0, 'policy_success': row['success'],
                      'steps': row['steps'], 'release_check_passed': release['release_check_passed'] if release else None,
                      'lift_m': audit['target_lift_m'], 'final_plate_xy_error_m': audit['target_plate_final_xy_m'],
                      'bilateral_contact_frames': audit['bilateral_contact_frames'],
                      'run_directory': str(run), 'panorama': str(run / row['videos']['panorama']),
                      'multiview': str(run / row['videos']['multiview']),
                      'panorama_with_release': str(run / release['video']) if release else None}
            combined.append(record)
            if release:
                release_videos.append(check_release(run, row, release))
    stats = {}
    for model in runs:
        selected = [r for r in combined if r['model'] == model]
        successes = sum(r['policy_success'] for r in selected)
        stats[model] = {'successes': successes, 'episodes': len(selected), 'success_rate': successes / len(selected),
                        'stable_after_release': sum(r['release_check_passed'] is True for r in selected),
                        'diagnosis_states': {'successes': sum(r['policy_success'] for r in selected if r['initial_state'] == 0), 'episodes': 3},
                        'additional_states': {'successes': sum(r['policy_success'] for r in selected if r['initial_state'] == 1), 'episodes': 3}}
    summary = {'status': 'complete', 'created_at': datetime.now(timezone.utc).isoformat(),
               'results': stats, 'matched_scene_pairs': 6,
               'scope': 'Piper H adapter v2, LIBERO-Spatial tasks 0/1/2, initial states 0/1; exploratory small sample, not standard Panda LIBERO benchmark',
               'training': 'none; unchanged official pi0_libero and pi05_libero checkpoints',
               'real_hardware_connected': False, 'gripper': 'Official AgileX default 100 mm; hardware stroke unconfirmed',
               'post_policy_validation': 'Separate fixed open/retreat/hold check after an already-successful policy; not included in policy success rate. Video appended with an explicit caption.',
               'source_runs': {m: str(r) for m, r in runs.items()}, 'episodes': combined,
               'interrupted_run_excluded': str(ROOT / 'results/piper-h-transfer-20261024-174356/execution-notes.json')}
    summary['diagnosis_runs_excluded_from_final_counts'] = []
    for label, name in [('original', 'piper-h-transfer-20261024-171827'),
                        ('official_rotvec_only', 'piper-h-transfer-20261024-173133'),
                        ('adapter_v2_pi05', 'piper-h-transfer-20261024-173501'),
                        ('adapter_v2_pi0', 'piper-h-transfer-20261024-173647')]:
        prior = ROOT / 'results' / name
        summary['diagnosis_runs_excluded_from_final_counts'].append(
            {'stage': label, 'run': str(prior), 'results': read_json(prior / 'summary.json')['results']})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (output / 'episodes.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(combined[0]))
        writer.writeheader(); writer.writerows(combined)
    validation = {'status': 'passed', 'matched_scene_pairs': 6, 'full_initial_qpos_qvel_equal': True,
                  'original_videos_validated': sum(v['video_files'] for v in validations.values()),
                  'release_videos': release_videos, 'all_policy_and_release_frames_contain_entire_robot': True}
    (output / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    for name in ('report_piper_adaptation.py', 'report_piper_h_demo.py', 'check_piper_release.py', 'audit_piper_failures.py'):
        (output / 'provenance').mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'scripts' / name, output / 'provenance' / name)
    esc = html.escape
    def link(path):
        return esc(os.path.relpath(path, output))
    overview = ''.join(f"<tr><td>{'π0' if m == 'pi0' else 'π0.5'}</td><td>{s['successes']}/6 ({s['success_rate']:.1%})</td>"
        f"<td>{s['diagnosis_states']['successes']}/3</td><td>{s['additional_states']['successes']}/3</td>"
        f"<td>{s['stable_after_release']}/{s['successes']}</td></tr>" for m, s in stats.items())
    failure_details = []
    for row in combined:
        if row['policy_success']:
            continue
        label = 'π0' if row['model'] == 'pi0' else 'π0.5'
        action = '未建立双指接触' if row['bilateral_contact_frames'] == 0 else f"双指接触 {row['bilateral_contact_frames']} 帧"
        failure_details.append(f"{label} 任务 {row['task_id']} / 状态 {row['initial_state']}：{action}，"
                               f"最大抬升 {row['lift_m'] * 100:.1f} cm，最终距盘心 {row['final_plate_xy_error_m'] * 100:.1f} cm")
    failure_text = '；'.join(failure_details) or '本轮没有失败轨迹'
    sections = []
    for task, trial in sorted(expected):
        panels = []
        for model in runs:
            record = next(r for r in combined if (r['model'], r['task_id'], r['initial_state']) == (model, task, trial))
            row = rows[model][task, trial]
            passed = record['policy_success']
            result = '成功' if passed else '失败（保留完整轨迹）'
            video = record['panorama_with_release'] or record['panorama']
            detail = (f"松爪稳定性检查：{'通过' if record['release_check_passed'] else '未通过'}；后半段为带标记的固定检查。" if passed else
                      f"双指接触 {record['bilateral_contact_frames']} 帧，最大抬升 {record['lift_m'] * 100:.1f} cm，最后距盘心 {record['final_plate_xy_error_m'] * 100:.1f} cm。")
            panels.append(f"<article><h3>{'π0' if model == 'pi0' else 'π0.5'} · {result}</h3>"
                f"<video controls playsinline preload='metadata' src='{link(video)}'></video><p>{detail}</p>"
                f"<p><a href='{link(record['panorama'])}'>原始策略全景</a> · <a href='{link(record['multiview'])}'>全景＋外部＋腕部</a></p></article>")
        state_label = '排查时使用的初始状态' if trial == 0 else '适配固定后新增的初始状态'
        sections.append(f"<section><h2>任务 {task} · 初始状态 {trial}</h2><p>{state_label} · {esc(row['task_name'])}</p>"
                        f"<div class='pair'>{''.join(panels)}</div></section>")
    page = f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Piper H 抓取适配与全景录像</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f8;color:#173142;font:16px/1.7 system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:32px 24px}}h1{{margin:0}}section,.card{{background:white;padding:24px;border:1px solid #dbe3e9;border-radius:12px;margin:24px 0}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}video{{width:100%;background:#111}}a{{color:#096984}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #dbe3e9}}
.note{{background:#fff3e7;border-left:4px solid #ca783f;padding:14px 20px}}@media(max-width:900px){{.pair{{grid-template-columns:1fr}}}}
</style><main><h1>Piper H 抓取已跑通：π0 / π0.5 仿真适配</h1><p>松灵官方 100 mm 默认夹爪 · 6 轴 Piper H · 1280×720 全景 · 20 FPS · 未连接实机</p>
<div class='card'><table><thead><tr><th>模型</th><th>本轮策略成功率</th><th>原初始状态</th><th>新增初始状态</th><th>成功后松爪检查</th></tr></thead><tbody>{overview}</tbody></table>
<p class='note'>范围仅为 3 个抓碗放盘任务 × 2 个初始状态，每个模型 6 次。状态 0 用于排查，状态 1 在适配固定后增加；样本少且任务相近，不能作为完整 LIBERO 基准或稳定实机成功率。所有失败均保留。权重未微调。</p></div>
<section><h2>失败原因与修正</h2><p>旧接口使用 SciPy 最短旋转向量，而官方 OpenPI LIBERO helper 保留另一角度分支；Piper 与 Panda 的 MuJoCo 四元数符号也不同。接近向下抓取的 π 旋转时，等价姿态会变成相差约 2π 的状态输入。现在统一向下工具姿态的正 x 四元数半球，再调用官方转换。该半球规则仍限于本轮向下抓取任务。</p>
<p>同时把初始工具偏航由 π/2 调整到 0.35 rad，以接近训练时的手部朝向和腕部视角，并重新求解带 Piper 关节限位的初始位姿。模型几何、接触参数、任务成功条件和 checkpoint 均保持不变；12 项局部控制方向检查通过。</p>
<p>排查轨迹：原接口 π0 0/3、π0.5 0/3；只换官方旋转向量转换，π0.5 仍为 0/3；再统一四元数符号和初始偏航，π0 为 2/3、π0.5 为 3/3。后两项同时修改，因此无法由这组试验分别量化它们的贡献。上表单独统计扩展后的完整 12 次测试。</p>
<p>{failure_text}。原成功判据包含水平距离小于 3 cm 及物体接触等条件。部分轨迹靠近第 6 关节限位，后续仍需扩展工作空间和视角验证；本次不放宽原始成功判据。</p></section>
<section><h2>如何看录像</h2><p>每段完整保留初始化、策略执行及末帧，没有加速或裁掉机械臂。成功视频后附 5 秒固定松爪、微退和等待检查，附加片段顶部明确标注 POST-POLICY VALIDATION；它只检查已成功轨迹，不能把策略失败改成成功。要求最后连续 2 秒目标条件保持成立且夹爪开口大于 90 mm；汇总时另检查这 2 秒内目标与机械臂/夹爪无接触。</p>
<p>全景相机只用于录像。另存策略外部与腕部相机的三视角版、逐帧状态和动作。驱动、凸包接触、TCP、相机安装位姿尚未按实机标定。</p>
<p><a href='summary.json'>完整结果 JSON</a> · <a href='episodes.csv'>逐次结果 CSV</a> · <a href='validation.json'>录像与场景校验</a> · <a href='{link(ROOT / 'docs/piper_h_plan.md')}'>适配说明与复运行命令</a></p></section>
{''.join(sections)}</main></html>"""
    (output / 'index.html').write_text(page)
    print(json.dumps({'output': str(output), 'results': stats, 'matched_scene_pairs': 6,
                      'original_videos': validation['original_videos_validated'], 'appended_videos': len(release_videos)}))


if __name__ == '__main__':
    main()
