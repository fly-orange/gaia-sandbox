import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import load


def main():
    parser = argparse.ArgumentParser(description="Persistent Agent service / per-task Docker GAIA")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Start ONE shared SDK Agent server process")
    commands.add_parser("run", help="Run/resume GAIA against the resident server")
    commands.add_parser("doctor", help="Check Docker, image, model, vendored SDK")
    commands.add_parser("download", help="Download gated GAIA dataset (requires HF_TOKEN)")
    commands.add_parser("plan", help="Print deployment topology without side effects")
    args = parser.parse_args()
    try:
        cfg = load(args.config)
        load_dotenv(cfg.root / ".env", override=False)
        if args.command == "plan":
            print(
                json.dumps(
                    {
                        "topology": "1 persistent SDK server -> N private tool-only containers",
                        "server": cfg.server,
                        "llm": cfg.llm,
                        "sandbox": cfg.sandbox,
                        "gaia": cfg.gaia,
                    },
                    indent=2,
                )
            )
        elif args.command == "serve":
            import uvicorn

            from .agent import SDKSession
            from .sandbox import DockerFactory
            from .server import create_app
            from .service import SharedService

            key = os.getenv(cfg.llm["api_key_env"])
            if not key:
                raise ValueError(f"Set {cfg.llm['api_key_env']}")
            if cfg.agent["tavily"] and not os.getenv("TAVILY_API_KEY"):
                raise ValueError("Set TAVILY_API_KEY or disable agent.tavily")
            service = SharedService(
                cfg,
                DockerFactory(cfg.sandbox),
                lambda run_id, sandbox, request, directory: SDKSession(
                    cfg, key, run_id, sandbox, request, directory
                ),
            )
            app = create_app(service, os.getenv("GAIA_SERVER_TOKEN", ""))
            print(json.dumps(service.health()))
            # Never use --workers > 1: that would create multiple Agent Server processes.
            uvicorn.run(app, host=cfg.server["host"], port=cfg.server["port"], workers=1)
        elif args.command == "run":
            from .client import evaluate

            url = os.getenv("GAIA_SERVER_URL", f"http://127.0.0.1:{cfg.server['port']}")
            asyncio.run(evaluate(cfg, os.getenv("GAIA_SERVER_TOKEN", ""), url))
        elif args.command == "download":
            from huggingface_hub import snapshot_download

            snapshot_download(
                "gaia-benchmark/GAIA",
                repo_type="dataset",
                local_dir=cfg.path(cfg.gaia["dataset_path"]),
                token=os.getenv("HF_TOKEN"),
            )
        elif args.command == "doctor":
            import httpx
            import openhands.sdk

            import docker

            if cfg.agent["tavily"] and not os.getenv("TAVILY_API_KEY"):
                raise ValueError("Set TAVILY_API_KEY or disable agent.tavily")

            print("SDK source:", openhands.sdk.__file__)
            with docker.from_env() as client:
                info = client.info()
                if info["OSType"] != "linux":
                    raise RuntimeError("Linux Docker containers are required")
                image = client.images.get(cfg.sandbox["image"])
                print("Sandbox image:", image.id)
            response = httpx.get(
                cfg.llm["base_url"].rstrip("/") + "/models",
                timeout=10,
                headers={"Authorization": "Bearer " + os.getenv(cfg.llm["api_key_env"], "")},
            )
            response.raise_for_status()
            print("Model endpoint OK. Verify the configured model ID exists in /models.")
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
