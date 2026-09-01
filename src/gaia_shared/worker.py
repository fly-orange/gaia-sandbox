"""Per-sandbox tool executor. No Agent, Conversation, model client, or HTTP server."""

import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from openhands.sdk.conversation.state import ConversationState
from openhands.sdk.mcp import create_mcp_tools
from openhands.sdk.tool import resolve_tool
from openhands.sdk.tool.builtins.invoke_skill import InvokeSkillTool
from openhands.tools.preset.default import get_default_tools

from .provenance import source_fingerprint
from .skills import load_skills


class VisionCapabilities:
    def __init__(self, enabled):
        self.enabled = enabled

    def vision_is_active(self):
        return self.enabled


class ToolWorker:
    def __init__(self):
        self.tools = {}
        self.mcp = None
        self.conversation = None

    def initialize(self, config):
        if self.tools:
            raise RuntimeError("A sandbox worker belongs to exactly one task")
        root = Path(__file__).resolve().parents[2]
        if source_fingerprint(root) != config["source_sha256"]:
            raise RuntimeError("Sandbox source/lock differs from server; rebuild the image")
        directory = Path(config.get("workspace", "/workspace"))
        persistence = directory / ".gaia"
        persistence.mkdir(parents=True, exist_ok=True)
        skills = load_skills(root / "vendor/extensions") if config["agent"]["public_skills"] else []
        # Tool factories require this state view, not a running Agent or LLM.
        state = SimpleNamespace(
            workspace=SimpleNamespace(working_dir=str(directory)),
            persistence_dir=str(persistence),
            env_observation_persistence_dir=str(persistence / "observations"),
            agent=SimpleNamespace(
                llm=VisionCapabilities(config["vision"]),
                agent_context=SimpleNamespace(skills=skills),
            ),
            invoked_skills=[],
        )
        self.conversation = SimpleNamespace(state=state)
        for spec in get_default_tools(enable_browser=config.get("browser", True)):
            for tool in resolve_tool(spec, cast(ConversationState, state)):
                self.tools[tool.name] = tool
        if any(s.is_agentskills_format and not s.disable_model_invocation for s in skills):
            for tool in InvokeSkillTool.create(cast(ConversationState, state)):
                self.tools[tool.name] = tool
        servers = {}
        if config["agent"]["fetch"]:
            servers["fetch"] = {"command": "/opt/fetch/bin/mcp-server-fetch"}
        if config["agent"]["tavily"]:
            if not config.get("tavily_key"):
                raise ValueError("TAVILY_API_KEY is required")
            servers["tavily"] = {
                "command": "/opt/tavily/node_modules/.bin/tavily-mcp",
                "env": {"TAVILY_API_KEY": config["tavily_key"]},
            }
        if servers:
            self.mcp = create_mcp_tools(
                {"mcpServers": servers}, timeout=config["agent"]["mcp_init_timeout"]
            )
            for tool in self.mcp.tools:
                if tool.name in self.tools:
                    raise ValueError(f"Duplicate tool: {tool.name}")
                self.tools[tool.name] = tool
        return {
            "worker_pid": os.getpid(), "source_sha256": config["source_sha256"],
            "tools": self._describe_tools(),
            "skills": [s.model_dump(mode="json") for s in skills],
        }

    def _describe_tools(self):
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.to_mcp_tool()["inputSchema"],
                "annotations": (
                    tool.annotations.model_dump(mode="json")
                    if tool.annotations is not None
                    else None
                ),
            }
            for tool in self.tools.values()
        ]

    def call(self, payload):
        tool = self.tools[payload["name"]]
        raw_action = payload["action"]
        action = tool.action_from_arguments(
            {key: value for key, value in raw_action.items() if key != "kind"}
        )
        observation = tool(action, self.conversation)
        rendered = [c.model_dump(mode="json") for c in observation.to_llm_content]
        return {"observation": {
            "content": rendered, "is_error": observation.is_error,
            "original": observation.model_dump(mode="json"),
        }}

    def describe(self):
        return {"tools": self._describe_tools()}

    def close(self):
        closed = set()
        for tool in self.tools.values():
            if tool.executor is not None and id(tool.executor) not in closed:
                closed.add(id(tool.executor))
                tool.executor.close()
        if self.mcp is not None:
            self.mcp.sync_close()


def main():
    # Reserve a protocol fd; even third-party subprocess stdout goes to stderr.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    worker = ToolWorker()
    write_lock = threading.Lock()

    def respond(request):
        try:
            method = request["method"]
            if method == "initialize":
                result = worker.initialize(request["payload"])
            elif method == "call":
                result = worker.call(request["payload"])
            elif method == "describe":
                result = worker.describe()
            else:
                raise ValueError(f"Unknown worker method: {method}")
            response = {"id": request["id"], "result": result}
        except Exception as exc:
            # Initialization exceptions can include MCP env; never echo request/config.
            traceback.print_exc(file=sys.stderr)
            response = {"id": request["id"], "error": f"Tool worker failed: {type(exc).__name__}"}
        with write_lock:
            protocol.write(json.dumps(response) + "\n")

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for line in sys.stdin.buffer:
                if len(line) > 32 * 1024 * 1024:
                    raise ValueError("Request too large")
                request = json.loads(line)
                if request["method"] == "initialize":
                    respond(request)
                else:
                    pool.submit(respond, request)
    finally:
        worker.close()


if __name__ == "__main__":
    main()
