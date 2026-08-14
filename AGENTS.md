# AGENTS.md

Single publishable ComfyUI custom node pack.

- Backend node code lives in `backend/`
- Root `__init__.py` is the thin ComfyUI entry shim
- Use `uv run pytest` for the test suite
- Use `uv` for Python dependency sync and Python execution outside repo scripts

For testing details, see `docs/TESTING.md`.
For ComfyUI API changes, verify current official docs before changing architecture or advanced frontend hooks.

## Testing cadence

- Do not rerun the full frontend and Python suites after every small edit.
- During implementation, run only the tests directly affected by the change.
- Before handoff:
  - Frontend-only changes: run `bun run check:frontend`.
  - Python-only changes: run `uv run pytest`.
  - Cross-stack, schema, packaging, or release changes: run both.
- Documentation-only changes may skip automated tests; still run `git diff --check`.
- If a full suite already passed and subsequent changes only affect unrelated documentation, do not rerun it.

## Git
- When Codex creates a Git commit, append:
  `Co-authored-by: Codex <codex@openai.com>`
