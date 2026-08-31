# Validation record — 2026-08-31

Environment: Windows, Python 3.12.13. Dependencies resolved into `uv.lock` and
installed in this repository's `.venv`. SDK v1.44.1 is imported editable from
`vendor/software-agent-sdk/openhands-sdk`, not a PyPI SDK copy.

## Passed

- `python -m pytest -q`: **28 passed, 1 skipped**.
- Real OpenHands SDK: two simultaneous conversations share the service PID,
  invoke their own bound test sandbox, finish with answer `42`, and clean up.
  The LLM completion boundary and Docker are simulated; SDK agent/event/tool
  dispatch and lifecycle are real. No paid model requests are made by these tests.
- Real SDK cancellation is classified as `timeout`, not a successful answer.
- HTTP authentication and rejection of a ground-truth field in task requests.
- Concurrency limit, exceptional cleanup, and cancellation while a Docker-create
  worker is still running (no lost sandbox ownership).
- GAIA numeric/string/list scoring, hidden test answers, attachment path validation.
- End-to-end ASGI client → service → simulated sandbox → local scoring, plus
  resume without accidentally advancing the sample limit and configuration mismatch checks.
- `ruff check src tests`: passed.
- Modified vendored SDK file: `ruff check --select E,F --ignore E501 .../agent/base.py` passed.
- `uv lock --check --offline --cache-dir .uv-cache`: passed.
- `python -m gaia_shared.cli --config config.example.toml plan`: passed.

The suite emits 3 upstream SDK deprecation warnings about LiteLLM parameter
modification; they do not fail the tests. The full upstream repository's pre-commit
suite was not run: only the SDK package snapshot, not its full development workspace,
is vendored here. The local patch has focused real-SDK regression coverage.

## Not validated on this host

- Docker image build and real Linux Docker namespace/filesystem isolation.
- Real vLLM requests, multimodal compatibility, or a real GAIA score.
- GPU/DCGM measurements, hardware performance counters, or network egress policy.
- Linux CI job (provided in `.github/workflows/tests.yml`, not yet run on GitHub).

`tests/test_docker.py` is skipped unless `RUN_DOCKER_TESTS=1`. On the deployment
host, build the image, run that test, then `doctor`, a one-question smoke run,
and a two-question concurrent run. Compare `server_id/server_pid/container_id`
and inspect container cleanup before accepting the platform for measurements.
