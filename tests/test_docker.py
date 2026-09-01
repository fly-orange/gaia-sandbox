import os
import uuid
from pathlib import Path

import pytest

from gaia_shared.provenance import source_fingerprint
from gaia_shared.sandbox import DockerFactory


@pytest.mark.docker
@pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="Set RUN_DOCKER_TESTS=1")
def test_real_container_filesystem_isolation_and_tool_profile(cfg, tmp_path):
    factory = DockerFactory(cfg.sandbox)
    boxes = []
    try:
        boxes = [factory.create(uuid.uuid4().hex)]
        boxes.append(factory.create(uuid.uuid4().hex))
        assert boxes[0].execute("echo first > /workspace/probe")["exit_code"] == 0
        assert boxes[1].execute("test ! -e /workspace/probe")["exit_code"] == 0
        for box in boxes:
            assert box.execute("test ! -S /var/run/docker.sock")["exit_code"] == 0
            assert box.execute('test -z "$VLLM_API_KEY"')["exit_code"] == 0
        worker = boxes[0].start_tools(
            {
                "source_sha256": source_fingerprint(Path(__file__).parents[1]),
                "vision": False,
                "browser": True,
                "tavily_key": "",
                "agent": {
                    **cfg.agent,
                    "public_skills": False,
                    "fetch": False,
                    "tavily": False,
                },
                "sandbox": cfg.sandbox,
            },
            tmp_path,
        )
        names = {item["name"] for item in worker["tools"]}
        assert {"terminal", "file_editor", "task_tracker", "browser_navigate"} <= names
        response = boxes[0].worker.call(
            "call", {"name": "terminal", "action": {"command": "echo docker-worker-ok"}}, 30
        )
        content = response["observation"]["content"]
        assert "docker-worker-ok" in "".join(item.get("text", "") for item in content)
    finally:
        for box in boxes:
            box.close()
