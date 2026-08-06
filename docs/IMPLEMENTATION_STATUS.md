# Implementation status

This document maps `PLAN.md` onto the package. Runtime Python stays under `backend/`, and root `__init__.py` remains a thin ComfyUI entry shim.

## Initial decisions

| Decision | Initial value |
| --- | --- |
| Node API | V3 schema via `comfy_api.v0_0_2`, with `latest` fallback |
| Minimum tested ComfyUI | 0.18.1 |
| Backend priority | Ollama REST first; native llama.cpp optional later |
| List handling | Node-level `is_input_list=True` |
| Ollama endpoint | `/api/chat`, stateless, `stream=false` |
| Image format | Independent lossless PNG files |
| Resize/padding/montage | Never automatic |
| Audio | Core WAV normalization; transport disabled by default |
| Authentication | URL-supported only; credentials are redacted from diagnostics |
| Ollama Cloud | Not compatibility-tested |

## Milestones

- Phase 0: package conversion and V3 registration — implemented and covered by entrypoint, schema, and extension registration tests.
- Phase 1: deterministic image/audio normalization and safety limits — implemented and covered by unit tests.
- Phase 2: Ollama request/response path and payload-free diagnostics — implemented and covered by a local mock HTTP server integration test.
- Phase 3: live Ollama capability and multi-model validation — pending.
- Phase 4: experimental audio compatibility validation — pending.
- Phase 5–6: optional `llama-cpp-python`, unload, and native audio research — pending.

The initial release intentionally does not claim that experimental audio or any native llama.cpp backend is stable.

Full `/api/object_info` discovery in a started ComfyUI process remains a manual release check until there is an end-to-end workflow test worth the additional harness cost.
