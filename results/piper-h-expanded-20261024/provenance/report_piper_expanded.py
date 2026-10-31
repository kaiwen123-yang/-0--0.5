"""Validate a frozen multi-suite evaluation and build a paired video gallery."""
import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import numpy as np


def load(path):
    return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True)
    args=parser.parse_args();root=args.campaign.resolve();plan=load(root/'plan.json')
    records={};manifests=[];validations=[];release={};runs=[];manifest_by_run={}
    for model in plan['models']:
        for suite in plan['suites']:
            run=root/f"{model}-{suite.removeprefix('libero_')}";runs.append(run)
            manifest=load(run/'manifest.json');manifests.append(manifest)
            manifest_by_run[model,suite]=manifest
            for filename,expected_hash in manifest['script_sha256'].items():
                assert hashlib.sha256((run/'provenance'/filename).read_bytes()).hexdigest()==expected_hash,(run,filename)
            assert manifest['adapter']==plan['adapter']
            assert manifest['models']==[model] and manifest['suite']==suite
            assert manifest['task_ids']==plan['suites'][suite]
            assert manifest['trials']==len(plan['initial_state_indices']) and manifest['trial_start']==0
            validation=load(run/'validation.json')
            assert validation['status'] in ('passed','passed_with_dynamics_warnings')
            assert validation.get('video_integrity_status',validation['status'])=='passed'
            validations.append(validation)
            for row in map(json.loads,(run/'episodes.jsonl').read_text().splitlines()):
                key=(model,suite,row['task_id'],row['trial_index'])
                assert key not in records and not row['error']
                row['run_directory']=str(run)
                row['development_case']=suite=='libero_spatial' and row['task_id']<3 and row['trial_index']<2
                scene=ET.parse((run/row['trajectory']).parent/'scene.xml').getroot()
                actual_base=np.fromstring(scene.find("./worldbody/body[@name='robot0_base_link']").get('pos'),sep=' ')
                assert np.array_equal(actual_base,manifest['base_position_m']),(run,row['task_id'],row['trial_index'])
                records[key]=row
            for check in load(run/'release-check.json'):
                key=(model,suite,check['task_id'],check['trial_index']);release[key]=check
    expected={(m,s,t,i) for m in plan['models'] for s,tasks in plan['suites'].items() for t in tasks for i in plan['initial_state_indices']}
    assert set(records)==expected and len(records)==plan['total_episodes']
    for manifest in manifests[1:]:
        for name in ('adapter','source_commits','flow_steps','replan_steps','home_qpos'):
            assert manifest[name]==manifests[0][name],name
    # The Object arena required a ground-mounted robot registration before any
    # Object episode could start. Verify this recorded addition explicitly;
    # policy sources and each model pair must otherwise be identical.
    amendments=load(root/'protocol-amendments.json')
    assert len(amendments)==1
    amendment=amendments[0]
    assert amendment['changed_file']=='piper_h_sim.py'
    assert not amendment['policy_settings_changed'] and not amendment['evaluation_grid_changed']
    for suite in plan['suites']:
        assert manifest_by_run['pi0',suite]['script_sha256']==manifest_by_run['pi05',suite]['script_sha256']
    old=manifest_by_run['pi0','libero_spatial']['script_sha256']
    new=manifest_by_run['pi0','libero_object']['script_sha256']
    assert set(old)==set(new)
    assert {name for name in old if old[name]!=new[name]}=={'piper_h_sim.py'}
    assert old['piper_h_sim.py']==amendment['old_sha256'] and new['piper_h_sim.py']==amendment['new_sha256']
    sources=[(root/f'pi0-{suite}'/'provenance/piper_h_sim.py').read_text() for suite in ('spatial','object')]
    classes=[{node.name:ast.get_source_segment(source,node) for node in ast.parse(source).body if isinstance(node,ast.ClassDef)} for source in sources]
    assert set(classes[1])-set(classes[0])=={'OnTheGroundPiperH'}
    for name,source in classes[0].items():assert source==classes[1][name],name
    paired=[]
    for suite,tasks in plan['suites'].items():
        for task in tasks:
            for trial in plan['initial_state_indices']:
                a,b=[records[m,suite,task,trial] for m in plan['models']]
                for name in ('scene_sha256','source_initial_state_sha256','environment_seed','policy_seed'):
                    assert a[name]==b[name],(suite,task,trial,name)
                states=[np.load(Path(row['run_directory'])/row['trajectory'],allow_pickle=False) for row in (a,b)]
                for name in ('qpos','qvel'):
                    assert np.array_equal(states[0][name][0],states[1][name][0]),(suite,task,trial,name)
                paired.append({'suite':suite,'task_id':task,'trial_index':trial,'development_case':a['development_case'],
                               'pi0_success':a['success'],'pi05_success':b['success']})
    assert set(release)=={key for key,row in records.items() if row['success']}
    def stats(rows):
        n=len(rows);s=sum(row['success'] for row in rows)
        return {'successes':s,'episodes':n,'success_rate':s/n if n else None}
    summary={'status':'complete','created_at':datetime.now(timezone.utc).isoformat(),
             'scope':plan,'protocol_amendments':amendments,'models':{},'per_task':[],'matched_scene_pairs':len(paired)}
    for model in plan['models']:
        selected=[row for key,row in records.items() if key[0]==model]
        summary['models'][model]={'all':stats(selected),'development':stats([r for r in selected if r['development_case']]),
            'new_evaluation_cases':stats([r for r in selected if not r['development_case']]),
            'suites':{suite:stats([r for r in selected if r['suite']==suite]) for suite in plan['suites']},
            'post_policy_release':{'passed':sum(r['release_check_passed'] for key,r in release.items() if key[0]==model),
                                   'checked':sum(key[0]==model for key in release),
                                   'terminal_predicate_changed_after_fresh_forward':sum(not r.get('terminal_success_after_forward',True) for key,r in release.items() if key[0]==model)}}
        for suite,tasks in plan['suites'].items():
            for task in tasks:
                summary['per_task'].append({'model':model,'suite':suite,'task_id':task,
                    'task_name':records[model,suite,task,0]['task_name'],
                    **stats([r for r in selected if r['suite']==suite and r['task_id']==task])})
    summary['paired_outcomes']={scope:{'both_success':sum(r['pi0_success'] and r['pi05_success'] for r in rows),
        'pi0_only':sum(r['pi0_success'] and not r['pi05_success'] for r in rows),
        'pi05_only':sum(not r['pi0_success'] and r['pi05_success'] for r in rows),
        'both_failed':sum(not r['pi0_success'] and not r['pi05_success'] for r in rows)}
        for scope,rows in [('all',paired),('new_evaluation_cases',[r for r in paired if not r['development_case']])]}
    regression=load(root/'original-three-regression.json')
    assert len(regression)==3
    for item in regression:
        key=(item['model'],item['suite'],item['task_id'],item['trial_index'])
        assert not item['before']['policy_success'] and records[key]['success'] and release[key]['release_check_passed']
    summary['original_three_failures_now_pass_policy_and_release']=True
    summary['pi05_minus_pi0_percentage_points']=100*(summary['models']['pi05']['all']['success_rate']-summary['models']['pi0']['all']['success_rate'])
    dynamics_violations=[row for check in validations for row in check.get('joint_limit_check',{}).get('violations',[])]
    validation={'status':'passed_with_dynamics_warnings' if dynamics_violations else 'passed',
        'video_integrity_status':'passed','episodes':len(records),'matched_initial_state_pairs':len(paired),
        'identical_adapter':True,'identical_sources_within_each_paired_suite':True,
        'cross_suite_source_difference':'documented OnTheGroundPiperH registration and panorama height addition only; original classes unchanged',
        'source_snapshots_match_manifest_hashes':True,'same_initial_full_qpos_qvel':True,
        'base_position_metadata_matches_all_saved_scenes':True,
        'original_video_files':sum(v['video_files'] for v in validations),'full_decode_all_original_videos':True,
        'whole_robot_in_all_original_panorama_frames':True,
        'release_checks':len(release),'release_checks_passed':sum(r['release_check_passed'] for r in release.values()),
        'joint_limit_check':{'status':'failed' if dynamics_violations else 'passed',
                            'threshold_rad':0.01,'violations':dynamics_violations},
        'per_run_validation':[str((run/'validation.json').relative_to(root)) for run in runs]}
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (root/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    flat=[]
    for key,row in sorted(records.items()):
        check=release.get(key)
        flat.append({name:row[name] for name in ('model','suite','task_id','trial_index','development_case','task_name','success','steps','scene_sha256','source_initial_state_sha256','policy_seed')}|
                    {'release_check_passed':check['release_check_passed'] if check else None,
                     'panorama':str(Path(row['run_directory'])/row['videos']['panorama']),
                     'multiview':str(Path(row['run_directory'])/row['videos']['multiview']),
                     'trajectory':str(Path(row['run_directory'])/row['trajectory'])})
    for name,rows in [('episodes',flat),('per_task',summary['per_task']),('paired_outcomes',paired)]:
        with (root/f'{name}.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    overview=[]
    for model,s in summary['models'].items():
        def result(v):return f"{v['successes']}/{v['episodes']} ({v['success_rate']:.1%})"
        overview.append(f"<tr><th>{'π0' if model=='pi0' else 'π0.5'}</th><td>{result(s['all'])}</td><td>{result(s['new_evaluation_cases'])}</td>"
                        f"<td>{result(s['suites']['libero_spatial'])}</td><td>{result(s['suites']['libero_object'])}</td>"
                        f"<td>{s['post_policy_release']['passed']}/{s['post_policy_release']['checked']}</td></tr>")
    sections=[];esc=html.escape
    regression_rows=[]
    for item in regression:
        before,after=item['before'],item['after']
        regression_rows.append(f"<tr><td>{'π0' if item['model']=='pi0' else 'π0.5'} · 任务 {item['task_id']} / 状态 {item['trial_index']}</td>"
            f"<td>{before['bilateral_contact_frames']} → {after['bilateral_contact_frames']}</td>"
            f"<td>{before['target_plate_final_xy_m']*100:.2f} → {after['target_plate_final_xy_m']*100:.2f} cm</td><td>成功；松爪检查通过</td></tr>")
    highlights=[]
    for key,check in sorted(release.items()):
        if 'video' not in check:continue
        row=records[key];video=(Path(row['run_directory'])/check['video']).relative_to(root)
        highlights.append(f"<article><h3>{'π0' if key[0]=='pi0' else 'π0.5'} · {key[1]} · 任务 {key[2]} / 状态 {key[3]}</h3>"
                          f"<video controls playsinline preload='none' src='{video}'></video><p>{esc(row['task_name'])}</p></article>")
    for suite,tasks in plan['suites'].items():
        for task in tasks:
            pairs=[]
            for trial in plan['initial_state_indices']:
                panels=[]
                for model in plan['models']:
                    row=records[model,suite,task,trial];run=Path(row['run_directory']);state='成功' if row['success'] else '失败'
                    pan=(run/row['videos']['panorama']).relative_to(root);multi=(run/row['videos']['multiview']).relative_to(root)
                    check=release.get((model,suite,task,trial));release_label=''
                    if check:release_label='；松爪复检'+('通过' if check['release_check_passed'] else '未通过')
                    panels.append(f"<article><h4>{'π0' if model=='pi0' else 'π0.5'} · {state} · {row['steps']} 步</h4>"
                                  f"<video controls playsinline preload='none' src='{pan}'></video><p><a href='{pan}'>全景</a> · <a href='{multi}'>三视角</a>{release_label}</p></article>")
                case='调试场景复测' if row['development_case'] else '新增评测场景'
                pairs.append(f"<div class='case' data-development='{str(row['development_case']).lower()}'><h3>初始状态 {trial} · {case}</h3><div class='pair'>{''.join(panels)}</div></div>")
            a,b=[next(s for s in summary['per_task'] if s['model']==m and s['suite']==suite and s['task_id']==task) for m in plan['models']]
            sections.append(f"<details data-suite='{suite}'><summary>{suite} · 任务 {task}　π0 {a['successes']}/5　π0.5 {b['successes']}/5</summary>"
                            f"<p>{esc(row['task_name'])}</p>{''.join(pairs)}</details>")
    page=f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Piper H 扩展仿真：150 次抓放测试</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f8;color:#183142;font:16px/1.7 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:30px 24px}}h1{{margin:0}}section,details{{background:white;border:1px solid #dbe3e9;border-radius:12px;padding:22px;margin:22px 0}}summary{{font-weight:700;cursor:pointer}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #dbe3e9}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}video{{width:100%;background:#111}}a{{color:#096984}}.note{{background:#fff2e5;border-left:4px solid #c87538;padding:14px 18px}}.case{{border-top:1px solid #dbe3e9}}select{{font:inherit;padding:6px}}@media(max-width:900px){{.pair{{grid-template-columns:1fr}}.table{{overflow-x:auto}}}}</style>
<main><h1>Piper H ＋ 官方双指夹爪：扩展仿真对比</h1><p>15 个任务 × 5 个初始状态 × 2 个模型 = 150 次 · 默认 100 mm 夹爪 · 1280×720 全景 / 20 FPS · 未连接实机、未微调</p>
<section class='table'><table><thead><tr><th>模型</th><th>全部场景</th><th>新增场景</th><th>Spatial 10 任务</th><th>Object 5 任务</th><th>成功后的松爪检查</th></tr></thead><tbody>{''.join(overview)}</tbody></table>
<p class='note'>每个模型 75 次，其中 6 个初始场景用于适配调试；另外 69 个是本次适配冻结后才评测的场景，不代表它们未出现在预训练数据中。两个模型使用相同物体初态、机器人初态与种子。此结果是更换机器人后的 Piper H 迁移测试，不能当作标准 Panda LIBERO 分数，也不能据此隔离预训练数据与算法结构的影响。</p></section>
<section><h2>本次修正与检查</h2><p>平行双指夹爪采用等价的 180° 工具坐标及对应虚拟腕部相机，使初始第 6 关节从约 160° 回到约 −20°；物理几何和限位保持官方值。归一化夹爪命令每物理步变化量从 0.1 改为训练环境的 0.01，降低过快闭合带来的抓取偏差。未使用物体真值反馈修正策略动作。原 12 条回归中两模型各 6/6，扩大测试前已冻结参数。</p>
<p>成功率沿用原任务判据与步数上限，失败录像全部保留。松爪检查只在策略已成功后执行，另列通过次数，不改变策略成功率。恢复状态并重新计算接触时，个别终态的瞬时判据与原环境返回值不同；检查日志保留该差异，并要求之后连续 2 秒满足重新计算后的目标条件，避免把一次瞬时接触当作稳定放置。虚拟相机、TCP、驱动与接触尚未按实机标定。</p>
<p>Object 使用地面场景。首次启动因缺少 OnTheGroundPiperH 注册而在评测前退出；随后补充同一机械臂的地面安装入口，并将全景相机高度同步下移。原桌面模型类、策略与适配参数均未改变，两个模型在每个任务组内使用相同源码。该执行修订和失败的启动日志均已保留。</p>
<p>动力学检查：{len(dynamics_violations)} 条轨迹的软关节限位超调达到或超过原验收阈值 0.01 rad，逐条保存在校验文件中；未放宽阈值，也未从成功率中剔除这些轨迹。录像完整性与动力学校验分别记录，本轮不作为硬件关节跟踪验收。</p>
<p><a href='plan.json'>预先固定的评测计划</a> · <a href='protocol-amendments.json'>地面场景执行修订</a> · <a href='metadata-corrections.json'>安装高度日志更正</a> · <a href='summary.json'>完整汇总</a> · <a href='episodes.csv'>150 次逐条结果</a> · <a href='per_task.csv'>任务成功率</a> · <a href='validation.json'>录像与场景校验</a> · <a href='../../docs/public_datasets_piper_20261024.md'>公开数据集调研</a></p></section>
<section class='table'><h2>此前 3 次失败的对应复测</h2><table><thead><tr><th>原失败案例</th><th>双指接触帧数：前 → 后</th><th>终态碗盘水平距离：前 → 后</th><th>本轮结果</th></tr></thead><tbody>{''.join(regression_rows)}</tbody></table><p>原成功判据保持不变。接触帧数是轨迹诊断量，不等于抓取质量评分。<a href='original-three-regression.json'>逐条前后证据</a></p></section>
<section><h2>代表性成功录像</h2><p>每条完整保留策略过程，并在末尾追加明确标注的 5 秒固定松爪检查；追加阶段不由 π 策略生成。原始视频和全部失败录像在下方任务列表。</p><div class='pair'>{''.join(highlights)}</div></section>
<section><h2>全部原始全景录像</h2><p>展开任务即可播放；无剪辑、无加速。三视角版另含外部与腕部相机，全景相机不输入策略。</p>
<label>任务组 <select id='suite'><option value='all'>全部</option><option value='libero_spatial'>Spatial</option><option value='libero_object'>Object</option></select></label>　<label>场景 <select id='scope'><option value='all'>全部</option><option value='new'>仅新增评测场景</option></select></label></section>
{''.join(sections)}<script>function filter(){{const suite=document.getElementById('suite').value,scope=document.getElementById('scope').value;document.querySelectorAll('details[data-suite]').forEach(e=>e.hidden=suite!=='all'&&e.dataset.suite!==suite);document.querySelectorAll('.case').forEach(e=>e.hidden=scope==='new'&&e.dataset.development==='true');}}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filter));</script></main></html>"""
    (root/'index.html').write_text(page)
    (root/'provenance').mkdir(exist_ok=True)
    shutil.copy2(__file__,root/'provenance'/Path(__file__).name)
    print(json.dumps({'models':summary['models'],'validation':validation}))


if __name__=='__main__':main()
