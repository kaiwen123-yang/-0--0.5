"""G500: E's full optimizer with only final visual updates projected to zero."""
import dataclasses, functools, json, logging, time
import jax
import jax.numpy as jnp
import numpy as np
import optax
from flax import nnx
from openpi.shared import nnx_utils
from openpi.training import checkpoints, data_loader as D, sharding
from dataset import PiperDataset
from policy_config import RUN, DATA
from train_pi0_ef import config as e_config
from train_pi0_120 import OrderedDataset
from bct_common import OLD, read, save

VISION = nnx_utils.PathRegex("PaliGemma/img/.*")

def config():
    # E's num_train_steps and schedule remain 5020; this invocation consumes 500 batches.
    return dataclasses.replace(e_config(), exp_name="g_fixed_vision")

def train_step(config, rng, state, batch):
    model = nnx.merge(state.model_def, state.params)
    model.train()
    def loss_fn(model, rng, observation, actions):
        return jnp.mean(model.compute_loss(rng, observation, actions, train=True))
    train_rng = jax.random.fold_in(rng, state.step)
    observation, actions = batch
    diff_state = nnx.DiffState(0, config.trainable_filter)
    loss, grads = nnx.value_and_grad(loss_fn, argnums=diff_state)(model, train_rng, observation, actions)
    params = state.params.filter(config.trainable_filter)
    updates, new_opt_state = state.tx.update(grads, state.opt_state, params)
    updates = nnx_utils.state_map(updates, VISION, lambda value: value.replace(jnp.zeros_like(value.value)))
    new_params = optax.apply_updates(params, updates)
    nnx.update(model, new_params)
    new_params = nnx.state(model)
    new_state = dataclasses.replace(state, step=state.step + 1, params=new_params, opt_state=new_opt_state)
    if state.ema_decay is not None:
        new_state = dataclasses.replace(new_state, ema_params=jax.tree.map(
            lambda old, new: state.ema_decay * old + (1 - state.ema_decay) * new, state.ema_params, new_params))
    kernel_params = nnx.state(model, nnx.All(nnx.Param,
        nnx.Not(nnx_utils.PathRegex(".*/(bias|scale|pos_embedding|input_embedding)")),
        lambda _, x: x.value.ndim > 1))
    return new_state, {"loss": loss, "grad_norm": optax.global_norm(grads),
                       "param_norm": optax.global_norm(kernel_params)}

def train():
    from scripts import train as upstream
    logging.basicConfig(level=logging.INFO)
    started = time.monotonic()
    cfg = config()
    (RUN / "train_config.txt").write_text(repr(cfg))
    dc = cfg.data.create(cfg.assets_dirs, cfg.model)
    order = np.load(RUN / "sample_order.npy", allow_pickle=False)
    source_resume = read(OLD / "resume.json")
    train_rng = jax.random.wrap_key_data(np.asarray(source_resume["train_rng_key_data"], dtype=np.uint32))
    _, init_rng = jax.random.split(jax.random.key(cfg.seed))
    mesh = sharding.make_mesh(cfg.fsdp_devices)
    data_sharding = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec(sharding.DATA_AXIS))
    replicated = jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec())
    manager, _ = checkpoints.initialize_checkpoint_dir(cfg.checkpoint_dir, keep_period=1, overwrite=False, resume=False)
    dataset = D.transform_dataset(OrderedDataset(PiperDataset(DATA, "train", 10), order[:2000]), dc)
    loader = D.DataLoaderImpl(dc, D.TorchDataLoader(dataset, 4, sharding=data_sharding,
        shuffle=False, num_workers=cfg.num_workers, seed=cfg.seed, num_batches=500))
    state, state_sharding = upstream.init_train_state(cfg, init_rng, mesh, resume=True)
    source_manager, _ = checkpoints.initialize_checkpoint_dir(OLD.parent, keep_period=1, overwrite=False, resume=True)
    try:
        state = checkpoints.restore_state(source_manager, state, loader, step=2010)
    finally:
        source_manager.close()
    jax.block_until_ready(state)
    gradient_parameters = sum(x.size for x in jax.tree.leaves(state.params.filter(cfg.trainable_filter)))
    fixed_parameters = sum(x.size for x in jax.tree.leaves(state.params.filter(nnx.All(cfg.trainable_filter, VISION))))
    report = dict(group="G", source_checkpoint=str(OLD), local_updates=0,
        optimizer_updates=int(state.step), full_optimizer_restored=True,
        optimizer_scalar_counters=[int(x) for x in jax.tree.leaves(state.opt_state)
            if x.ndim == 0 and np.issubdtype(x.dtype, np.integer)],
        train_rng_key_data=jax.random.key_data(train_rng).tolist(),
        gradient_parameters=gradient_parameters, effective_update_parameters=gradient_parameters-fixed_parameters,
        fixed_parameters=fixed_parameters, fixed_module="PaliGemma/img/.*",
        intervention="zero final updates after tx.update, before optax.apply_updates",
        visual_gradients_and_optimizer_buffers="original E rule",
        learning_rate=1e-6, schedule_decay_steps=5020, segment_end_local=500, segment_complete=False,
        initialization_seconds=time.monotonic()-started)
    save(RUN / "lora_training.json", report)
    print("TRAIN_INITIALIZED", json.dumps(report), flush=True)
    step_fn = jax.jit(functools.partial(train_step, cfg),
        in_shardings=(replicated, state_sharding, data_sharding),
        out_shardings=(state_sharding, replicated), donate_argnums=(1,))
    previous_end = time.monotonic()
    try:
        for local, batch in enumerate(loader, start=1):
            t0 = time.monotonic()
            with sharding.set_mesh(mesh):
                state, info = step_fn(train_rng, state, batch)
            values = {k: float(v) for k,v in jax.device_get(info).items()}
            row = dict(group="G", local_update=local, optimizer_update=int(state.step), **values,
                wall_time=time.time(), compute_seconds=time.monotonic()-t0,
                data_wait_seconds=t0-previous_end, learning_rate=1e-6,
                sample_offset_before=(local-1)*4, sample_indices=order[(local-1)*4:local*4].tolist(),
                sample_components=["original"]*4, rng_fold_in_step=4020+local-1)
            with (RUN / "lora_metrics.jsonl").open("a") as stream:
                stream.write(json.dumps(row, allow_nan=False)+"\n")
            if local == 1 or local % 10 == 0:
                save(RUN / "training_progress.json", row)
                print("UPDATE", json.dumps(row), flush=True)
            previous_end = time.monotonic()
        checkpoints.save_state(manager, state, loader, 500)
        manager.wait_until_finished()
        checkpoint = cfg.checkpoint_dir / "500"
        save(checkpoint / "resume.json", dict(local_updates=500, optimizer_updates=int(state.step),
            sample_offset=2000, sample_order_file=str(RUN / "sample_order.npy"),
            train_rng_key_data=jax.random.key_data(train_rng).tolist(),
            rng_rule="jax.random.fold_in(train_rng, cumulative optimizer state.step); 4020..4519",
            old_checkpoint=str(OLD), group="G"))
        report.update(local_updates=500, optimizer_updates=int(state.step), checkpoint=str(checkpoint),
            segment_complete=True, wall_seconds=time.monotonic()-started)
        save(RUN / "lora_training.json", report)
        print("CHECKPOINT_COMPLETE G500", flush=True)
    finally:
        manager.close()

if __name__ == "__main__":
    train()
