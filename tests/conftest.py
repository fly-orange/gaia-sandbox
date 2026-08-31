import os
from dataclasses import replace
from pathlib import Path

import pytest

from gaia_shared.config import load

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"


@pytest.fixture
def cfg(tmp_path):
    config = load(Path(__file__).parents[1] / "config.example.toml")
    return replace(config, root=tmp_path, server={**config.server, "metrics_interval": 0.01})


class FakeSandbox:
    def __init__(self, run_id):
        self.id = run_id
        self.closed = False
        self.commands = []
        self.files = []

    def upload(self, attachment):
        self.files.append(attachment.name)

    def execute(self, command):
        self.commands.append(command)
        return {"exit_code": 0, "stdout": self.id, "stderr": ""}

    def stats(self):
        return {"container_id": self.id, "cpu_seconds": 0.5, "memory_bytes": 100}

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self):
        self.created = []

    def create(self, run_id):
        box = FakeSandbox(run_id)
        self.created.append(box)
        return box


@pytest.fixture
def factory():
    return FakeFactory()
