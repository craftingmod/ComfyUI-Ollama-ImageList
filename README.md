# ComfyUI-Ollama-ImageList

![JPG Banner](./docs/icon.jpg)

ComfyUI V3 custom nodes that analyze image lists through either one stateless Ollama `/api/chat` request or one directly loaded `llama-cpp-python` GGUF model. The llama.cpp node additionally accepts ComfyUI AUDIO and VIDEO and can submit mixed media when the selected model, projector, and native build support those modalities. Batches, data lists, nested lists, and lists of batches are flattened deterministically while their traversal order is preserved.

## Nodes

Nodes are grouped by backend in ComfyUI's Add Node menu.

### Ollama / Image List

![Ollama Workflow Example](./workflows/Simple_Vision.png)

Workflow example: [Simple_Vision.json](./workflows/Simple_Vision.json)

- **Ollama Image List Connectivity** — fetches available models from an Ollama server and outputs the selected URL and model name.
- **Ollama Image List Options** — builds Generate-compatible options dictionary and JSON outputs from individually enabled Ollama runtime parameters.
- **Ollama Generate (Image List)** — sends the system prompt, user prompt, and all normalized images in one non-streaming request.

### Ollama / llama_cpp

![Native Workflow Example](./workflows/Native_Vision.png)

Workflow example: [Native_Vision.json](./workflows/Native_Vision.json)

- **Llama.cpp Sampling Preset** — supplies image-analysis, Gemma 4, or llama.cpp-default sampling values through one typed connection.
- **Llama.cpp Gemma 4 Runtime Preset** — supplies Gemma 4 context and output-length integers plus a typed physical-batch and image-token profile.
- **Llama.cpp Generate (Multimodal)** — loads a local GGUF and optional multimodal projector, analyzes optional IMAGE, AUDIO, and VIDEO inputs in one request, and immediately closes the model and handler.
- **Llama.cpp Media Diagnostics** — expands the Generate node's typed MTMD receipt into capability flags, evaluated media counts, JSON, and formatted text.

## Install

Search `ollama-imagelist` in `ComfyUI Manager's nodes manager` and install `Ollama-ImageList`.

Also you can clone this repository into `ComfyUI/custom_nodes`. Runtime dependencies are provided by ComfyUI.

To run the development tests, sync the development environment:

```bash
uv sync --locked --group dev
```

### Ollama Nodes

The Ollama nodes require no additional Python package. They use Python's standard HTTP client and expect an Ollama server, which defaults to `http://127.0.0.1:11434`.

### llama_cpp Nodes

