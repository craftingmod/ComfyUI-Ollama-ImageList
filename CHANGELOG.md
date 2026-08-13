# Changelog

All notable changes to this project are documented in this file.

## Unreleased

## 0.6.0 - 2026-08-13

### Added

- `MiniMax System Prompt Preset` under `Ollama / prompt`, with packaged, editable base and mode-specific Markdown sources for eight prompting modes plus an optional validated `enum_string` override.
- `Llama.cpp Sequential Generate`, which reuses one loaded model for an input list while resetting context before every independent completion and unloading once after the sequence.

## 0.5.0 - 2026-08-12

### Added

- Native `draft-mtp` speculative decoding for Gemma 4 external assistant GGUFs and Qwen 3.5 targets with embedded NextN layers.
- Advanced `reasoning_budget` control for recognized Qwen `<think>` and Gemma channel formats, with explicit validation for unsupported templates.
- Request-local Native MTP acceptance, completion, throughput, finish-reason, provider, and NextN diagnostics in `metrics_json.speculative`.

### Changed

- Experimental Speculative Generate now supports an explicit target-only `none` mode, uses `[none]` for an unselected draft, and shares conservative `spec_n_max=2`, `spec_n_min=0`, and `spec_p_min=0.0` defaults across native providers.
- Qwen 3.5 thinking controls now reach text-only GGUF Jinja templates even without an `mmproj`, and response extraction handles templates that prefill the opening `<think>` tag.
- `reasoning_strength` now defaults to `auto`; thinking-specific widgets are disabled while thinking is off without losing their values.
- Speculative and MTP widgets are enabled only for applicable modes, while Sampling and Runtime preset connections continue to preserve overridden widget values.
- Text-only llama.cpp requests no longer resolve or load a selected multimodal projector when no media is connected.

### Compatibility

- Native MTP requires an experimental `llama-cpp-python` build with `draft-mtp`, external/internal MTP bridging, and speculative ABI v2; the earlier DFlash/DSpark-only wheel is insufficient.
- Native MTP is currently text-only, requires `gpu_layers=all`, and does not support context shifting, grammar constraints, custom logits processors, state-cache reuse, or multi-sequence batching.
- Qwen 3.5 internal MTP requires embedded NextN layers and no separate draft GGUF; Gemma 4 external MTP requires a matching assistant GGUF.

## 0.4.0 - 2026-08-11

### Added

- `Muse Glimmer Response Parser`, a dedicated non-streaming string parser with separate response, thinking, unclassified raw, and final-response validity outputs.
- `Llama.cpp Speculative Generate (Experimental)` under `Ollama / llama_cpp / experimental`, with a dedicated draft GGUF selector, DFlash/DSpark parameters, acceptance statistics, and target/draft cleanup.
- `Llama.cpp N-gram Speculative Preset` for optional model-free `LlamaNGramMapDecoding` on the normal Generate node, including `off`/`ngram`, k/k4v, hit, memory-cap, and history-sync controls.
- Advanced `reasoning_strength` control with `low`, `medium`, `high`, and `xhigh` values on both llama.cpp Generate nodes.
- Unit coverage for target-only isolation, speculative construction order and parameter forwarding, pre-close statistics capture, validation, and initialization-failure cleanup.

### Changed

- Speculative Generate now checks its experimental Python API at Job start and reports release notes plus the compatible CPython 3.13/CUDA 13.2 Windows wheel before any media or model loading.
- N-gram detail widgets are disabled without losing their values while its Preset mode is `off`; normal Generate sampling and runtime widgets behave the same way while their corresponding typed presets are connected.
- Experimental node schema cloning now uses the V3 input `id`, preventing the extension entrypoint from being skipped by current ComfyUI builds.
- Muse-Glimmer Auto requests preserve the model's embedded chat template while adapting OpenAI `image_url` parts to the template-native `image` representation required to emit `<|patch|>` markers.
- `thinking=false` now takes precedence over the selected reasoning strength and sends disabled Boolean controls plus `reasoning_strength=low`; `thinking=true` uses the selected strength.
- Speculative Generate places `reasoning_strength` directly below `thinking`; the published normal Generate keeps the new widget at the end for positional workflow compatibility.

### Compatibility

- Native DFlash/DSpark generation requires the separately published experimental `llama-cpp-python` wheel documented in the node error and llama.cpp guide.
- Explicit Generic handling retains the existing OpenAI `image_url` representation; the Muse-specific conversion applies only to Auto with `general.architecture=muse-glimmer`.

## 0.3.0 - 2026-08-10

### Added

- `CLIP Generate Text (Image List)`, based on ComfyUI's official Generate Text API, with system-role prompts, Qwen3-VL/Qwen3.5/Gemma 4 format selection, thinking support, and one-call IMAGE data lists.
- Runtime detection of Gemma 4's named `images` tokenizer parameter from ComfyUI PR #15450, with a same-resolution batch fallback for older ComfyUI builds.

### Changed

- The CLIP text-generation seed now exposes ComfyUI's after-generation control, including automatic randomization, increment, decrement, and fixed modes.

### Compatibility

- The minimum ComfyUI version is now 0.19.3 for the official Generate Text dynamic sampling schema.
- Gemma 4 lists containing different resolutions require a ComfyUI build with explicit `images=` tokenizer support; older builds fail without resizing or discarding images.
- Gemma 4 AUDIO remains available through the official default template. A separate system prompt plus AUDIO is rejected until ComfyUI exposes a public audio placeholder formatter.

## 0.2.0 - 2026-08-08

### Added

- Optional native JamePeng `llama-cpp-python` backend with lazy dependency loading.
- `Llama.cpp Generate (Multimodal)` with IMAGE, AUDIO, and VIDEO list inputs in one chat completion.
- GGUF and multimodal-projector discovery from ComfyUI `LLM` paths, including `extra_model_paths.yaml`.
- Generic and model-specific MTMD handlers for Gemma 4, Qwen 3 VL, Qwen 2.5 VL, and Qwen 3 ASR where provided by the installed fork.
- Explicit thinking control and separate response/thinking outputs.
- Sampling and Gemma 4 runtime preset nodes.
- Typed MTMD media diagnostics with capability flags and evaluated media counts.
- Example native multimodal workflow and detailed installation, configuration, and troubleshooting documentation.

### Changed

- Native llama.cpp executions are serialized and close the model, context, KV cache, and projector after every completion or failure.
- Less frequently adjusted llama.cpp generation settings are Advanced inputs.
- llama.cpp nodes are grouped under `Ollama / llama_cpp`; Ollama REST nodes remain under `Ollama / Image List`.
- The Gemma 4 Runtime Preset output order is `runtime`, `n_ctx`, then `max_tokens`.
- VIDEO uses the fork's native `libmtmd` path and requires a wheel built with `MTMD_VIDEO`; no separately installed FFmpeg executable is required by this node.
- Workflow preview images use WebP to reduce repository and release-archive size.
- Tag releases build on Ubuntu while reusing the cross-platform PowerShell archive script.

### Compatibility

- The Registry package ID remains `ollama-image-list`.
- Manual archives are named `ComfyUI-Ollama-ImageList-<version>.zip` with a `ComfyUI-Ollama-ImageList` top-level folder.
- `llama-cpp-python` remains an optional dependency and must be installed into the Python environment that starts ComfyUI.
- Workflows created before the Runtime Preset output reorder may need those three links reconnected.

## 0.1.0

- Initial stateless Ollama `/api/chat` release with deterministic IMAGE batch and data-list normalization.
