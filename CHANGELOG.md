# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- `CLIP Generate Text (Image List)`, based on ComfyUI's official Generate Text API, with system-role prompts, Qwen3-VL/Qwen3.5/Gemma 4 format selection, thinking support, and one-call IMAGE data lists.
- Runtime detection of Gemma 4's named `images` tokenizer parameter from ComfyUI PR #15450, with a same-resolution batch fallback for older ComfyUI builds.

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
