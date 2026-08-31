"""SDK conversations stay in this process; only the bound tool talks to Docker."""

import base64
import json
import mimetypes
from pathlib import Path
from threading import Lock

from openhands.sdk import (
    LLM,
    Action,
    Agent,
    ImageContent,
    Message,
    Observation,
    TextContent,
    ToolDefinition,
)
from openhands.sdk.context import AgentContext
from openhands.sdk.conversation import LocalConversation
from openhands.sdk.tool import Tool, ToolExecutor, register_tool
from pydantic import Field, SecretStr

from .io import append_json, stamp

_bindings = {}
_lock = Lock()


class SandboxCommand(Action):
    command: str = Field(description="Bash command to run in this task's isolated sandbox")


class CommandObservation(Observation):
    output: str

    @property
    def to_llm_content(self):
        return [TextContent(text=self.output)]


class SandboxExecutor(ToolExecutor):
    def __init__(self, sandbox):
        self.sandbox = sandbox

    def __call__(self, action, conversation=None):
        return CommandObservation(output=json.dumps(self.sandbox.execute(action.command)))


class SandboxCommandTool(ToolDefinition):
    @classmethod
    def create(cls, conv_state, binding_id: str):
        # binding_id is supplied by trusted server code, never by the model.
        with _lock:
            sandbox = _bindings[binding_id]
        return [
            cls(
                description=(
                    "Execute bash in your private Linux container at /workspace. "
                    "Use Python to read/write files, requests for webpages and "
                    "Playwright for Chromium browsing. Commands do not retain shell "
                    "cwd/env between calls; files persist throughout this task. "
                    "You have no access to the agent server or other tasks."
                ),
                action_type=SandboxCommand,
                observation_type=CommandObservation,
                executor=SandboxExecutor(sandbox),
            )
        ]


register_tool(SandboxCommandTool.name, SandboxCommandTool)


def extract_answer(events):
    import re

    for event in reversed(events):
        if event.get("source") != "agent":
            continue
        action = event.get("action", {})
        if isinstance(action, dict) and action.get("message"):
            raw = str(action["message"])
        else:
            content = (event.get("llm_message") or {}).get("content", [])
            raw = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
        if raw:
            matches = re.findall(r"<solution>(.*?)</solution>", raw, flags=re.S)
            return matches[-1].strip() if matches else raw.strip()
    return ""


class SDKSession:
    def __init__(self, cfg, key, run_id, sandbox, request, run_dir: Path):
        self.run_id = run_id
        self.events = []
        self.conversation = None
        with _lock:
            _bindings[run_id] = sandbox
        try:
            llm = LLM(
                model=cfg.llm["model"],
                base_url=cfg.llm["base_url"],
                api_key=SecretStr(key),
                usage_id=f"gaia-{run_id}",
                max_output_tokens=cfg.llm["max_output_tokens"],
                timeout=cfg.llm["timeout"],
                num_retries=1,
            )
            agent = Agent(
                llm=llm,
                tools=[Tool(name=SandboxCommandTool.name, params={"binding_id": run_id})],
                include_default_tools=["FinishTool", "ThinkTool"],
                auto_attach_vision_tool=False,
                agent_context=AgentContext(
                    load_user_skills=False,
                    load_project_skills=False,
                    load_public_skills=False,
                    system_message_suffix=(
                        "Solve the GAIA question using only your private sandbox. "
                        "Do not ask the user for help. Return the final answer with "
                        "the finish tool, enclosed in <solution>...</solution>. "
                        "Follow the question's formatting exactly. "
                        "Only the sandbox command tool can access task files."
                    ),
                ),
            )
            state_dir = run_dir / "sdk-state"
            state_dir.mkdir()

            def callback(event):
                data = event.model_dump(mode="json")
                self.events.append(data)
                append_json(run_dir / "events.jsonl", {**stamp(), "event": data})

            self.conversation = LocalConversation(
                agent=agent,
                workspace=str(state_dir),
                callbacks=[callback],
                profile_store_dir=str(run_dir / "sdk-profiles"),
                max_iteration_per_run=cfg.llm["max_iterations"],
                visualizer=None,
                delete_on_close=False,
            )
            text = request.question
            if request.attachments:
                text += "\nAttachments in your sandbox: " + ", ".join(
                    "/workspace/" + a.name for a in request.attachments
                )
            content = [TextContent(text=text)]
            for attachment in request.attachments:
                mime = mimetypes.guess_type(attachment.name)[0]
                if mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                    # Input images go to the model; the same file is also in the sandbox.
                    base64.b64decode(attachment.data_base64, validate=True)
                    content.append(
                        ImageContent(image_urls=[f"data:{mime};base64,{attachment.data_base64}"])
                    )
            self.conversation.send_message(Message(role="user", content=content))
        except BaseException:
            self.close()
            raise

    async def run(self):
        await self.conversation.arun()
        status = self.conversation.state.execution_status.value
        return {
            "answer": extract_answer(self.events),
            "conversation_status": status,
            "llm_metrics": self.conversation.conversation_stats.get_combined_metrics().model_dump(
                mode="json"
            ),
            "tool_calls": sum(e.get("kind") == "ActionEvent" for e in self.events),
        }

    def close(self):
        try:
            if self.conversation is not None:
                self.conversation.close()
        finally:
            with _lock:
                _bindings.pop(self.run_id, None)
