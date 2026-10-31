"""Validate saved Piper simulation trajectories/videos and build a local viewing page."""
import argparse
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
import subprocess

import numpy as np
import mujoco


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args()
    run=args.run_dir.resolve();manifest=json.loads((run/'manifest.json').read_text())
    rows=[json.loads(x) for x in (run/'episodes.jsonl').read_text().splitlines()]
    expected={(m,manifest['suite'],t,i) for m in manifest['models'] for t in manifest['task_ids'] for i in range(manifest['trials'])}
    assert len(rows)==len(expected)==manifest['expected_episodes']
    assert {(r['model'],r['suite'],r['task_id'],r['trial_index']) for r in rows}==expected
    assert not any(r['error'] or r['status']=='error' for r in rows)
    by_key={(r['model'],r['task_id'],r['trial_index']):r for r in rows}
    pairs=0
    if set(manifest['models'])=={'pi0','pi05'}:
        for task in manifest['task_ids']:
            for trial in range(manifest['trials']):
                a,b=(by_key[m,task,trial] for m in ('pi0','pi05'))
                for field in ('scene_sha256','source_initial_state_sha256','environment_seed','policy_seed'):assert a[field]==b[field]
                pairs+=1
    reports=[]
    for row in rows:
        trajectory=run/row['trajectory'];saved=np.load(trajectory,allow_pickle=False)
        frames=row['steps']+row['wait_steps']+1
        assert frames==row['video_frames'] and saved['actions'].shape==(row['steps'],7)
        assert len(saved['qpos'])==len(saved['qvel'])==frames
        assert all(np.isfinite(saved[name]).all() for name in saved.files)
        model=mujoco.MjModel.from_xml_path(str(trajectory.parent/'scene.xml'));data=mujoco.MjData(model)
        assert saved['qpos'].shape==(frames,model.nq) and saved['qvel'].shape==(frames,model.nv)
        assert sum(model.joint(i).name.startswith('robot0_joint') for i in range(model.njnt))==6
        cam=model.camera('robot0_panorama').id
        geoms=[i for i in range(model.ngeom) if (model.geom(i).name or '').startswith(('robot0_','gripper0_')) and model.geom_group[i]==1]
        tan=np.tan(np.deg2rad(model.cam_fovy[cam])/2);max_extent=0.;min_depth=float('inf');max_joint_violation=0.
        arm_ids=[model.joint(f'robot0_joint{i}').id for i in range(1,7)]
        for q in saved['qpos']:
            data.qpos[:]=q;mujoco.mj_forward(model,data)
            # Conservative spheres around visual meshes also cover the mesh vertices.
            R=data.cam_xmat[cam].reshape(3,3)
            centers=(data.geom_xpos[geoms]-data.cam_xpos[cam])@R
            radii=model.geom_rbound[geoms]
            depths=-centers[:,2]-radii
            assert np.all(depths>0)
            extents=np.column_stack(((np.abs(centers[:,0])+radii)/(depths*tan*(1280/720)),
                                     (np.abs(centers[:,1])+radii)/(depths*tan)))
            max_extent=max(max_extent,float(extents.max()));min_depth=min(min_depth,float(depths.min()))
            joint_q=q[model.jnt_qposadr[arm_ids]];limits=model.jnt_range[arm_ids]
            max_joint_violation=max(max_joint_violation,float(np.max(limits[:,0]-joint_q)),float(np.max(joint_q-limits[:,1])))
        assert max_extent<1,('Robot might be cropped',row['model'],row['task_id'],max_extent)
        assert max_joint_violation<0.01,('Joint limit violation',max_joint_violation)
        for kind,relative in row['videos'].items():
            path=run/relative
            stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                'stream=width,height,codec_name,avg_frame_rate,nb_frames','-of','json',str(path)],text=True))['streams'][0]
            size=[1280,720] if kind=='panorama' else [1280,1008]
            assert [stream['width'],stream['height']]==size and stream['codec_name']=='h264'
            assert stream['avg_frame_rate']=='20/1' and int(stream['nb_frames'])==frames
            subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True,timeout=60,stdout=subprocess.DEVNULL)
            reports.append({'video':relative,'frames':frames,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                            'max_robot_projected_extent':max_extent,'joint_limit_violation_rad':max_joint_violation})
    assert not list(run.rglob('*.partial.mp4'))
    summary={'status':'complete','results':{m:{'successes':sum(r['success'] for r in rows if r['model']==m),
              'episodes':sum(r['model']==m for r in rows)} for m in manifest['models']},'scope':manifest['scope']}
    validation={'status':'passed','checked_at':datetime.now(timezone.utc).isoformat(),'episodes':len(rows),'video_files':len(reports),
                'matched_scene_pairs':pairs,'full_video_decode':True,'panorama_contains_entire_robot_in_all_saved_frames':True,
                'projection_method':'Conservative camera-space visual mesh bounding spheres; all projected extents below 1',
                'artifacts':reports}
    (run/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (run/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    esc=html.escape
    sections=[]
    for task in manifest['task_ids']:
        for trial in range(manifest['trials']):
            selected=[by_key[m,task,trial] for m in manifest['models']]
            panels=[]
            for row in selected:
                label='π0' if row['model']=='pi0' else 'π0.5'
                result='成功' if row['success'] else '到达步数上限，未完成任务'
                panels.append(f"<article><h3>{label} · {result}</h3><video controls preload='metadata' playsinline src='{esc(row['videos']['multiview'])}'></video><p><a href='{esc(row['videos']['panorama'])}'>纯全景 1280×720</a> · <a href='{esc(row['videos']['multiview'])}'>三视角 1280×1008</a> · <a href='{esc(row['trajectory'])}'>动作与仿真状态</a></p></article>")
            sections.append(f"<section><h2>任务 {task} · 初始状态 {trial}</h2><p>{esc(selected[0]['task_name'])}</p><div class='pair'>{''.join(panels)}</div></section>")
    outcomes='；'.join(('π0' if m=='pi0' else 'π0.5')+f"：{s['successes']}/{s['episodes']}" for m,s in summary['results'].items())
    page=f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Piper H 全景仿真</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f9;color:#192f3d;font:16px/1.7 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:30px 24px}}h1{{margin:0}}section{{background:white;border:1px solid #dce4eb;border-radius:12px;padding:22px;margin:25px 0}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}video{{width:100%;background:#111;border-radius:6px}}a{{color:#176d8d}}.note{{border-left:4px solid #d07743;background:#fff3e7;padding:14px 20px}}@media(max-width:900px){{.pair{{grid-template-columns:1fr}}}}
</style><main><h1>Piper H ＋ 松灵官方双指夹爪：全景仿真</h1><p>100 mm 默认行程 · MuJoCo / LIBERO 场景 · 20 FPS · {len(rows)} 条完整策略轨迹 · 未连接实机</p>
<p class='note'>本轮是官方 LIBERO 权重通过 Piper H 接口的仿真测试，{outcomes}。机器人类型、初始状态、动作与姿态约定见运行设置；不是标准 Panda LIBERO 基准。权重未针对 Piper H 微调，夹爪接触、驱动参数和虚拟相机安装尚未按实机标定。</p>
<p>主画面完整显示机械臂、夹爪、桌面与目标物体，底部保留外部近景及腕部相机。每条录像另存独立全景文件；未裁剪、未加速。全景相机仅用于录制，不输入策略。</p>
<p><a href='manifest.json'>运行设置</a> · <a href='episodes.jsonl'>逐次结果</a> · <a href='validation.json'>视频与轨迹校验</a></p>{''.join(sections)}</main></html>"""
    (run/'index.html').write_text(page)
    print(json.dumps({k:v for k,v in validation.items() if k!='artifacts'}))
    print(json.dumps(summary))


if __name__=='__main__':main()
