# Validation record — 2026-09-01

Environment: Windows, Python 3.12.13. The lockfile pins the same dependency
versions as the selected OpenHands benchmark baseline, including OpenHands SDK/
tools 1.27.0, LiteLLM 1.93.0 and browser-use 0.11.13.

The local Windows environment could not finish building the LiteLLM 1.93.0 source
distribution, so the test interpreter used LiteLLM 1.98.0 as a local-only
workaround. `uv.lock` was not changed to that version. Linux CI and the Docker
image continue to install the locked 1.93.0 version and are the authoritative
dependency validation targets.

## Passed locally

- `python -m pytest -q`: **36 passed, 1 skipped**.
- Two simultaneous real SDK conversations share one service PID, receive separate
  dynamically generated sandbox-tool proxies, produce answer `42`, and clean up.
  LLM responses and Docker are simulated; SDK agent/event dispatch is real.
- A real out-of-process tool worker initializes the pinned upstream Terminal,
  FileEditor and TaskTracker, and Terminal executes a command successfully.
- All 60 vendored public OpenHands skills parse successfully.
- GAIA ordinary-file renaming, image-as-model-content behavior, safe ZIP expansion,
  total attachment bounds, traversal rejection and no answer leakage.
- Timeout classification, concurrency limit, authentication, cancellation during
  container creation, cleanup, resume behavior and GAIA scoring.
- `ruff check src tests`: passed.
- `ruff check --select E,F --ignore E501` on the three locally patched SDK files:
  passed.
- `uv lock --check --offline --cache-dir .uv-cache`: passed (357 packages).
- `python -m gaia_shared.cli --config config.example.toml plan`: passed.
- `git diff --check`, Python byte-compilation, nested `.git`/`.upstream` search and
  repository secret-pattern scan: passed; only documented placeholder values exist.

The full upstream pre-commit workspace was not vendored, so its complete suite was
not run. Local patches have targeted adapter regression coverage.

## Not validated on this host

- Docker image build and Linux container isolation: Docker is not installed on this
  Windows host. The opt-in Docker test now also starts the in-container worker and
  verifies Terminal plus the browser-use tool schema.
- Live Tavily MCP, Fetch MCP, Chromium navigation, vLLM requests, multimodal input,
  a real GAIA score, GPU/DCGM measurements or egress policy.
- The GitHub Linux CI result until this revision has been pushed.

On the deployment host, build `gaia-sandbox:0.2`, run
`RUN_DOCKER_TESTS=1 uv run pytest -m docker -q`, then `doctor`, one question, and
two concurrent questions. Confirm one `server_id/server_pid`, distinct container
IDs/tool-worker PIDs, expected tool names, successful cleanup, and usable Tavily/
browser observations before accepting the platform for measurements.
