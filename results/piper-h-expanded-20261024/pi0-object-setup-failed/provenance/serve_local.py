"""Serve an official LIBERO checkpoint. This starts inference, not training."""
import argparse
import dataclasses
import json
import logging
from pathlib import Path


def _read_json(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read checkpoint metadata {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Checkpoint metadata must be a JSON object: {path}")
    return value


def validate_checkpoint(root, checkpoint, config_name, backend):
    """Check local files before importing runtimes or allocating model memory."""
    checkpoint = checkpoint.resolve()
    if not checkpoint.is_dir():
        raise ValueError(f"Missing checkpoint: {checkpoint}. Run download_checkpoints.py first.")
    pytorch_weights = checkpoint / "model.safetensors"
    if backend == "jax" and pytorch_weights.exists():
        # Upstream auto-detects PyTorch from this file regardless of our flag.
        raise ValueError("Checkpoint contains model.safetensors: select --backend pytorch or a JAX-only directory.")
    if backend == "pytorch" and (not pytorch_weights.is_file() or pytorch_weights.stat().st_size <= 8):
        raise ValueError("PyTorch requires a nonempty converted model.safetensors checkpoint; see README.")
    if backend == "jax" and not (checkpoint / "params").is_dir():
        raise ValueError("JAX checkpoint must contain params/.")

    official_root = (root / "checkpoints").resolve()
    official_names = {"pi0_libero", "pi05_libero", "pi0_base", "pi05_base"}
    is_official = checkpoint.parent == official_root and checkpoint.name in official_names
    validation = "structure_only"
    if is_official:
        if checkpoint.name != config_name:
            raise ValueError(f"Checkpoint {checkpoint.name} does not match the requested config {config_name}.")
        manifest = _read_json(root / "results" / f"checkpoints-manifest-{config_name}.json")
        status = _read_json(root / "results" / "checkpoints-status.json")
        objects = manifest.get("objects", [])
        group = status.get("checkpoints", {}).get(config_name, {})
        if not objects or not group.get("complete") or group.get("verified_files") != len(objects):
            raise ValueError(
                f"Checkpoint {config_name} is not fully verified in checkpoints-status.json; "
                f"finish download_checkpoints.py --checkpoint {config_name} before serving."
            )
        records = {item["name"]: item for item in group.get("objects", [])}
        prefix = f"checkpoints/{config_name}/"
        for item in objects:
            name = item["name"]
            if not name.startswith(prefix):
                raise ValueError(f"Unexpected manifest object: {name}")
            path = (checkpoint / name[len(prefix):]).resolve()
            if not path.is_relative_to(checkpoint):
                raise ValueError(f"Manifest object escapes checkpoint directory: {name}")
            record = records.get(name, {})
            expected_size = int(item["size"])
            if record.get("state") != "verified" or record.get("expected_bytes") != expected_size:
                raise ValueError(f"Missing verified download record for {name}")
            for checksum in ("crc32c", "md5Hash"):
                if item.get(checksum) and record.get(checksum) != item[checksum]:
                    raise ValueError(f"Download verification record does not match manifest for {name}")
            if not path.is_file() or path.stat().st_size != expected_size:
                raise ValueError(f"Verified checkpoint file is missing or has changed size: {path}")
        validation = (
            "download_record_and_file_sizes" if backend == "jax"
            else "source_download_record_and_converted_structure_only"
        )

    if backend == "jax":
        metadata_path = checkpoint / "params" / "_METADATA"
        if not metadata_path.is_file() or metadata_path.stat().st_size == 0:
            raise ValueError(f"Missing Orbax parameter metadata: {metadata_path}")
    stats_path = checkpoint / "assets" / "physical-intelligence" / "libero" / "norm_stats.json"
    stats = _read_json(stats_path)
    if not isinstance(stats, dict) or not {"state", "actions"}.issubset(stats.get("norm_stats", {})):
        raise ValueError(f"Missing LIBERO state/action normalization statistics: {stats_path}")
    return {"checkpoint": str(checkpoint), "backend": backend, "validation": validation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("pi0", "pi05"), default="pi05")
    parser.add_argument("--backend", choices=("jax", "pytorch"), default="jax")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check-only", action="store_true", help="Validate checkpoint files without importing ML runtimes.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config_name = f"{args.model}_libero"
    checkpoint = args.checkpoint or root / "checkpoints" / (
        config_name + ("_pytorch" if args.backend == "pytorch" else "")
    )
    try:
        checked = validate_checkpoint(root, checkpoint, config_name, args.backend)
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.error(str(error))
    if args.check_only:
        print(json.dumps(checked, indent=2))
        return
    if checked["validation"] != "download_record_and_file_sizes":
        logging.warning("Custom/converted weights passed structural checks only; their contents have no download verification record.")
    from openpi.policies import policy_config
    from openpi.serving import websocket_policy_server
    from openpi.training import config

    cfg = config.get_config(config_name)
    # Avoid autotuning/compilation memory spikes in the optional PyTorch path.
    if args.backend == "pytorch":
        cfg = dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, pytorch_compile_mode=None))
    policy = policy_config.create_trained_policy(cfg, checkpoint)
    logging.info("Serving %s / %s on %s:%d", config_name, args.backend, args.host, args.port)
    websocket_policy_server.WebsocketPolicyServer(
        policy=policy, host=args.host, port=args.port, metadata=policy.metadata
    ).serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
