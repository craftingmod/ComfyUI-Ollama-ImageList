# AGENTS.md

Single publishable ComfyUI custom node pack.

- Backend node code lives in `backend/`
- Root `__init__.py` is the thin ComfyUI entry shim
- Use `uv run pytest` for the test suite
- Use `uv` for Python dependency sync and Python execution outside repo scripts

For testing details, see `docs/TESTING.md`.
For ComfyUI API changes, verify current official docs before changing architecture or advanced frontend hooks.

## Git
- When Codex creates a Git commit, append:
  `Co-authored-by: Codex <codex@openai.com>`
