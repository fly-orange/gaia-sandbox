import asyncio
import json

from litellm.types.utils import ModelResponse
from openhands.sdk import LLM

from gaia_shared.agent import SDKSession
from gaia_shared.schema import TaskRequest
from gaia_shared.service import SharedService


async def test_real_sdk_two_conversations_bound_to_distinct_sandboxes(cfg, factory, monkeypatch):
    calls = {}

    async def completion(self, messages, **kwargs):
        count = calls.get(self.usage_id, 0)
        calls[self.usage_id] = count + 1
        name = "test_sandbox" if count == 0 else "finish"
        args = (
            {"command": "echo isolated"} if count == 0 else {"message": "<solution>42</solution>"}
        )
        response = ModelResponse(
            model=self.model,
            choices=[
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call-{count}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                        ],
                    },
                }
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        return self._build_completion_result(response)

    monkeypatch.setattr(LLM, "acompletion", completion)
    service = SharedService(
        cfg,
        factory,
        lambda run_id, sandbox, request, directory: SDKSession(
            cfg, "fake-key", run_id, sandbox, request, directory
        ),
    )
    results = await asyncio.gather(
        *(service.execute(TaskRequest(task_id=str(i), question="6*7?")) for i in range(2))
    )
    assert [r["status"] for r in results] == ["completed", "completed"], results
    assert [r["answer"] for r in results] == ["42", "42"]
    assert len(calls) == 2
    assert all(b.commands == ["echo isolated"] for b in factory.created)
    assert all(b.closed for b in factory.created)
    for r in results:
        events_path = service.root / r["run_id"] / "events.jsonl"
        events = [
            json.loads(line)["event"]
            for line in events_path.read_text(encoding="utf-8").splitlines()
        ]
        system = next(e for e in events if e["kind"] == "SystemPromptEvent")
        kinds = {t["kind"] for t in system["tools"]}
        assert kinds == {"SandboxProxy0Tool", "FinishTool", "ThinkTool"}


async def test_real_sdk_deadline_classified_as_timeout(cfg, factory, monkeypatch):
    from dataclasses import replace

    async def slow(self, messages, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(LLM, "acompletion", slow)
    cfg = replace(cfg, server={**cfg.server, "request_timeout": 0.03})
    service = SharedService(
        cfg,
        factory,
        lambda run_id, sandbox, request, directory: SDKSession(
            cfg, "fake", run_id, sandbox, request, directory
        ),
    )
    result = await service.execute(TaskRequest(task_id="slow", question="wait"))
    assert result["status"] == "timeout", result
    assert factory.created[0].closed
