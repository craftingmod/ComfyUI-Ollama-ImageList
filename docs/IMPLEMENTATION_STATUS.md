# Implementation status

This document maps `PLAN.md` onto the package. Runtime Python stays under `backend/`, and root `__init__.py` remains a thin ComfyUI entry shim.

## Initial decisions

| Decision | Initial value |
| --- | --- |
| Node API | V3 schema via `comfy_api.v0_0_2`, with `latest` fallback |
| Minimum supported ComfyUI | 0.19.3 (official Generate Text dynamic schema baseline) |
| Current package release | 0.7.0 |
| Backend priority | Ollama REST, optional native llama.cpp, and ComfyUI generative CLIP |
| List handling | Node-level `is_input_list=True` |
| Ollama endpoint | `/api/chat`, stateless, `stream=false` |
| Model discovery | ComfyUI route proxy to Ollama `/api/tags` |
| Image format | Independent lossless PNG files |
| Resize/padding/montage | Never automatic |
| Public media scope | Ollama Generate exposes IMAGE; llama.cpp Generate exposes optional IMAGE, AUDIO, and VIDEO |
| Native CLIP scope | Official Generate Text flow plus system role and IMAGE data lists for Qwen3-VL, Qwen3.5, and Gemma 4 |
| Node categories | Ollama image nodes use `Ollama / images`; native nodes use top-level `llama_cpp`; Compact profiles/generation use `compact`; diagnostics/parsers use `utils`; native speculative configuration uses `experimental`; four registered detailed schemas are development-only under `legacy`; the detailed speculative Generate class is not registered |
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
- Phase 5: optional `llama-cpp-python` multimodal generation is implemented with IMAGE, AUDIO, and VIDEO list inputs, lazy dependency import, GGUF Combo discovery from ComfyUI's registered `LLM` paths (including `extra_model_paths.yaml`) plus the local `models/LLM` fallback, selectable MTMD handlers, explicit thinking control, typed sampling and Gemma 4 runtime presets, separate Compact model/hardware/reasoning configs with published Gemma/Muse/Qwen values and presence-penalty forwarding, visible request budgets, and a unified Compact N-gram/native `speculative` socket, serialized execution, unconditional per-request model cleanup, and a typed MTMD ingestion receipt expanded by a separate diagnostics node.
- Experimental native speculative generation is implemented as a cloned Generate schema with a dedicated draft GGUF selector, DFlash/DSpark/MTP controls, lazy `SpecConfig`/`SpeculativeType` import, request-local `Llama.last_speculative_stats` capture, and `Llama`-owned native-engine cleanup.
- JamePeng API cleanup keeps native decoding on the public `SpecConfig` + `Llama(speculative=...)` boundary, replaces the broad sequential proxy and private tokenizer/handler checks with a narrow explicit adapter, and does not inspect native engine metadata. Real wheel, GGUF, MTMD/video, and process-tree validation remain manual.
- Normal Generate supports a separate typed N-gram Speculative Preset backed by the official `SpecConfig`/`SpeculativeType.NGRAM_MAP_K` or `NGRAM_MAP_K4V` path, with an unchanged off path, no draft GGUF, public-stat capture, and explicit rejection of mixed native/n-gram modes and multimodal requests.
- Phase 6: per-request Ollama unload is implemented through `unload_after_response`; native llama.cpp audio and video message construction is implemented, including optional embedded-video-audio extraction for compact Generate and atomic IMAGE/AUDIO/VIDEO sequencing for Compact Media Sequential Generate. Session Generate (Media Sequential) processes one media item per request; Session Generate (Prompt Sequential) runs a flat prompt list against one shared complete media bundle and requests best-effort common-prefix reuse by default (`reuse_kv_cache`, with server `cache_prompt` control). Session Decide (Media Sequential) pairs atomic media items with a shared or per-item context and typed question; Session Decide (Prompt Sequential) pairs/broadcasts context and typed-question lists against one fixed media bundle and can request best-effort cache reuse. Text-only Native Decide prefill currently resets internally through the public prefill handler, so cache reuse cannot be guaranteed on that path. MTMD handler-side media encoding may repeat, and hybrid/recurrent checkpoint cache behavior remains model-and-wheel-specific; real native and server runtime validation remains pending. Compact request nodes unload after each completion; retained Native Sessions use the existing Unload Session and prompt-end cleanup lifecycle.
- Native CLIP Text Encode (Multimodal): implemented with official sampling/generation calls, model-specific system-role templates, one-call IMAGE lists, tokenizer capability detection, and Gemma 4 PR #15450 compatibility fallback.

The Ollama node intentionally exposes no audio or video input. Native llama.cpp support depends on a separately installed platform/Python/native-backend-compatible wheel, a wheel built with `MTMD_VIDEO` for VIDEO, and modality-specific GGUF/mmproj compatibility. The optional `video_with_audio` mode uses the PyAV package already required by supported ComfyUI installations. Detailed operational documentation is in [`LLAMA_CPP.md`](LLAMA_CPP.md).

Server Decide probability correction: single and both Sequential variants request full-vocabulary pre-sampling logprobs using cached `/v1/models` vocabulary metadata. Unrelated tokens are excluded from scoring, every choice must be present, and all-zero choice mass is rejected. Regression coverage was added without execution; full-vocabulary response cost and live Gemma 4 behavior remain unverified.

Full `/api/object_info` discovery in a started ComfyUI process remains a manual release check until there is an end-to-end workflow test worth the additional harness cost.
