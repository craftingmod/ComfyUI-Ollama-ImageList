# AGENTS.md

Single publishable ComfyUI custom node pack.

- Backend node code lives in `backend/`
- Frontend runtime source lives in `frontend/` and is bundled to generated `dist/`
- Root `__init__.py` is the thin ComfyUI entry shim
- Use repo commands first: `bun run typecheck`, `bun run test`, `bun run build`
- Use `uv` for Python dependency sync and Python execution outside repo scripts

For testing details, see `docs/TESTING.md`.
For ComfyUI API changes, verify current official docs before changing architecture or advanced frontend hooks.

## Git
- When Codex creates a Git commit, append:
  `Co-authored-by: Codex <codex@openai.com>`
