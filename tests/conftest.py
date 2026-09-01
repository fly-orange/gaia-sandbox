import os
from dataclasses import replace
from pathlib import Path

import pytest
from openhands.sdk import Action, Observation, ToolDefinition
from openhands.sdk.tool import ToolExecutor, register_tool

from gaia_shared.config import load


class TestSandboxAction(Action):
    command: str


class TestSandboxObservation(Observation):
    output: str = ""


class TestSandboxExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        return TestSandboxObservation.from_text("unused", output="unused")


class TestSandboxTool(ToolDefinition):
    @classmethod
    def create(cls, conv_state):
        return [cls(
            description="test sandbox", action_type=TestSandboxAction,
            observation_type=TestSandboxObservation, executor=TestSandboxExecutor(),
        )]


register_tool(TestSandboxTool.name, TestSandboxTool)


class FakeWorker:
    def __init__(self, sandbox):
        self.sandbox = sandbox

    def call(self, method, payload, timeout):
        if method == "describe":
            return {"tools": [self.definition()]}
        if method == "call":
            self.sandbox.commands.append(payload["action"]["command"])
            return {"observation": {
                "content": [{"text": self.sandbox.id}], "is_error": False,
                "original": {"output": self.sandbox.id},
            }}
        raise AssertionError(method)

    @staticmethod
    def definition():
        tool = TestSandboxTool.create(None)[0]
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.to_mcp_tool()["inputSchema"],
            "annotations": None,
        }

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
        self.worker = None

    def start_tools(self, config, run_dir):
        self.worker = FakeWorker(self)
        return {
            "worker_pid": 1000,
            "tools": [self.worker.definition()],
            "skills": [],
            "source_sha256": config["source_sha256"],
        }

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