The llama.cpp backend is optional. Its nodes still register when `llama-cpp-python` is absent, but executing Generate reports that the optional dependency is unavailable. Install a compatible wheel into the exact Python environment that runs ComfyUI, then restart ComfyUI. This project deliberately does not declare it as a package dependency because automatic installation could compile or select an incompatible CPU-only or CUDA build. The MTMD-enabled fork used during development publishes Windows CUDA wheels at [JamePeng/llama-cpp-python releases](https://github.com/JamePeng/llama-cpp-python/releases). VIDEO requires a wheel built with `MTMD_VIDEO` support; no separate FFmpeg executable is required by this node.

See [Native llama.cpp backend](docs/LLAMA_CPP.md) for installation constraints, model layout, node wiring, preset values, modality behavior, and troubleshooting.

## Input semantics

A ComfyUI IMAGE batch and a data list are different:

- A batch is one tensor shaped `[B,H,W,C]`; all entries normally share H×W.
- A data list is a list of independent values and may contain tensors with different H×W.

The nodes declare V3 `is_input_list=True`, so ComfyUI passes the complete data list to one execution instead of mapping the node over each item. The normalizer recursively splits every batch and preserves traversal order. Each image is independently encoded as PNG; it is never resized, cropped, padded, letterboxed, or combined into a montage.

The implementation follows ComfyUI's official [data list semantics](https://docs.comfy.org/custom-nodes/backend/lists) and [V3 migration/schema reference](https://docs.comfy.org/custom-nodes/v3_migration).

All scalar inputs (`url`, `model`, prompts, and options) must resolve to exactly one value. Supplying a data list of multiple prompts is an error rather than silently choosing one.

## llama.cpp quick start

1. Install a compatible optional `llama-cpp-python` build in ComfyUI's Python environment.
2. Put the main model GGUF and its matching multimodal projector under `ComfyUI/models/LLM`, or register an `LLM` directory through `extra_model_paths.yaml`.
3. Add **Llama.cpp Generate (Multimodal)** from `Ollama / llama_cpp`, select the main GGUF and `mmproj`, and connect any IMAGE, AUDIO, or VIDEO inputs.
4. Optionally connect **Llama.cpp Sampling Preset**. For Gemma 4, connect the Runtime Preset's `runtime`, `n_ctx`, and `max_tokens` outputs to the matching Generate inputs.
5. Connect `media_diagnostics` to **Llama.cpp Media Diagnostics** when verifying native ingestion.

All connected media lists are normalized into one user message and one chat completion. The node does not map one prompt over each list item. The model and projector are closed after that completion, including on failure.

## Ollama connectivity

The connectivity node contains `url`, `available_models`, and editable `model` widgets plus a **Fetch** button. It requests the model list when the node is created and whenever **Fetch** is pressed. Choosing an entry in `available_models` copies the exact name into `model`; the model field remains editable for names that are not currently reported by the server.

Model discovery is proxied through the ComfyUI server to Ollama's `GET /api/tags` endpoint, avoiding browser CORS restrictions. The node outputs independent `URL` and `model` strings that can be connected directly to the generate node.

## Ollama options

The options node exposes an **Include/Ignore** toggle followed by a typed value widget for each documented parameter. Disabled parameters are omitted rather than being sent with their displayed defaults. The inputs are ordered as `num_ctx`, `num_predict`, `temperature`, `top_p`, `top_k`, `min_p`, `repeat_penalty`, `repeat_last_n`, `seed`, `stop`, and `draft_num_predict`.

Connect the first `options` output directly to the generate node's `options` input for normal use. The second `options_json` output is provided for debugging, manual inspection, and string-based utility nodes. A selected `stop` string is encoded as the one-item array required by Ollama's HTTP API.

## Ollama request

The generate node creates one request with this logical structure:

```text
system message + user message + images[] -> POST /api/chat -> response/thinking/metrics
```

`system` is placed in a system-role message and `prompt` is placed in the current user-role message without trimming or rewriting. Images belong only to that request; this node does not create a persistent session or preserve them in later history.

Use the `options` dictionary input for Ollama generation options such as `temperature`, `top_p`, `top_k`, `min_p`, `seed`, `num_ctx`, `num_predict`, `repeat_penalty`, and `stop`. The advanced `options_json` field remains available as a manual fallback. If both are supplied, the connected dictionary takes precedence, including an empty dictionary. `format_json` accepts an empty value, the literal `json`, or a JSON Schema object.

Enable `unload_after_response` to send `keep_alive: 0`, which tells Ollama to unload the model as soon as the response is complete. This overrides the `keep_alive` input while enabled; when disabled, the configured keep-alive value is used as before.

To verify that a data list produced one request, enable Ollama server logging and look for one `POST /api/chat`, or enable the node's `debug` option and inspect the payload-free request manifest. The manifest includes counts, dimensions, byte sizes, hashes, and prompt character counts, but never base64 payloads or prompt text.

Model support for multiple images varies. If a model or server rejects a request, the node reports the backend error and does not resize, remove, montage, or split images into multiple calls.

Request and response fields follow Ollama's official [Chat API](https://docs.ollama.com/api/chat).

## llama.cpp request and unload behavior

`Llama.cpp Generate (Multimodal)` lists `.gguf` files recursively from every path registered under ComfyUI's `LLM` model category, including `LLM` entries loaded from `extra_model_paths.yaml`. The local `ComfyUI/models/LLM` directory is appended as a fallback. Duplicate absolute paths are removed while preserving ComfyUI's registered order. Both the main-model Combo and projector Combo expose the complete, unfiltered `.gguf` list; the projector Combo additionally provides `[none]` and stably prioritizes filenames containing `mmproj`. The selected relative names are resolved again through ComfyUI's `folder_paths` API at execution time, so a workflow cannot escape the registered model directories with a crafted relative path.

For image, audio, or video requests, choose the `mmproj` GGUF built for the exact main-model family and modality. `handler=auto` uses the fork's metadata-driven generic MTMD handler. Model-specific `gemma4`, `qwen3_vl`, `qwen25_vl`, and `qwen3_asr` handlers are available when a model requires specialized template or stop-token behavior.

`thinking` is an explicit Boolean request rather than a model-default mode. It maps to `enable_thinking` for Gemma 4, `force_reasoning` for Qwen 3 VL, and both template arguments for the generic MTMD path. A model or checkpoint without a compatible template switch may ignore it; in particular, the option cannot turn an Instruct-only checkpoint into a Thinking checkpoint.

`override_n_ubatch` and `override_image_max_tokens` control whether their adjacent integer widgets are passed to llama-cpp-python. With an override disabled, the integer is ignored and the backend or mmproj default remains authoritative. For image and video requests with an explicit image-token ceiling, the node validates `n_ctx`, `n_batch`, and the effective physical batch before loading the model. This prevents Gemma 4's non-causal vision encoder from reaching a native assertion when the image token chunk is larger than `n_ubatch`. A Gemma 4 ceiling of 1120 therefore also requires `n_batch>=1120` and an enabled `n_ubatch` override of at least 1120.

Connect `Llama.cpp Sampling Preset` to the optional `sampling` input to override `temperature`, `top_p`, `top_k`, `min_p`, and `repeat_penalty` together. When no preset is connected, the five widgets on the Generate node remain authoritative, preserving existing workflows.

`Llama.cpp Gemma 4 Runtime Preset` places its typed `runtime` output first, followed by separate `n_ctx` and `max_tokens` integer outputs for direct connections to the Generate node's always-visible inputs. `runtime` overrides only the Advanced `n_batch`, `n_ubatch`, `image_max_tokens`, and two override switches. This keeps context and output-length changes visible as graph connections while retaining one compact connection for the related multimodal batch settings. The profiles are named for Gemma 4 because their image-token and physical-batch values were selected for Gemma 4's dynamic-resolution vision encoder; other model families may need different values. `Vision Long / Thinking` reserves enough output room for reasoning but deliberately does not change the Generate node's explicit `thinking` Boolean.

The node intentionally has no model-loader output and no cache policy. Every execution follows this lifecycle:

```text
normalize media -> load GGUF/mmproj -> one chat completion -> Llama.close() -> garbage collection
```

Native executions are serialized so two ComfyUI branches cannot load separate llama.cpp models concurrently. Cleanup runs in `finally`, including when loading or generation raises an exception. `metrics_json.model_unloaded` confirms that explicit cleanup completed. The model, context, KV cache, and multimodal projector are not retained by this node; the loaded CUDA driver context and native DLLs may keep a small process-level baseline allocation until ComfyUI exits.

Input images are embedded as independent lossless PNG data URIs. ComfyUI AUDIO tensors are encoded as lossless PCM16 WAV payloads and attached as `input_audio`. A ComfyUI VIDEO object's original encoded stream is read without decoding it in Python and passed as an internal `video` content part containing a base64 data URI; this form is compatible with model-provided templates such as Gemma 4 that ignore `video_url`. The fork's native `libmtmd` video helper decodes the stream when `MTMD_VIDEO` was enabled at wheel build time. The node exposes only a `video` socket, not a URL widget. Embedded video audio is not ingested by llama.cpp's current video path, so connect AUDIO separately when the soundtrack is required. Media are placed in one multimodal user message in IMAGE, AUDIO, then VIDEO group order. `mmproj_path` is mandatory whenever any media are connected but may be `[none]` for text-only GGUF models. Use `gpu_layers=all` for normal GPU offload, and start with the context size recommended by the selected model.

The Generate node emits one typed `media_diagnostics` object rather than formatting diagnostics itself. Connect it to `Llama.cpp Media Diagnostics` to obtain `All Media Evaluated`, Vision/Audio/Video availability, evaluated IMAGE/AUDIO/VIDEO counts, full JSON, and a compact formatted receipt. With the supported fork, a successful `mtmd_evaluated` receipt means every requested media item passed capability checks, decoding, marker/chunk validation, and native MTMD evaluation. It does not claim that the language model interpreted the media correctly. Only payload-free metadata and hashes survive model cleanup; native handlers and pointers are never retained.

### Supported model format

| Input | Supported scope |
| --- | --- |
| Main model | A single-file `.gguf` model whose architecture is supported by the installed llama.cpp build |
| Text-only chat | GGUF with a usable embedded chat template, or a format recognized by llama-cpp-python |
| Vision with `auto`/`generic` | Main GGUF plus matching MTMD-compatible `mmproj` GGUF whose template uses media markers understood by the fork |
| Explicit Vision handlers | Gemma 4, Qwen 3 VL, and Qwen 2.5 VL |
| Audio with `auto`/`generic` | Audio-capable main GGUF plus its matching multimodal projector and template |
| Explicit audio handler | Qwen 3 ASR through `qwen3_asr` when provided by the installed llama-cpp-python build |
| Video with `auto`/`generic` | Video-capable main GGUF plus matching projector and a fork wheel built with `MTMD_VIDEO` support |
| Not accepted | Safetensors/Transformers directories, PyTorch checkpoints, ONNX, Ollama model names, and arbitrary non-GGUF files |

GGUF is a container, not a guarantee that every model is compatible. The main model, projector, handler, requested modalities, and context size must agree. A file named `mtp-*.gguf` is a speculative-decoding MTP/draft model, not a multimodal projector, and must not be selected as `mmproj_path`.

## Public scope

The Ollama Generate node remains image-only. `Llama.cpp Generate (Multimodal)` exposes separate optional IMAGE, AUDIO, and VIDEO inputs. The experimental Media Bundle node and `audio_transport` option are still not registered; llama.cpp performs its own local media message construction without routing media through Ollama.

## Privacy and limits

Images connected to the Ollama node are transmitted to its configured URL. A non-loopback or remote URL can therefore receive private images. Media connected to the llama.cpp node remains in the local process. URL credentials and media payloads are excluded from manifests and backend error summaries.

Default safeguards limit image, audio, and video item counts, pixels per image, audio/video duration, nesting depth, raw tensor size, and encoded payload size. Limit violations fail before inference; no automatic fallback changes request meaning.

## Development

```bash
uv run pytest
```

See [testing documentation](docs/TESTING.md) and [implementation status](docs/IMPLEMENTATION_STATUS.md).

To replace the node installed in the local portable ComfyUI instance with the current runtime package, run:

```powershell
./scripts/deploy-to-portable.ps1
```

Use `-WhatIf` to inspect the fixed deployment target without replacing it. Restart ComfyUI after deployment.

## Roadmap

`v0.1.0` established Ollama image single/batch/data-list support. Native `llama-cpp-python` image, audio, and video generation is now available as an optional, explicitly unloaded backend with typed MTMD ingestion diagnostics. Broader real-model multimodal compatibility results and the optional Media Bundle remain later milestones described by `PLAN.md`.

## License

MIT
