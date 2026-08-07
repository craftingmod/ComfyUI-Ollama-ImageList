# ComfyUI Ollama Image List

![JPG Banner](./docs/icon.jpg)

ComfyUI V3 custom nodes that analyze image lists through either one stateless Ollama `/api/chat` request or one directly loaded `llama-cpp-python` GGUF model. The llama.cpp node additionally accepts ComfyUI AUDIO and can submit images and audio together when the selected model and projector support those modalities. Batches, data lists, nested lists, and lists of batches are flattened deterministically while their traversal order is preserved.

## Nodes

![Workflow Example](./workflows/Simple_Vision.avif)

Workflow example: [Simple_Vision.json](./workflows/Simple_Vision.json)

- **Ollama Image List Connectivity** — fetches available models from an Ollama server and outputs the selected URL and model name.
- **Ollama Image List Options** — builds Generate-compatible options dictionary and JSON outputs from individually enabled Ollama runtime parameters.
- **Ollama Generate (Image List)** — sends the system prompt, user prompt, and all normalized images in one non-streaming request.
- **Llama.cpp Sampling Preset** — supplies image-analysis, Gemma 4, or llama.cpp-default sampling values through one typed connection.
- **Llama.cpp Generate (Multimodal)** — loads a local GGUF and optional multimodal projector, analyzes optional IMAGE and AUDIO inputs in one request, and immediately closes the model and handler.

## Install

Clone this repository into `ComfyUI/custom_nodes`. Runtime dependencies are provided by ComfyUI.

To run the development tests, sync the development environment:

```bash
uv sync --locked --group dev
```

The Ollama nodes require no additional Python package. They use Python's standard HTTP client and expect an Ollama server, which defaults to `http://127.0.0.1:11434`.

The llama.cpp node is optional. Install a compatible `llama-cpp-python` wheel into the exact Python environment that runs ComfyUI, then restart ComfyUI. This project does not declare it as a package dependency because automatic installation could compile an incompatible CPU-only or CUDA build. The JamePeng fork supplies current multimodal handlers and prebuilt Windows CUDA wheels: [JamePeng/llama-cpp-python releases](https://github.com/JamePeng/llama-cpp-python/releases).

## Input semantics

A ComfyUI IMAGE batch and a data list are different:

- A batch is one tensor shaped `[B,H,W,C]`; all entries normally share H×W.
- A data list is a list of independent values and may contain tensors with different H×W.

The nodes declare V3 `is_input_list=True`, so ComfyUI passes the complete data list to one execution instead of mapping the node over each item. The normalizer recursively splits every batch and preserves traversal order. Each image is independently encoded as PNG; it is never resized, cropped, padded, letterboxed, or combined into a montage.

The implementation follows ComfyUI's official [data list semantics](https://docs.comfy.org/custom-nodes/backend/lists) and [V3 migration/schema reference](https://docs.comfy.org/custom-nodes/v3_migration).

All scalar inputs (`url`, `model`, prompts, and options) must resolve to exactly one value. Supplying a data list of multiple prompts is an error rather than silently choosing one.

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

For image or audio requests, choose the `mmproj` GGUF built for the exact main-model family and modality. `handler=auto` uses the fork's metadata-driven generic MTMD handler. Model-specific `gemma4`, `qwen3_vl`, `qwen25_vl`, and `qwen3_asr` handlers are available when a model requires specialized template or stop-token behavior.

Connect `Llama.cpp Sampling Preset` to the optional `sampling` input to override `temperature`, `top_p`, `top_k`, `min_p`, and `repeat_penalty` together. When no preset is connected, the five widgets on the Generate node remain authoritative, preserving existing workflows.

The node intentionally has no model-loader output and no cache policy. Every execution follows this lifecycle:

```text
normalize media -> load GGUF/mmproj -> one chat completion -> Llama.close() -> garbage collection
```

Native executions are serialized so two ComfyUI branches cannot load separate llama.cpp models concurrently. Cleanup runs in `finally`, including when loading or generation raises an exception. `metrics_json.model_unloaded` confirms that explicit cleanup completed. The model, context, KV cache, and multimodal projector are not retained by this node; the loaded CUDA driver context and native DLLs may keep a small process-level baseline allocation until ComfyUI exits.

Input images are embedded as independent lossless PNG data URIs. ComfyUI AUDIO tensors are encoded as lossless PCM16 WAV payloads and attached as `input_audio`. The prompt, images, and audio are placed in one OpenAI-style multimodal user message, with all images followed by all audio items. `mmproj_path` is mandatory whenever image or audio media are connected but may be `[none]` for text-only GGUF models. Use `gpu_layers=all` for normal GPU offload, and start with the context size recommended by the selected model.

### Supported model format

| Input | Supported scope |
| --- | --- |
| Main model | A single-file `.gguf` model whose architecture is supported by the installed llama.cpp build |
| Text-only chat | GGUF with a usable embedded chat template, or a format recognized by llama-cpp-python |
| Vision with `auto`/`generic` | Main GGUF plus matching MTMD-compatible `mmproj` GGUF whose template uses media markers understood by the fork |
| Explicit Vision handlers | Gemma 4, Qwen 3 VL, and Qwen 2.5 VL |
| Audio with `auto`/`generic` | Audio-capable main GGUF plus its matching multimodal projector and template |
| Explicit audio handler | Qwen 3 ASR through `qwen3_asr` when provided by the installed llama-cpp-python build |
| Not accepted | Safetensors/Transformers directories, PyTorch checkpoints, ONNX, Ollama model names, and arbitrary non-GGUF files |

GGUF is a container, not a guarantee that every model is compatible. The main model, projector, handler, requested modalities, and context size must agree. A file named `mtp-*.gguf` is a speculative-decoding MTP/draft model, not a multimodal projector, and must not be selected as `mmproj_path`.

## Public scope

The Ollama Generate node remains image-only. `Llama.cpp Generate (Multimodal)` exposes separate optional IMAGE and AUDIO inputs. The experimental Media Bundle node and `audio_transport` option are still not registered; llama.cpp performs its own local WAV message construction without routing audio through Ollama.

## Privacy and limits

Images connected to the Ollama node are transmitted to its configured URL. A non-loopback or remote URL can therefore receive private images. Media connected to the llama.cpp node remains in the local process. URL credentials and media payloads are excluded from manifests and backend error summaries.

Default safeguards limit image and audio item counts, pixels per image, audio duration, nesting depth, raw tensor size, and encoded payload size. Limit violations fail before inference; no automatic fallback changes request meaning.

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

`v0.1.0` established Ollama image single/batch/data-list support. Native `llama-cpp-python` image and audio generation is now available as an optional, explicitly unloaded backend. Capability diagnostics, broader real-model multimodal compatibility results, and the optional Media Bundle remain later milestones described by `PLAN.md`.

## License

MIT
