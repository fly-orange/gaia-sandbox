"""One host Agent loop; upstream tools execute in the task's container worker."""

import mimetypes
import re
from pathlib import Path

from openhands.sdk import LLM, Agent, ImageContent, Message, TextContent, Tool
from openhands.sdk.context import AgentContext
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.conversation import LocalConversation
from openhands.sdk.event import ActionEvent, MessageEvent
from openhands.sdk.tool.builtins.finish import FinishAction
from pydantic import SecretStr

from .benchmark import fake_user_response, instruction
from .io import append_json, stamp
from .skills import load_skills
from .tool_bridge import SandboxToolSet, bind_tools, unbind_tools


def extract_answer(events):
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
        self.run_id, self.events, self.conversation = run_id, [], None
        definitions = sandbox.worker.call(
            "describe", {}, cfg.sandbox["tool_call_timeout"]
        )
        bind_tools(
            run_id,
            definitions["tools"],
            sandbox.worker,
            cfg.sandbox["tool_call_timeout"],
            run_dir / "tool-calls.jsonl",
        )
        try:
            llm = LLM(
                model=cfg.llm["model"],
                base_url=cfg.llm["base_url"],
                api_key=SecretStr(key),
                usage_id=f"gaia-{run_id}",
                max_output_tokens=cfg.llm["max_output_tokens"],
                timeout=cfg.llm["timeout"],
                num_retries=cfg.llm["num_retries"],
                temperature=cfg.llm["temperature"],
                drop_params=True,
                modify_params=True,
                native_tool_calling=True,
            )
            condenser = None
            if cfg.agent["enable_condenser"]:
                condenser = LLMSummarizingCondenser(
                    llm=llm.model_copy(update={"usage_id": "condenser"}),
                    max_size=cfg.agent["condenser_max_size"],
                    keep_first=cfg.agent["condenser_keep_first"],
                )
            skills = (
                load_skills(cfg.root / "vendor/extensions")
                if cfg.agent["public_skills"]
                else []
            )
            context = AgentContext(skills=skills) if skills else None
            agent = Agent(
                llm=llm,
                tools=[Tool(name=SandboxToolSet.name, params={"binding_id": run_id})],
                system_prompt_kwargs={"cli_mode": True, "enable_browser": True},
                agent_context=context,
                condenser=condenser,
                auto_attach_skill_tool=False,
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
            content = [TextContent(text=instruction(request))]
            for attachment in request.attachments:
                mime = mimetypes.guess_type(attachment.name)[0]
                if mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                    content.append(
                        ImageContent(
                            image_urls=[
                                f"data:{mime};base64,{attachment.data_base64}"
                            ]
                        )
                    )
            self.conversation.send_message(Message(role="user", content=content))
            self.max_fake_responses = cfg.agent["max_fake_responses"]
        except BaseException:
            self.close()
            raise

    def _last_agent_finished(self):
        for event in reversed(self.conversation.state.events):
            if isinstance(event, ActionEvent):
                return isinstance(event.action, FinishAction)
        return False

    def _last_agent_message(self):
        for event in reversed(self.conversation.state.events):
            if isinstance(event, MessageEvent) and event.source == "agent":
                return True
            if isinstance(event, ActionEvent):
                return False
        return False

    async def run(self):
        fake_responses = 0
        while True:
            await self.conversation.arun()
            status = self.conversation.state.execution_status.value
            if (
                status != "finished"
                or self._last_agent_finished()
                or not self._last_agent_message()
            ):
                break
            if fake_responses >= self.max_fake_responses:
                break
            self.conversation.send_message(fake_user_response(fake_responses))
            fake_responses += 1
        return {
            "answer": extract_answer(self.events),
            "conversation_status": status,
            "llm_metrics": self.conversation.conversation_stats.get_combined_metrics().model_dump(
                mode="json"
            ),
            "tool_calls": sum(e.get("kind") == "ActionEvent" for e in self.events),
            "fake_user_responses": fake_responses,
        }

    def close(self):
        try:
            if self.conversation is not None:
                self.conversation.close()
        finally:
            unbind_tools(self.run_id)
