import json
from dataclasses import replace

import httpx
import pytest

from gaia_shared.client import evaluate
from gaia_shared.server import create_app
from gaia_shared.service import SharedService


async def test_full_client_scoring_and_resume_without_new_questions(cfg, factory, monkeypatch):
    class Session:
        def __init__(self, run_id, sandbox, request, directory):
            self.request = request

        async def run(self):
            return {"answer": "42"}

        def close(self):
            pass

    directory = cfg.root / "data" / "GAIA" / "2023" / "validation"
    directory.mkdir(parents=True)
    (directory / "metadata.jsonl").write_text(
        "\n".join(
            json.dumps({"task_id": str(i), "Level": 1, "Question": "6*7?", "Final answer": "42"})
            for i in range(3)
        )
    )
    cfg = replace(cfg, gaia={**cfg.gaia, "limit": 1})
    service = SharedService(cfg, factory, Session)
    app = create_app(service, "token")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.ASGITransport(app=app), **kwargs),
    )
    report = await evaluate(cfg, "token", "http://test")
    assert report["accuracy"] == 1.0 and report["instances"] == 1
    report = await evaluate(cfg, "token", "http://test")
    assert len(factory.created) == 1  # Does not advance the 1-question limit on resume.
    changed = replace(cfg, gaia={**cfg.gaia, "limit": 2})
    with pytest.raises(ValueError, match="changed"):
        await evaluate(changed, "token", "http://test")


async def test_client_rejects_wrong_server_profile(cfg, factory, monkeypatch):
    class Session:
        pass

    directory = cfg.root / "data" / "GAIA" / "2023" / "validation"
    directory.mkdir(parents=True)
    (directory / "metadata.jsonl").write_text("")
    server_cfg = replace(cfg, llm={**cfg.llm, "model": "another-model"})
    app = create_app(SharedService(server_cfg, factory, Session), "token")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
    )
    with pytest.raises(ValueError, match="does not match"):
        await evaluate(cfg, "token", "http://test")
