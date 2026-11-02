
"""Fix matched E/F sample starts before any update; preserve B optimizer/RNG/norm."""
import shutil
import numpy as np
from ef_common import *
def prepare():
    h=ROOT/'outputs/pi0-b-coverage-correction-test-20261101'
    old=read(h/'contract.json')
    cfg=dict(task=TASK,base_optimizer_updates=4020,max_updates_per_group=1000,first_segment=500,
        learning_rate=1e-6,batch=4,old_checkpoint=str(OLD),old_checkpoint_files=old['old_checkpoint_files'],
        old_resume=read(OLD/'resume.json'),rng_rule='B train_rng folded with cumulative state.step',
        protocol=dict(hz=20,horizon=10,replan=5,max_steps=420,continuous_success_steps=40),
        source_review_commit='9b30982a55a6ef6e6ce78563c709d879514da0d2')
    save(CAMPAIGN/'contract.json',cfg)
    evaluation=CAMPAIGN/'evaluation_layouts';evaluation.mkdir(exist_ok=True)
    manifest=read(V2/'dataset/manifest.json');manifest['split_seeds']['test']=list(range(3000,3010))
    save(evaluation/'manifest.json',manifest)
    save(CAMPAIGN/'node_roster.json',roster('validation',range(1000,1005),range(42,47))+read(CAMPAIGN/'development_training_roster.json'))
    save(CAMPAIGN/'new_layout_roster.json',roster('test',range(3000,3010),(42,43)))
def samplers():
    entries=read(V2/'dataset/index.json')
    streams=np.random.SeedSequence(42).spawn(3)
    colors=np.random.default_rng(streams[0]).integers(0,3,4000)
    layouts=np.random.default_rng(streams[1]).integers(100,140,4000)
    u=np.random.default_rng(streams[2]).random(4000)
    frames=np.where(u<.4,np.floor(u/.4*10),np.where(u<.7,10+np.floor((u-.4)/.3*52),62+np.floor((u-.7)/.3*206))).astype(np.int64)
    lookup={(e['layout_seed'],e['target']):i for i,e in enumerate(entries)}
    order=np.array([lookup[(int(l),COLORS[int(c)])] for l,c in zip(layouts,colors)])*268+frames
    rng=np.random.default_rng(20261102)
    mask=np.zeros(4000,dtype=bool)
    for begin in (0,2000): mask[begin+rng.choice(2000,200,replace=False)]=True
    corr=read(CAMPAIGN/'correction_dataset/index.json')
    ends=np.cumsum([e['frames'] for e in corr]); starts=np.r_[0,ends[:-1]]
    pools={};categories=('align_descend','grasp_lift','completion')
    for i,e in enumerate(corr):
        stages=np.load(CAMPAIGN/'correction_dataset'/e['directory']/'stage.npy')
        for cat in categories:
            selected=np.isin(stages,('local_reopen','local_align','descend') if cat=='align_descend' else ('grasp','lift') if cat=='grasp_lift' else ('transfer','lower','release','retreat','settle','success_hold'))
            if selected.any(): pools.setdefault((cat,e['target']),[]).append((i,np.flatnonzero(selected)))
    extra=[];details=[]
    for segment in range(2):
        cats=np.array(['align_descend']*100+['grasp_lift']*60+['completion']*40);rng.shuffle(cats)
        for j,cat in enumerate(cats):
            available=[c for c in COLORS if (cat,c) in pools]; color=available[j%len(available)]
            options=pools[(cat,color)];i,ff=options[int(rng.integers(len(options)))];frame=int(rng.choice(ff))
            extra.append(int(starts[i]+frame));details.append(dict(segment=segment,category=str(cat),color=color,episode=i,frame=frame,layout=corr[i]['layout_seed']))
    for group in ('E','F'):
        run=CAMPAIGN/group;run.mkdir(exist_ok=True);(run/'logs').mkdir(exist_ok=True)
        for name,src in [('scene',V2/'scene'),('assets',OLD/'assets'),('dataset',V2/'dataset')]:
            if not (run/name).exists(): (run/name).symlink_to(src,target_is_directory=True)
        schedule=order.copy()
        if group=='F':schedule[mask]=32160+np.array(extra)
        np.save(run/'sample_order.npy',schedule,allow_pickle=False)
        save(run/'sample_order.json',schedule.tolist())
        save(run/'sampler.json',dict(group=group,samples=4000,source_optimizer_updates=BASE,
            correction_starts=400 if group=='F' else 0,replacement_indices=np.flatnonzero(mask).tolist() if group=='F' else [],
            correction_details=details if group=='F' else [],paired_original_positions=True,
            original_frame_probabilities=[.4,.3,.3],correction_stage_probabilities=[.5,.3,.2],sampling_seed=20261102))
if __name__=='__main__':
    import sys
    samplers() if len(sys.argv)>1 and sys.argv[1]=='samplers' else prepare()

