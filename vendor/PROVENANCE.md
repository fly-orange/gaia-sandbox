# Vendored OpenHands GAIA baseline

- `OpenHands/benchmarks` commit `f60e4ed11262b667896ce9f554dd487057fd1ef2`:
  `benchmarks/gaia`, shared agent/LLM helpers needed for reference, root license/instructions.
- Its `software-agent-sdk` submodule commit
  `43376f1868ffd702746080714a59c16d3f69ec12`, package version `1.27.0`:
  `openhands-sdk`, `openhands-tools`, root license/instructions.
- `OpenHands/extensions` commit `87959a7da3e75445647e77b2fbf5bf5b66fb037b`:
  public skills, marketplaces and retained root license/instructions.
- Import date: 2026-09-01. Licenses are retained inside each snapshot.

This is a source snapshot, NOT a submodule or nested Git checkout. Every source
file is tracked by the outer repository. `uv` installs the package editable from
this directory; there is no hidden `.upstream` or monkey-patched installed wheel.

## Local SDK patches

- `Agent.auto_attach_skill_tool` defaults to `True`; this adapter sets it to `False`
  because its per-sandbox InvokeSkill proxy is already present.
- `LocalConversation.profile_store_dir` keeps mutable LLM profiles inside each run.
- the Jinja bytecode cache defaults to the process temporary directory rather than
  the user home, while still allowing `OH_JINJA_CACHE_DIR`.

The platform adapter in `src/gaia_shared` implements the persistent host service,
per-task tool worker and protocol. The benchmark snapshot is retained as an auditable
reference; it is not imported as a second application at runtime.

## Updating

Use an upstream checkout OUTSIDE this repository, fetch and inspect a chosen SHA,
and compare it with this recorded baseline. Apply reviewed changes to this tracked
snapshot with normal patches; retain the local patch and update this document.
Run `uv lock`, `uv sync --locked --extra test --extra data`, and all tests.
Do not clone another `.git` into `vendor/`, do not add it to `.gitignore`, and do
not overwrite this directory blindly while it contains local debugging changes.

All three snapshots are tracked by the outer repository, so ordinary Git commits
and pushes include local debugging changes without a hidden upstream worktree.
