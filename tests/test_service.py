import asyncio
import os
from dataclasses import replace

import httpx
import pytest

from gaia_shared.schema import TaskRequest
from gaia_shared.server import create_app
from gaia_shared.service import SharedService


class Session:
    def __init__(self, run_id, sandbox, request, directory):
        self.sandbox = sandbox
        self.question = request.question

    async def run(self):
        await asyncio.sleep(0.03)
        return {"answer": self.sandbox.id}

    def close(self):
        pass


async def test_parallel_tasks_share_server_not_sandbox(cfg, factory):
    service = SharedService(cfg, factory, Session)
    app = create_app(service, "test-token")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-token"},
        ) as client:
            before = (await client.get("/health")).json()
            replies = await asyncio.gather(
                *(
                    client.post("/tasks", json={"task_id": str(i), "question": "test"})
                    for i in range(3)
                )
            )
            after = (await client.get("/health")).json()
    results = [r.json() for r in replies]
    assert all(r["status"] == "completed" for r in results)
    assert {r["server_pid"] for r in results} == {os.getpid()}
    assert before["server_id"] == after["server_id"]
    assert len({r["container_id"] for r in results}) == 3
    assert all(b.closed for b in factory.created)
    assert after["completed"] == 3 and after["active"] == 0
    assert (service.root / "server-metrics.jsonl").exists()
    assert all((service.root / r["run_id"] / "result.json").exists() for r in results)


async def test_image_is_not_uploaded_to_sandbox(cfg, factory):
    import base64

    from gaia_shared.schema import Attachment

    service = SharedService(cfg, factory, Session)
    result = await service.execute(
        TaskRequest(
            task_id="image",
            question="inspect",
            attachments=[Attachment(name="image.png", data_base64=base64.b64encode(b"x").decode())],
        )
    )
    assert result["status"] == "completed"
    assert factory.created[0].files == []


async def test_timeout_and_failure_cleanup(cfg, factory):
    class Failing(Session):
        async def run(self):
            if self.question == "slow":
                await asyncio.sleep(1)
            raise RuntimeError("expected failure")

    cfg = replace(cfg, server={**cfg.server, "request_timeout": 0.01})
    service = SharedService(cfg, factory, Failing)
    results = [await service.execute(TaskRequest(task_id=q, question=q)) for q in ("slow", "fail")]
    assert [r["status"] for r in results] == ["timeout", "error"]
    assert all(b.closed for b in factory.created)
    assert service.active == 0


async def test_auth_and_ground_truth_rejected(cfg, factory):
    app = create_app(SharedService(cfg, factory, Session), "token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).status_code == 401
        r = await client.post(
            "/tasks",
            headers={"Authorization": "Bearer token"},
            json={"task_id": "x", "question": "x", "ground_truth": "secret"},
        )
        assert r.status_code == 422
    assert not factory.created


async def test_concurrency_limit(cfg, factory):
    cfg = replace(cfg, server={**cfg.server, "max_concurrency": 1})
    service = SharedService(cfg, factory, Session)
    jobs = [
        asyncio.create_task(service.execute(TaskRequest(task_id=str(i), question="x")))
        for i in range(4)
    ]
    while any(not j.done() for j in jobs):
        assert service.active <= 1
        await asyncio.sleep(0.005)
    await asyncio.gather(*jobs)
    assert all(b.closed for b in factory.created)


def test_placeholder_key_rejected(cfg, factory):
    with pytest.raises(ValueError):
        create_app(SharedService(cfg, factory, Session), "replace-with-a-random-token")


async def test_cancel_during_container_start_does_not_orphan(cfg, factory):
    import threading

    from conftest import FakeFactory

    started, finish = threading.Event(), threading.Event()

    class SlowFactory(FakeFactory):
        def create(self, run_id):
            started.set()
            finish.wait(timeout=3)
            return super().create(run_id)

    slow = SlowFactory()
    service = SharedService(cfg, slow, Session)
    task = asyncio.create_task(service.execute(TaskRequest(task_id="x", question="x")))
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(slow.created) == 1 and slow.created[0].closed
    assert service.active == 0
