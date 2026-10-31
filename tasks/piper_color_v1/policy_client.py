"""Bounded connection to the OpenPI wire protocol, without a reconnect loop."""
import websockets.sync.client
from openpi_client import msgpack_numpy


class PolicyClient:
    def __init__(self, host, port, timeout=300):
        self.timeout = timeout
        self.ws = websockets.sync.client.connect(
            f"ws://{host}:{port}", compression=None, max_size=None,
            open_timeout=10, close_timeout=5, ping_interval=None, proxy=None)
        self.metadata = msgpack_numpy.unpackb(self.ws.recv(timeout=10))
        self.packer = msgpack_numpy.Packer()

    def infer(self, obs):
        self.ws.send(self.packer.pack(obs))
        response = self.ws.recv(timeout=self.timeout)
        if isinstance(response, str):
            raise RuntimeError(response)
        return msgpack_numpy.unpackb(response)

    def reset_seed(self, seed):
        if not self.metadata.get("reset_seed_supported"):
            raise RuntimeError("Server does not support explicit RNG reset")
        if self.infer({"reset_seed": int(seed)}).get("reset_seed") != int(seed):
            raise RuntimeError("Unexpected RNG reset acknowledgement")

    def close(self):
        self.ws.close()
