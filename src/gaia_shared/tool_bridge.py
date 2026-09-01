"""Transfer upstream tool schemas and rendered observations, never host execution."""

import json
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future

from openhands.sdk import Action, Observation, ToolDefinition
from openhands.sdk.tool import ToolAnnotations, ToolExecutor, register_tool
from pydantic import Field

from .io import append_json, stamp


class SandboxObservation(Observation):
    original: dict = Field(default_factory=dict)

    @property
    def to_llm_content(self):
        # Rendering/truncation may write files; it is performed in the sandbox.
        return self.content


class WorkerConnection:
    MAX_MESSAGE = 32 * 1024 * 1024

    def __init__(self, command, log_path, *, env=None):
        self._log = log_path.open("wb")
        try:
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._log, env=env,
            )
        except BaseException:
            self._log.close()
            raise
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending = {}
        self._closed = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        try:
            while line := self.process.stdout.readline(self.MAX_MESSAGE + 1):
                if len(line) > self.MAX_MESSAGE or not line.endswith(b"\n"):
                    raise RuntimeError("Worker response exceeds transport limit")
                reply = json.loads(line)
                with self._lock:
                    future = self._pending.pop(reply["id"], None)
                if future is not None:
                    if "error" in reply:
                        future.set_exception(RuntimeError(reply["error"]))
                    else:
                        future.set_result(reply["result"])
            raise RuntimeError("Sandbox tool worker disconnected")
        except Exception as exc:
            with self._lock:
                self._closed = True
                pending, self._pending = self._pending, {}
            for future in pending.values():
                future.set_exception(exc)

    def call(self, method, payload, timeout):
        request_id = uuid.uuid4().hex
        future = Future()
        message = json.dumps({"id": request_id, "method": method, "payload": payload}).encode() + b"\n"
        if len(message) > self.MAX_MESSAGE:
            raise ValueError("Worker request exceeds transport limit")
        with self._lock:
            if self._closed:
                raise RuntimeError("Sandbox tool worker is closed")
            self._pending[request_id] = future
        try:
            with self._write_lock:
                self.process.stdin.write(message)
                self.process.stdin.flush()
            return future.result(timeout=timeout)
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def close(self):
        # Container removal terminates tools as well; this reaps the docker client.
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self._reader.join(timeout=2)
        finally:
            if self.process.stdin is not None:
                self.process.stdin.close()
            if self.process.stdout is not None:
                self.process.stdout.close()
            self._log.close()


class RemoteExecutor(ToolExecutor):
    def __init__(self, name, connection, timeout, log_path, log_lock):
        self.name, self.connection, self.timeout = name, connection, timeout
        self.log_path, self.log_lock = log_path, log_lock

    def __call__(self, action, conversation=None):
        start = time.monotonic()
        outcome = "transport_error"
        try:
            result = self.connection.call(
                "call", {"name": self.name, "action": action.model_dump(mode="json")}, self.timeout
            )
            observation = SandboxObservation.model_validate(result["observation"])
            outcome = "error" if observation.is_error else "ok"
            if conversation is not None and self.name == "invoke_skill" and not observation.is_error:
                name = action.name
                if name not in conversation.state.invoked_skills:
                    conversation.state.invoked_skills.append(name)
            return observation
        finally:
            with self.log_lock:
                append_json(self.log_path, {
                    **stamp(), "tool": self.name, "status": outcome,
                    "roundtrip_seconds": time.monotonic() - start,
                })


_bindings = {}
_binding_lock = threading.Lock()


def bind_tools(binding_id, definitions, connection, timeout, log_path):
    # Import schemas only. No upstream Tool.create() executes in this process.
    log_lock = threading.Lock()
    tools = []
    for index, definition in enumerate(definitions):
        name = definition["name"]
        action_type = Action.from_mcp_schema(
            f"SandboxToolAction{index}", definition["input_schema"]
        )
        tool_class = type(f"SandboxProxy{index}Tool", (SandboxProxyTool,), {"name": name})
        tool = tool_class(
            description=definition["description"],
            action_type=action_type,
            observation_type=None,
            annotations=(
                ToolAnnotations.model_validate(definition["annotations"])
                if definition["annotations"] is not None
                else None
            ),
            executor=RemoteExecutor(name, connection, timeout, log_path, log_lock),
        )
        tools.append(tool)
    with _binding_lock:
        _bindings[binding_id] = tools


def unbind_tools(binding_id):
    with _binding_lock:
        _bindings.pop(binding_id, None)


class SandboxToolSet(ToolDefinition):
    @classmethod
    def create(cls, conv_state, binding_id):
        with _binding_lock:
            return list(_bindings[binding_id])


class SandboxProxyTool(ToolDefinition):
    @classmethod
    def create(cls, conv_state):
        raise RuntimeError("Sandbox proxy tools are created from worker schemas")


register_tool(SandboxToolSet.name, SandboxToolSet)
