"""H500: restore complete B state and use E's unchanged upstream train step."""
import dataclasses, functools, json, logging, time
import jax
import numpy as np
from openpi.training import checkpoints, data_loader as D, sharding
from dataset import PiperDataset
from policy_config import RUN, DATA
from train_pi0_ef import config as e_config
from train_pi0_120 import OrderedDataset
from h_common import OLD, RECOVERY, read, save


class RecoveryDataset:
    def __init__(self):
        self.original = PiperDataset(DATA, 'train', 10)
        self.recovery = PiperDataset(RECOVERY, 'train', 10)
    def __len__(self):
        return len(self.original) + len(self.recovery)
    def __getitem__(self, index):
        n = len(self.original)
        return self.original[index] if index < n else self.recovery[index - n]


def config():
    return dataclasses.replace(e_config(), exp_name='h_recovery')


def train():
    from scripts import train as upstream
    logging.basicConfig(level=logging.INFO)
    started = time.monotonic()
    cfg = config()
    (RUN / 'train_config.txt').write_text(repr(cfg))
    dc = cfg.data.create(cfg.assets_dirs, cfg.model)
    order = np.load(RUN / 'sample_order.npy', allow_pickle=False)
    train_rng = jax.random.wrap_key_data(np.asarray(read(OLD / 'resume.json')['train_rng_key_data'], dtype=np.uint32))
    _, init_rng = jax.random.split(jax.random.key(cfg.seed))
    mesh = sharding.make_mesh(cfg.fsdp_devices)
    data_sharding = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    replicated = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec())
    manager, _ = checkpoints.initialize_checkpoint_dir(cfg.checkpoint_dir, keep_period=1, overwrite=False, resume=False)
    dataset = D.transform_dataset(OrderedDataset(RecoveryDataset(), order), dc)
    loader = D.DataLoaderImpl(dc, D.TorchDataLoader(dataset, 4, sharding=data_sharding,
        shuffle=False, num_workers=cfg.num_workers, seed=cfg.seed, num_batches=500))
    state, state_sharding = upstream.init_train_state(cfg, init_rng, mesh, resume=True)
    source_manager, _ = checkpoints.initialize_checkpoint_dir(OLD.parent, keep_period=1, overwrite=False, resume=True)
    try:
        state = checkpoints.restore_state(source_manager, state, loader, step=2010)
    finally:
        source_manager.close()
    jax.block_until_ready(state)
    report = dict(group='H', source_checkpoint=str(OLD), local_updates=0, optimizer_updates=int(state.step),
        full_optimizer_restored=True,
        optimizer_scalar_counters=[int(x) for x in jax.tree.leaves(state.opt_state)
                                   if x.ndim == 0 and np.issubdtype(x.dtype, np.integer)],
        train_rng_key_data=jax.random.key_data(train_rng).tolist(),
        trainable_parameters=sum(x.size for x in jax.tree.leaves(state.params.filter(cfg.trainable_filter))),
        train_step='upstream.train_step', visual_update_zeroing=False, learning_rate=1e-6,
        schedule_decay_steps=5020, segment_end_local=500, segment_complete=False,
        initialization_seconds=time.monotonic() - started)
    save(RUN / 'lora_training.json', report)
    print('TRAIN_INITIALIZED', json.dumps(report), flush=True)
    step_fn = jax.jit(functools.partial(upstream.train_step, cfg),
        in_shardings=(replicated, state_sharding, data_sharding),
        out_shardings=(state_sharding, replicated), donate_argnums=(1,))
    previous_end = time.monotonic()
    try:
        for local, batch in enumerate(loader, start=1):
            t0 = time.monotonic()
            with sharding.set_mesh(mesh):
                state, info = step_fn(train_rng, state, batch)
            values = {k: float(v) for k, v in jax.device_get(info).items()}
            samples = order[(local - 1) * 4:local * 4].tolist()
            row = dict(group='H', local_update=local, optimizer_update=int(state.step), **values,
                wall_time=time.time(), compute_seconds=time.monotonic() - t0, data_wait_seconds=t0 - previous_end,
                learning_rate=1e-6, sample_offset_before=(local - 1) * 4, sample_indices=samples,
                sample_components=['original' if i < 32160 else 'recovery' for i in samples],
                rng_fold_in_step=int(state.step) - 1)
            with (RUN / 'lora_metrics.jsonl').open('a') as stream:
                stream.write(json.dumps(row, allow_nan=False) + '\n')
            if local == 1 or local % 10 == 0:
                save(RUN / 'training_progress.json', row)
                print('UPDATE', json.dumps(row), flush=True)
            previous_end = time.monotonic()
        checkpoints.save_state(manager, state, loader, 500)
        manager.wait_until_finished()
        checkpoint = cfg.checkpoint_dir / '500'
        save(checkpoint / 'resume.json', dict(local_updates=500, optimizer_updates=int(state.step), sample_offset=2000,
            sample_order_file=str(RUN / 'sample_order.npy'), train_rng_key_data=jax.random.key_data(train_rng).tolist(),
            rng_rule='jax.random.fold_in(train_rng, cumulative optimizer state.step); 4020..4519',
            old_checkpoint=str(OLD), group='H'))
        resume_metadata = read(checkpoint / 'resume.json')
        save(RUN / 'resume.json', resume_metadata)
        report.update(local_updates=500, optimizer_updates=int(state.step), checkpoint=str(checkpoint),
            segment_complete=True, wall_seconds=time.monotonic() - started)
        save(RUN / 'lora_training.json', report)
        print('CHECKPOINT_COMPLETE H500', flush=True)
    finally:
        manager.close()

if __name__ == '__main__':
    train()
