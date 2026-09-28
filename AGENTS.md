# AGENTS.md

## Repository

- Frontend runtime code lives in `frontend/`; backend code lives in `backend/`; the root `__init__.py` is the ComfyUI entry shim.
- Use `uv` for Python dependency sync and Python execution outside repo scripts.

## Validation

- Do not run validation unless explicitly requested.
- When tests are requested, use `bun run test:agent`.
- Full validation is performed once at the end by the parent agent or manually by the user.
- See `docs/TESTING.md` when manual runtime testing is required.
- For ComfyUI API changes, verify the current official documentation.

## Rules

- Use `GPT-6 Luna` with `MAX` reasoning for sub-agent.
- Use `snake_case` for custom node's parameters
