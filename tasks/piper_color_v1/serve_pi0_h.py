"""One independent H policy/RNG instance per localhost port."""
import argparse, json, logging
from pathlib import Path
import jax
from openpi.policies import policy_config as upstream
from openpi.shared import normalize
from openpi.serving.websocket_policy_server import WebsocketPolicyServer
from serve import SeededPolicy
from train_pi0_h import config
from h_common import CHECKPOINT, NORM

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    cfg = config()
    policy = upstream.create_trained_policy(cfg, CHECKPOINT, norm_stats=normalize.load(NORM), sample_kwargs={'num_steps': 10})
    policy._rng = jax.random.key(42)
    metadata = {**cfg.policy_metadata, 'model_family': 'pi0', 'mode': 'lora', 'checkpoint': str(CHECKPOINT),
        'norm_stats': str(NORM), 'reset_seed_supported': True, 'action_horizon': 10, 'flow_denoising_steps': 10}
    print('MODEL_LOADED ' + json.dumps(metadata), flush=True)
    WebsocketPolicyServer(SeededPolicy(policy), host='127.0.0.1', port=args.port, metadata=metadata).serve_forever()
