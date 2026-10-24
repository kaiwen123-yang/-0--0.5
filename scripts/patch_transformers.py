"""Apply exactly the upstream openpi patch, only to this isolated environment."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import transformers

root = Path(__file__).resolve().parents[1]
assert importlib.metadata.version("transformers") == "4.53.2"
target = Path(transformers.__file__).resolve().parent
assert target.is_relative_to(root / "envs/openpi"), f"Refusing unexpected target {target}"
source = root / "repos/openpi/src/openpi/models_pytorch/transformers_replace"
manifest = {}
for path in source.rglob("*.py"):
    relative = path.relative_to(source)
    dest = target / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest
    manifest[str(relative)] = digest
(root / "results/transformers-patch.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Applied {len(manifest)} upstream files to {target}")
