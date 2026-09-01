import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

import psutil

from .io import append_json, stamp
from .provenance import fingerprint, profile, source_fingerprint
from .schema import IMAGE_SUFFIXES


class SharedService:
    def __init__(self, cfg, factory, session_factory):
        self.cfg, self.factory, self.session_factory = cfg, factory, session_factory
        self.pid = os.getpid()
        self.server_id = uuid.uuid4().hex
        self.limit = asyncio.Semaphore(cfg.server["max_concurrency"])
        self.active = 0
        self.waiting = 0
        self.completed = 0
        self.root = cfg.path(cfg.server["output_dir"]) / self.server_id
        self.root.mkdir(parents=True)
        self.process = psutil.Process()
        self.stop_sampling = asyncio.Event()
        self.source_sha256 = source_fingerprint(Path(__file__).resolve().parents[2])
        self.profile_sha256 = fingerprint(profile(cfg))
        (self.root / "server-manifest.json").write_text(
            json.dumps(
                {
                    **self.health(),
                    "profile": profile(cfg),
                    "server_settings": cfg.server,
                    "started_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def health(self):
        return {
            "server_id": self.server_id,
            "server_pid": self.pid,
            "active": self.active,
            "waiting": self.waiting,
            "completed": self.completed,
            "max_concurrency": self.cfg.server["max_concurrency"],
            "profile_sha256": self.profile_sha256,
            "source_sha256": self.source_sha256,
        }

    async def sample_server(self):
        while not self.stop_sampling.is_set():
            cpu = self.process.cpu_times()
            append_json(
                self.root / "server-metrics.jsonl",
                {
                    **stamp(),
                    **self.health(),
                    "rss_bytes": self.process.memory_info().rss,
                    "cpu_user_seconds": cpu.user,
                    "cpu_system_seconds": cpu.system,
                    "threads": self.process.num_threads(),
                },
            )
            try:
                await asyncio.wait_for(
                    self.stop_sampling.wait(), self.cfg.server["metrics_interval"]
                )
            except TimeoutError:
                pass

    async def execute(self, request):
        submitted = time.monotonic()
        self.waiting += 1
        try:
            await self.limit.acquire()
        finally:
            self.waiting -= 1
        self.active += 1
        try:
            return await self._execute(request, submitted)
        finally:
            self.active -= 1
            self.completed += 1
            self.limit.release()

    async def _execute(self, request, submitted):
        run_id = uuid.uuid4().hex
        directory = self.root / run_id
        directory.mkdir()
        result = {
            "run_id": run_id,
            "task_id": request.task_id,
            "server_id": self.server_id,
            "server_pid": self.pid,
            "source_sha256": self.source_sha256,
            "profile_sha256": self.profile_sha256,
            "queue_seconds": time.monotonic() - submitted,
            "started_at": time.time(),
            "status": "error",
            "answer": "",
        }
        (directory / "request.json").write_text(
            json.dumps(
                {
                    "task_id": request.task_id,
                    "question": request.question,
                    "attachments": [a.name for a in request.attachments],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        sandbox = session = sampler = None
        stop = asyncio.Event()
        phase = "initializing"
        start = time.monotonic()

        async def sample():
            while not stop.is_set():
                try:
                    sample_phase = phase
                    data = await asyncio.to_thread(sandbox.stats)
                    append_json(
                        directory / "sandbox-metrics.jsonl",
                        {**stamp(), "phase": sample_phase, **data},
                    )
                except Exception as exc:
                    append_json(
                        directory / "sandbox-metrics.jsonl", {**stamp(), "sampling_error": str(exc)}
                    )
                try:
                    await asyncio.wait_for(stop.wait(), self.cfg.server["metrics_interval"])
                except TimeoutError:
                    pass

        try:
            # A finite Docker API timeout bounds startup. Keep ownership until it returns.
            creating = asyncio.create_task(asyncio.to_thread(self.factory.create, run_id))
            try:
                sandbox = await asyncio.shield(creating)
            except asyncio.CancelledError:
                # The thread cannot be cancelled; retain ownership for finally-cleanup.
                sandbox = await creating
                raise
            result["container_id"] = sandbox.id
            result["sandbox_image"] = self.cfg.sandbox["image"]
            sampler = asyncio.create_task(sample())
            for attachment in request.attachments:
                if Path(attachment.name).suffix.lower() not in IMAGE_SUFFIXES:
                    await asyncio.to_thread(sandbox.upload, attachment)
            worker_config = {
                "source_sha256": self.source_sha256,
                "agent": self.cfg.agent,
                "sandbox": self.cfg.sandbox,
                "vision": self.cfg.llm["vision"],
                "browser": True,
                "tavily_key": os.getenv("TAVILY_API_KEY", ""),
            }
            worker = await asyncio.to_thread(
                sandbox.start_tools, worker_config, directory
            )
            result["tool_worker_pid"] = worker["worker_pid"]
            result["tool_names"] = [item["name"] for item in worker["tools"]]
            session = self.session_factory(run_id, sandbox, request, directory)
            result["sandbox_stats_after_init"] = await asyncio.to_thread(sandbox.stats)
            result["initialization_seconds"] = time.monotonic() - start
            phase = "running"
            agent_start = time.monotonic()
            try:
                async with asyncio.timeout(self.cfg.server["request_timeout"]) as deadline:
                    outcome = await session.run()
                if deadline.expired():
                    raise TimeoutError("Task execution deadline exceeded")
                if outcome.get("conversation_status", "finished") != "finished":
                    raise RuntimeError(
                        f"Conversation ended with status {outcome['conversation_status']}"
                    )
                result.update(outcome)
                result["status"] = "completed"
            finally:
                result["agent_seconds"] = time.monotonic() - agent_start
        except TimeoutError:
            result.update(status="timeout", error="Task execution deadline exceeded")
        except asyncio.CancelledError:
            result.update(status="cancelled", error="Service request cancelled")
            raise
        except Exception as exc:
            logging.getLogger(__name__).exception("Task %s failed", run_id)
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            phase = "cleanup"
            cleanup_start = time.monotonic()
            stop.set()
            if sampler is not None:
                try:
                    await sampler
                except Exception as exc:
                    result["sampler_error"] = str(exc)
            # Remove sandbox first: stop any command still in a cancelled SDK thread.
            if sandbox is not None:
                try:
                    result["final_sandbox_stats"] = await asyncio.to_thread(sandbox.stats)
                except Exception as exc:
                    result["stats_error"] = str(exc)
                try:
                    await asyncio.to_thread(sandbox.close)
                except Exception as exc:
                    result["cleanup_error"] = str(exc)
            if session is not None:
                try:
                    session.close()
                except Exception as exc:
                    result["session_cleanup_error"] = str(exc)
            result["total_seconds"] = time.monotonic() - start
            result["cleanup_seconds"] = time.monotonic() - cleanup_start
            result["finished_at"] = time.time()
            (directory / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return result
