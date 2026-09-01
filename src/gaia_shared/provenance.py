import hashlib
import json
from pathlib import Path


def profile(cfg):
    return {
        "llm": cfg.llm,
        "sandbox": cfg.sandbox,
        "agent": cfg.agent,
        "request_timeout": cfg.server["request_timeout"],
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_fingerprint(root: Path):
    digest = hashlib.sha256()
    lockfile = root / "uv.lock"
    if lockfile.exists():
        digest.update(lockfile.read_bytes())
    for folder in (root / "src", root / "vendor"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and not any(
                part.endswith(".egg-info") for part in path.parts
            ):
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()
