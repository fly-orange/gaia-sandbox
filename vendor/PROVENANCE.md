# Vendored OpenHands SDK

- Repository: https://github.com/OpenHands/software-agent-sdk
- Commit: `704cbe6015e3d59cabe04632175d99df2d448999`
- Package version: `1.44.1`
- Imported: `openhands-sdk/`, root `LICENSE` and root `AGENTS.md` via `git archive`.
- Import date: 2026-08-31
- License: see `software-agent-sdk/LICENSE` (retained verbatim).

This is a source snapshot, NOT a submodule or nested Git checkout. Every source
file is tracked by the outer repository. `uv` installs the package editable from
this directory; there is no hidden `.upstream` or monkey-patched installed wheel.

## Local patch

`openhands/sdk/agent/base.py` adds `Agent.auto_attach_vision_tool` (default `True`
for upstream compatibility). The shared-service adapter sets it to `False` to
prevent automatically adding a host filesystem/profile vision tool outside its
per-task Docker tool boundary. `tests/test_sdk.py` tests real SDK initialization
and verifies only the intended tools are attached.

## Updating

Use an upstream checkout OUTSIDE this repository, fetch and inspect a chosen SHA,
and compare it with this recorded baseline. Apply reviewed changes to this tracked
snapshot with normal patches; retain the local patch and update this document.
Run `uv lock`, `uv sync --locked --extra test --extra data`, and all tests.
Do not clone another `.git` into `vendor/`, do not add it to `.gitignore`, and do
not overwrite this directory blindly while it contains local debugging changes.

Only the SDK is vendored: the GAIA loader, scorer, persistent server and Docker
adapter are maintained directly in `src/gaia_shared/`. The former benchmarks
repository and per-task OpenHands Agent Server package are not needed.
