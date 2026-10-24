"""Check OpenPI server <-> LIBERO client environments with synthetic CPU data.

No policy weights, simulator, GPU, or robot are used. The test server binds only
to loopback and is terminated by the parent when the check finishes.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def serve(port):
    import numpy as np
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer
    from openpi_client.base_policy import BasePolicy

    class SyntheticPolicy(BasePolicy):
        def infer(self, obs):
            for key in ("observation/image", "observation/wrist_image"):
                assert obs[key].shape == (224, 224, 3)
                assert obs[key].dtype == np.uint8
            assert obs["observation/state"].shape == (8,)
            assert obs["prompt"] == "CPU transport check"
            return {"actions": np.zeros((10, 7), dtype=np.float32)}

    WebsocketPolicyServer(SyntheticPolicy(), host="127.0.0.1", port=port,
                          metadata={"synthetic_cpu_check": True}).serve_forever()


def query(port):
    import numpy as np
    from openpi_client.websocket_client_policy import WebsocketClientPolicy

    client = WebsocketClientPolicy(host="127.0.0.1", port=port)
    try:
        assert client.get_server_metadata() == {"synthetic_cpu_check": True}
        observation = {
            "observation/image": np.zeros((224, 224, 3), dtype=np.uint8),
            "observation/wrist_image": np.ones((224, 224, 3), dtype=np.uint8),
            "observation/state": np.zeros(8, dtype=np.float64),
            "prompt": "CPU transport check",
        }
        for _ in range(2):
            response = client.infer(observation)
            assert response["actions"].shape == (10, 7)
            assert response["actions"].dtype == np.float32
            assert np.isfinite(response["actions"]).all()
        print(json.dumps({"status": "passed", "round_trips": 2,
                          "server_environment": "openpi", "client_environment": "libero",
                          "action_shape": [10, 7], "synthetic_policy": True,
                          "weights_loaded": False, "gpu_used": False,
                          "scope": "WebSocket and NumPy serialization only; not model inference"}))
    finally:
        client._ws.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("parent", "server", "client"), default="parent")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.mode == "server":
        return serve(args.port)
    if args.mode == "client":
        return query(args.port)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", JAX_PLATFORMS="cpu")
    script = str(Path(__file__).resolve())
    launcher = str(ROOT / "scripts/run.sh")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (ROOT / "logs/policy-transport-server.log").open("w") as log:
        process = subprocess.Popen([launcher, "openpi", script, "--mode", "server", "--port", str(port)],
                                   cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Transport test server exited; inspect its log")
                try:
                    with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                        assert response.read() == b"OK\n"
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Transport test server did not become ready")
                    time.sleep(0.1)
            result = subprocess.run([launcher, "libero", script, "--mode", "client", "--port", str(port)],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=15, check=True)
            payload = json.loads(result.stdout)
            (ROOT / "results/policy-transport-check.json").write_text(json.dumps(payload, indent=2) + "\n")
            print(json.dumps(payload, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
