# llama.cpp server session design

## Contract

- Add `[llama.cpp] Connect Session` alongside the existing `[llama.cpp] Create Native Session`. Both feed the existing `session` socket on `[llama.cpp] Generate` and Unload Session.
- The node has a server base URL, an available-models COMBO, and an editable `model` STRING. `model` is the saved execution value; selecting the COMBO copies its ID into `model`. A workflow can execute from the saved URL and `model` after reload without fetching suggestions.
- Place a **Connect** button first in the node's widgets. Pressing it asks a ComfyUI backend route to GET `<server>/models`; the browser never contacts the remote server directly. Do not fetch automatically on node creation or reload. A failed fetch leaves the saved `model` intact and shows the error.
- `GET /models` is expected to return `data` entries with string `id` values. A single-model server and a router server both use this shape. An empty or malformed response must not silently replace the saved model.

## Execution and ownership

- When Connect Session executes in a workflow, it first GETs `<server>/health` and requires a JSON response with `status: "ok"`. On any failed or non-ready response, it raises an error without emitting a session. A successful check creates a small remote session handle containing the URL and raw model ID; it does not import `llama_cpp` or load a local model.
- Generate keeps its output contract and sends non-streaming chat requests to the server's `/v1/chat/completions`. The remote adapter maps its result to the existing response, thinking, raw JSON, metrics, and media diagnostics outputs. Unsupported media must fail explicitly.
- Unload Session sends `POST <server>/models/unload` with `{"model": "<raw model ID>"}`, then closes the local handle. Repeated close calls must not send duplicate unload requests. The existing prompt-end cleanup behavior must also cover a remote session left open after interruption or failure.
- Validate URL scheme/host and nonempty model at execution; redact large request or response payloads from errors. Keep custom node parameter names in `snake_case`.

## Work sequence and review

1. Reuse the current Ollama Connectivity proxy and widget behavior where they fit, with a separate llama.cpp route and explicit Connect action.
2. Add the remote session adapter and route both session types through existing Generate/Unload nodes.
3. Register the new node and frontend extension. Preserve node IDs and all existing native sockets.
4. Leave focused runnable checks for model parsing, workflow health gating, remote generation, and unload behavior. Per repository instructions, do not run validation unless requested.

Official references: [llama.cpp server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [ComfyUI frontend hooks](https://docs.comfy.org/custom-nodes/js/javascript_hooks).
