# ComfyUI Ollama Image List

ComfyUI V3 custom nodes that send a single stateless Ollama `/api/chat` request containing all supplied images. Image batches, ComfyUI data lists, nested lists, and lists of batches are flattened deterministically while each image keeps its original width, height, channels, and order.

## Nodes

- **Ollama Image List Connectivity** — fetches available models from an Ollama server and outputs the selected URL and model name.
- **Ollama Image List Options** — builds Generate-compatible options dictionary and JSON outputs from individually enabled Ollama runtime parameters.
- **Ollama Generate (Image List)** — sends the system prompt, user prompt, and all normalized images in one non-streaming request.
- **Ollama Image List Media Bundle** — normalizes and reuses image lists while exposing a payload-free manifest.

## Install

Clone this repository into `ComfyUI/custom_nodes`. Runtime dependencies are provided by ComfyUI.

To run the development tests, sync the development environment:

```bash
uv sync --locked --group dev
```

Ollama and `llama-cpp-python` Python packages are not required. The node uses Python's standard HTTP client and expects an Ollama server, which defaults to `http://127.0.0.1:11434`.

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

Connect the first `options dict` output directly to the generate node's `options` input for normal use. The second `options JSON` output is provided for debugging, manual inspection, and string-based utility nodes. A selected `stop` string is encoded as the one-item array required by Ollama's HTTP API.

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

## Audio status

ComfyUI AUDIO values are normalized into PCM16 WAV items, but Ollama currently has no documented native audio field. The default `audio_transport=disabled` therefore returns an explicit error when audio is connected.

`experimental_wav_in_images` is an explicit, unofficial compatibility attempt that places WAV bytes in Ollama's `images` array. It may fail or behave unpredictably depending on the model and server. `native` remains reserved for a future documented Ollama API and currently fails clearly.

## Privacy and limits

Images and experimental audio are transmitted to the configured Ollama URL. A non-loopback or remote URL can therefore receive private media. URL credentials and media payloads are excluded from manifests and backend error summaries.

Default safeguards limit image count, pixels per image, audio duration, nesting depth, raw tensor size, and encoded payload size. Limit violations fail before the HTTP request; no automatic fallback changes request meaning.

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

`v0.1.0` targets Ollama image single/batch/data-list support with non-streaming response, thinking, metrics, unit tests, and a mock-server integration test. Capability diagnostics, real-model compatibility results, stable Media Bundle workflows, experimental audio verification, and optional `llama-cpp-python` support follow in later milestones described by `PLAN.md`.

## License

MIT
