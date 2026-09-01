import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    root: Path
    server: dict
    llm: dict
    sandbox: dict
    gaia: dict
    agent: dict

    def path(self, value: str) -> Path:
        return (self.root / value).resolve()


def load(path: Path) -> Config:
    path = path.resolve()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    cfg = Config(path.parent, **raw)
    if cfg.agent["tool_preset"] != "default":
        raise ValueError("This compatibility baseline supports tool_preset=default only")
    for value in (
        cfg.server["max_concurrency"],
        cfg.server["request_timeout"],
        cfg.server["metrics_interval"],
        cfg.sandbox["cpus"],
        cfg.sandbox["pids_limit"],
        cfg.sandbox["command_timeout"],
        cfg.llm["max_iterations"],
        cfg.gaia["workers"],
        cfg.sandbox["tool_startup_timeout"],
        cfg.sandbox["tool_call_timeout"],
        cfg.agent["mcp_init_timeout"],
    ):
        if value <= 0:
            raise ValueError("Concurrency, resource limits and timeouts must be positive")
    if not 0 <= cfg.agent["condenser_keep_first"] < cfg.agent["condenser_max_size"]:
        raise ValueError("condenser_keep_first must be below condenser_max_size")
    if cfg.agent["max_fake_responses"] < 0:
        raise ValueError("max_fake_responses must be nonnegative")
    if cfg.sandbox["network"] not in ("bridge", "none"):
        raise ValueError("sandbox.network must be bridge or none; host networking is forbidden")
    if cfg.gaia["split"] not in ("validation", "test"):
        raise ValueError("gaia.split must be validation or test")
    if cfg.gaia["level"] not in (0, 1, 2, 3) or cfg.gaia["limit"] < 0:
        raise ValueError("GAIA level must be 0..3 and limit >= 0 (0 = all)")
    return cfg
