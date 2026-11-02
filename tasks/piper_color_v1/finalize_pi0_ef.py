
"""Create result tables and figures from completed real updates and full tasks."""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ef_common import *
from run_pi0_ef import partition
from publish_pi0_ef import publish
def finish():
    run=read(CAMPAIGN/'run.json')
    if not run.get('completed'):return
    figdir=CAMPAIGN/'figures';figdir.mkdir(exist_ok=True)
    fig,ax=plt.subplots(figsize=(7.2,3.4),layout='constrained')
    for g,color,style in [('E','#0072B2','-'),('F','#D55E00','--')]:
        data=[__import__('json').loads(s) for s in (CAMPAIGN/g/'lora_metrics.jsonl').read_text().splitlines()]
        xs=[r['optimizer_update'] for r in data];ys=[r['loss'] for r in data]
        ax.plot(xs,ys,color=color,alpha=.2,lw=.5)
        if len(ys)>=25:ax.plot(xs[24:],np.convolve(ys,np.ones(25)/25,'valid'),color=color,ls=style,label=g+' 25-update mean')
    ax.set(xlabel='Cumulative optimizer updates',ylabel='Training loss');ax.legend()
    fig.savefig(figdir/'training_loss.png',dpi=180);fig.savefig(figdir/'training_loss.svg');plt.close(fig)
    nodes=[read(p) for p in sorted(CAMPAIGN.glob('node_*.json')) if p.name not in ('node_roster.json',)]
    comparison=read(CAMPAIGN/'candidate_comparison.json')
    summary=[]
    for n in nodes:
        if 'episodes' not in n:continue
        for split in ('train','validation','test'):
            for slot in ('all','back','front_left','front_right'):
                rr=[r for r in n['episodes'] if r['split']==split and (slot=='all' or r['slot']==slot)]
                if not rr:continue
                close=[r for r in rr if r.get('first_close_frame') is not None]
                row=dict(candidate=n['label'],split=split,slot=slot,n=len(rr),successes=sum(r['success'] for r in rr),
                    closure_events=len(close),no_closure=len(rr)-len(close),
                    close_median_s=float(np.median([r['first_close_frame']/20 for r in close])) if close else None,
                    close_xy_median_mm=float(np.median([r.get('close_target_xy_m',r.get('close_target_distance_xy_m',0))*1000 for r in close])) if close else None)
                # Exact distance key from saved analyzer is retained below; recompute directly for unambiguous units.
                errors=[]
                for r in close:
                    with np.load(r['trajectory']) as d:
                        t=r['first_close_frame'];p=d['object_positions'][t,COLORS.index(r['target'])]
                        errors.append(float(np.linalg.norm(d['tcp'][t,:2]-p[:2])*1000))
                row['close_xy_median_mm']=float(np.median(errors)) if errors else None
                row['failure_stages']={stage:sum(not r['success'] and r['failure_stage']==stage for r in rr) for stage in sorted({r['failure_stage'] for r in rr})}
                summary.append(row)
    save(CAMPAIGN/'behavior_comparison.json',summary)
    # Paired traces use existing train-development tasks only.
    b=read(CAMPAIGN/'node_B.json')['episodes'];bfail=[r for r in b if r['split']=='train' and r['slot']=='back' and not r['success']]
    picked=bfail[:2]
    if picked:
        fig,axes=plt.subplots(len(picked),3,figsize=(9,3*len(picked)),squeeze=False,layout='constrained')
        for k,task in enumerate(picked):
            for label,color,style in [('B','#333333','-'),('E_500','#0072B2','--'),('F_500','#D55E00',':')]:
                p=CAMPAIGN/f'node_{label}.json'
                if not p.exists():continue
                match=[r for r in read(p)['episodes'] if key(r)==key(task)]
                if not match:continue
                with np.load(match[0]['trajectory']) as d:
                    t=np.arange(len(d['tcp']))/20;pos=d['object_positions'][:,COLORS.index(task['target'])]
                    vals=[1000*np.linalg.norm(d['tcp'][:,:2]-pos[:,:2],axis=1),d['tcp'][:,2]*1000,d['executed_command'][:,6]*1000]
                    for j,v in enumerate(vals):axes[k,j].plot(t,v,color=color,ls=style,label=label)
            for j,title in enumerate(('Target XY error (mm)','TCP height (mm)','Gripper command (mm)')):
                axes[k,j].set(xlabel='Episode time (s)',ylabel=title,title=f"{task['layout']} {task['target']} seed {task['base_seed']}")
            axes[k,2].legend()
        fig.savefig(figdir/'paired_rear_traces.png',dpi=180);fig.savefig(figdir/'paired_rear_traces.svg');plt.close(fig)
    table=['|Model|Split|Slot|Full success|Median closure s|Median closure XY mm|','|---|---|---|---|---|---|']
    for r in summary:
        table.append(f"|{r['candidate']}|{r['split']}|{r['slot']}|{r['successes']}/{r['n']}|{r['close_median_s']}|{r['close_xy_median_mm']}|")
    new=read(CAMPAIGN/'new_layout_comparison.json')
    text=f"# E/F complete task results\n\nFinished: {run['finished_at']}. Selected: {comparison['selected']}.\n\n"
    text+='B historical full training 211/240, validation 72/75, original test 53/60 retained. New test is not used for model selection or further training.\n\n'
    text+='Actual compute: '+__import__('json').dumps(run['counts'])+'\n\n'
    text+='Local teacher: 24 attempts, 24 complete successes. Intervention episodes are not autonomous policy successes.\n\n'
    text+='\n'.join(table)
    text+='\n\nClosure statistics use all episodes with a closure event. No-closure counts and failure stages are in behavior_comparison.json. Interpret speed together with complete success.\n'
    text+='Per-update loss, learning rate, sampling source, local/cumulative updates are in E/F. Both start at the same B full model/optimizer/RNG and old normalization, fixed 1e-6 and batch4.\n'
    text+='Raw trajectories and videos use the Release queue. Experiment status, upload status and deletion status are separate.\n'
    if new.get('performed') is False:text+='\nNew layouts were not evaluated because no candidate surpassed B.\n'
    else:text+='\nNew-layout paired comparison: '+__import__('json').dumps({k:v['summary'] for k,v in new.items()})+'\n'
    (CAMPAIGN/'final_report_zh.md').write_text(text)
    dest=ROOT/'results/piper-color-v1'/TASK/'figures';dest.mkdir(parents=True,exist_ok=True)
    import shutil
    for p in figdir.iterdir():shutil.copyfile(p,dest/p.name)
    save(CAMPAIGN/'report_complete.json',dict(at_utc=now(),figures=[p.name for p in figdir.iterdir()],visual_review='automatic render; human visual review not claimed'))
    publish(CAMPAIGN,'final-report-and-figures')
if __name__=='__main__':finish()
