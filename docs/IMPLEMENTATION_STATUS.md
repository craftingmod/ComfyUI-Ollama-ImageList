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
| Model discovery | ComfyUI route proxy to Ollama `/api/tags` |
| Image format | Independent lossless PNG files |
| Resize/padding/montage | Never automatic |
| Public media scope | Generate exposes IMAGE input only; Media Bundle and AUDIO inputs are disabled |
| Authentication | URL-supported only; credentials are redacted from diagnostics |
| Ollama Cloud | Not compatibility-tested |

## Milestones

- Phase 0: package conversion and V3 registration — implemented and covered by entrypoint, schema, and extension registration tests.
- Phase 1: deterministic image-list normalization and safety limits — implemented and covered by unit tests; dormant audio normalization remains internal.
- Phase 2: Ollama request/response path and payload-free diagnostics — implemented and covered by a local mock HTTP server integration test.
- Ollama connectivity: model discovery, dynamic COMBO selection, manual model override, and URL/model outputs — implemented.
- Ollama options builder: individually enabled documented runtime options with JSON and typed dictionary outputs — implemented.
- Phase 3: live Ollama capability and multi-model validation — pending.
- Phase 4: optional Media Bundle and experimental audio compatibility validation — disabled for the initial public scope.
- Phase 5–6: per-request Ollama unload is implemented through `unload_after_response`; optional `llama-cpp-python`, dedicated unload controls, and native audio research remain pending.

The initial release intentionally exposes no audio input and does not claim that any native llama.cpp backend is stable.

Full `/api/object_info` discovery in a started ComfyUI process remains a manual release check until there is an end-to-end workflow test worth the additional harness cost.
