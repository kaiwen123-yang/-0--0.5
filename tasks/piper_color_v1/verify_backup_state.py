"""Load the downloaded B full checkpoint; perform zero optimizer updates or evaluations."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,os.environ['PIPER_OPENPI'])
import jax
import numpy as np
from openpi.training import checkpoints,sharding
from scripts import train as upstream
from train_pi0_ab import config


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('checkpoint',type=Path);p.add_argument('receipt',type=Path);a=p.parse_args()
    t=time.monotonic();cfg=config(resume=True)
    train_rng,init_rng=jax.random.split(jax.random.key(cfg.seed));mesh=sharding.make_mesh(cfg.fsdp_devices)
    template,_=upstream.init_train_state(cfg,init_rng,mesh,resume=True)
    manager,found=checkpoints.initialize_checkpoint_dir(a.checkpoint.parent,keep_period=1,overwrite=False,resume=True)
    try:
        if not found:raise ValueError('Downloaded checkpoint not discoverable')
        state=checkpoints.restore_state(manager,template,None,step=int(a.checkpoint.name))
        jax.block_until_ready(state)
        counters=[int(x) for x in jax.tree.leaves(state.opt_state) if x.ndim==0 and np.issubdtype(x.dtype,np.integer)]
        if int(state.step)!=4020 or counters!=[4020,4020]:raise ValueError((int(state.step),counters))
        saved=json.loads((a.checkpoint/'resume.json').read_text())
        if saved['optimizer_updates']!=4020 or saved['train_rng_key_data']!=jax.random.key_data(train_rng).tolist():
            raise ValueError('Restored state/RNG provenance differs')
        a.receipt.write_text(json.dumps({'checkpoint':str(a.checkpoint),'model_and_optimizer_restored':True,
            'optimizer_updates':int(state.step),'optimizer_scalar_counters':counters,
            'optimizer_array_leaves':len(jax.tree.leaves(state.opt_state)),
            'new_optimizer_updates':0,'new_evaluation_episodes':0,'seconds':time.monotonic()-t},indent=2)+'\n')
        print(a.receipt.read_text(),flush=True)
    finally:manager.close()
