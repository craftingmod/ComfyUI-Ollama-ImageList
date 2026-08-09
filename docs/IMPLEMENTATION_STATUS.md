# Implementation status

This document maps `PLAN.md` onto the package. Runtime Python stays under `backend/`, and root `__init__.py` remains a thin ComfyUI entry shim.

## Initial decisions

| Decision | Initial value |
| --- | --- |
| Node API | V3 schema via `comfy_api.v0_0_2`, with `latest` fallback |
| Minimum supported ComfyUI | 0.19.3 (official Generate Text dynamic schema baseline) |
| Current package release | 0.3.0 |
| Backend priority | Ollama REST, optional native llama.cpp, and ComfyUI generative CLIP |
| List handling | Node-level `is_input_list=True` |
| Ollama endpoint | `/api/chat`, stateless, `stream=false` |
| Model discovery | ComfyUI route proxy to Ollama `/api/tags` |
| Image format | Independent lossless PNG files |
| Resize/padding/montage | Never automatic |
| Public media scope | Ollama Generate exposes IMAGE; llama.cpp Generate exposes optional IMAGE, AUDIO, and VIDEO |
| Native CLIP scope | Official Generate Text flow plus system role and IMAGE data lists for Qwen3-VL, Qwen3.5, and Gemma 4 |
| Node categories | Ollama nodes use `Ollama / Image List`; native nodes use `Ollama / llama_cpp` |
| Native model lifetime | Serialized, one completion per load, unconditional close in `finally`, no retained model output or cache |
| Authentication | URL-supported only; credentials are redacted from diagnostics |
| Ollama Cloud | Not compatibility-tested |

## Milestones

- Phase 0: package conversion and V3 registration — implemented and covered by entrypoint, schema, and extension registration tests.
- Phase 1: deterministic image/audio/video normalization and safety limits — implemented and covered by unit tests.
- Phase 2: Ollama request/response path and payload-free diagnostics — implemented and covered by a local mock HTTP server integration test.
- Ollama connectivity: model discovery, dynamic COMBO selection, manual model override, and URL/model outputs — implemented.
- Ollama options builder: individually enabled documented runtime options with JSON and typed dictionary outputs — implemented.
- Phase 3: live Ollama capability and multi-model validation — pending.
- Phase 4: optional Media Bundle remains disabled; its shared image/audio normalization and PCM16 WAV encoder are used directly by the llama.cpp node.
- Phase 5: optional `llama-cpp-python` multimodal generation is implemented with IMAGE, AUDIO, and VIDEO list inputs, lazy dependency import, GGUF Combo discovery from ComfyUI's registered `LLM` paths (including `extra_model_paths.yaml`) plus the local `models/LLM` fallback, selectable MTMD handlers, explicit thinking control, typed sampling and Gemma 4 runtime presets, serialized execution, unconditional per-request model cleanup, and a typed MTMD ingestion receipt expanded by a separate diagnostics node.
- Phase 6: per-request Ollama unload is implemented through `unload_after_response`; native llama.cpp audio and video message construction is implemented, while broad real-model compatibility validation remains pending. A dedicated native unload node is unnecessary because native models are never cached.
- Native CLIP Generate Text: implemented with official sampling/generation calls, model-specific system-role templates, one-call IMAGE lists, tokenizer capability detection, and Gemma 4 PR #15450 compatibility fallback.

The Ollama node intentionally exposes no audio or video input. Native llama.cpp support depends on a separately installed platform/Python/native-backend-compatible wheel, a wheel built with `MTMD_VIDEO` for VIDEO, and modality-specific GGUF/mmproj compatibility. No separate FFmpeg executable is required by this node. Detailed operational documentation is in [`LLAMA_CPP.md`](LLAMA_CPP.md).

Full `/api/object_info` discovery in a started ComfyUI process remains a manual release check until there is an end-to-end workflow test worth the additional harness cost.
