import os
import uuid

import pytest

from gaia_shared.sandbox import DockerFactory


@pytest.mark.docker
@pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="Set RUN_DOCKER_TESTS=1")
def test_real_container_filesystem_isolation(cfg):
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
    finally:
        for box in boxes:
            box.close()
