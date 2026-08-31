import asyncio
import hashlib
import json

import httpx

from .dataset import make_request, read_instances
from .io import append_json
from .provenance import fingerprint, profile
from .scoring import score, summarize


async def evaluate(cfg, token, url):
    gaia = cfg.gaia
    root = cfg.path(gaia["dataset_path"])
    rows = read_instances(root, gaia["split"], gaia["level"], gaia["limit"])
    output = cfg.path(gaia["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "llm": cfg.llm,
        "sandbox": cfg.sandbox,
        "gaia": gaia,
        "request_timeout": cfg.server["request_timeout"],
        "dataset_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
    }
    manifest_path = output / "manifest.json"
    results_path = output / "output.jsonl"
    previous = []
    if results_path.exists():
        previous = [
            json.loads(s)
            for s in results_path.read_text(encoding="utf-8").splitlines()
            if s.strip()
        ]
    latest = {r["task_id"]: r for r in previous}
    # Limit was applied BEFORE resume filtering: re-running smoke cannot take new questions.
    pending = [r for r in rows if latest.get(str(r["task_id"]), {}).get("status") != "completed"]
    semaphore = asyncio.Semaphore(gaia["workers"])
    # Include queue time, startup, execution, command cancellation and cleanup slack.
    budget = cfg.server["request_timeout"] + cfg.sandbox["command_timeout"] + 120
    async with httpx.AsyncClient(
        base_url=url,
        timeout=budget * (gaia["workers"] + 1),
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        health = await client.get("/health")
        health.raise_for_status()
        server = health.json()
        if server["profile_sha256"] != fingerprint(profile(cfg)):
            raise ValueError("Client/server LLM, sandbox or timeout configuration does not match")
        manifest["server_source_sha256"] = server["source_sha256"]
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Configuration, code or dataset changed. Use a new gaia.output_dir.")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        async def run_one(row):
            async with semaphore:
                request = make_request(row, root, gaia["split"])
                response = await client.post("/tasks", json=request.model_dump())
                response.raise_for_status()
                result = response.json()
                truth = str(row.get("Final answer", "")) if gaia["split"] == "validation" else None
                result["score"] = score(result["answer"], truth)
                if result["status"] != "completed" and result["score"] is not None:
                    result["score"] = False
                result["ground_truth"] = truth
                append_json(results_path, result)
                latest[result["task_id"]] = result
                print(f"{result['task_id']}: {result['status']}, score={result['score']}")

        # Capture all errors; don't cancel healthy requests because one upload failed.
        failures = await asyncio.gather(*(run_one(row) for row in pending), return_exceptions=True)
    selected = [latest[str(r["task_id"])] for r in rows if str(r["task_id"]) in latest]
    report = {
        **summarize(selected),
        "selected": len(rows),
        "transport_errors": [str(e) for e in failures if isinstance(e, BaseException)],
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["transport_errors"]:
        raise RuntimeError("Some requests failed before a result was obtained; see summary.json")
    return report
