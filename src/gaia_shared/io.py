import json
import time
from pathlib import Path


def append_json(path: Path, value: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")


def stamp():
    return {"timestamp": time.time(), "monotonic": time.monotonic()}
