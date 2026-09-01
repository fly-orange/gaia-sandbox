import sys
from pathlib import Path

from gaia_shared.provenance import source_fingerprint
from gaia_shared.skills import load_skills
from gaia_shared.tool_bridge import WorkerConnection


def test_real_tool_worker_executes_upstream_terminal(cfg, tmp_path):
    connection = WorkerConnection(
        [sys.executable, "-m", "gaia_shared.worker"], tmp_path / "worker.log"
    )
    try:
        result = connection.call(
            "initialize",
            {
                "source_sha256": source_fingerprint(Path(__file__).parents[1]),
                "workspace": str(tmp_path),
                "vision": False,
                "browser": False,
                "agent": {
                    **cfg.agent,
                    "public_skills": False,
                    "fetch": False,
                    "tavily": False,
                },
            },
            timeout=30,
        )
        names = {item["name"] for item in result["tools"]}
        assert names == {"terminal", "file_editor", "task_tracker"}
        response = connection.call(
            "call",
            {"name": "terminal", "action": {"command": "echo worker-ok"}},
            timeout=30,
        )
        text = "".join(item.get("text", "") for item in response["observation"]["content"])
        assert "worker-ok" in text
    finally:
        connection.close()


def test_pinned_public_skills_are_loadable():
    skills = load_skills(Path(__file__).parents[1] / "vendor/extensions")
    assert len(skills) == 60
    assert {"evidence-based-citations", "research-brief", "jupyter"} <= {
        skill.name for skill in skills
    }
