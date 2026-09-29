# Native llama.cpp backend

The Generate nodes under `llama_cpp` run a GGUF model directly inside the ComfyUI process through `llama-cpp-python`. They are intended for stateless text or multimodal chat completion. The workflow-owned Runtime Session nodes instead launch a local `llama server` process and keep its model loaded until the session closes; they do not require `llama-cpp-python`.

## Optional dependency

`llama-cpp-python` is intentionally not listed as a package dependency. A usable wheel must match all of the following:

- the operating system and CPU architecture;
- the Python ABI of the interpreter that starts ComfyUI;
- the desired native backend, such as CPU, CUDA, ROCm, Vulkan, or Metal;
- the model, projector, handler, and modality features required by the workflow.

Install the wheel into ComfyUI's actual Python environment, not an unrelated system Python. For a Windows portable installation, invoke that installation's embedded Python. Restart ComfyUI after installation.

The CUDA tag on a PyTorch build does not select the llama.cpp wheel. PyTorch and llama.cpp load separate native runtimes; the llama.cpp wheel must be compatible with the installed NVIDIA driver and with the runtime expected by that wheel. It does not need to have the same CUDA tag as PyTorch merely because both packages are used in the same ComfyUI process.

This implementation targets the fork API used by the multimodal wheels published at [JamePeng/llama-cpp-python releases](https://github.com/JamePeng/llama-cpp-python/releases). The [ComfyUI-ThinkingLLM installation notes](https://github.com/goodguy1963/ComfyUI-ThinkingLLM/blob/main/docs/LLAMA_CPP_PYTHON_VISION_INSTALL.md) provide a practical fork-wheel installation reference. Other builds may omit the generic MTMD handler, audio/video capability flags, handler arguments, or diagnostics used here.

The custom node package and all Ollama nodes still load when this dependency is missing. Only an attempted llama.cpp Generate execution fails with an optional-dependency error, which includes the installation guide and JamePeng wheel-release links above.

VIDEO input requires a fork wheel built with `MTMD_VIDEO` support. The native `libmtmd` helper performs video decoding; this node does not require a separately installed FFmpeg executable.

## Model discovery

The Generate node scans `.gguf` files recursively from:

1. every ComfyUI model path whose category name is `LLM`, case-insensitively;
2. `ComfyUI/models/LLM` as a local fallback.

This includes `LLM` paths contributed by `extra_model_paths.yaml`. For example:

```yaml
shared_models:
  base_path: D:/AI/models
  LLM: LLM
```

Both `model_path` and `mmproj_path` show the complete GGUF inventory. Filenames are not used to reject user selections. The projector Combo provides `[none]` and places filenames containing `mmproj` first as a convenience. An `mtp-*.gguf` file is normally a speculative-decoding draft model, not a multimodal projector.

The experimental Speculative Generate node adds a `draft_model` Combo from the same inventory directly below `mmproj_path`. It stably prioritizes filenames containing `dflash`, `dspark`, `draft`, or `mtp`, but does not infer target compatibility from a filename.

After adding files or changing `extra_model_paths.yaml`, restart ComfyUI or refresh the node definitions. A saved relative selection is resolved through ComfyUI's registered model paths again at execution time.

## Optional local llama.cpp server

The **Internal llama.cpp runtime activation** setting starts the `llama server` executable on `127.0.0.1`. A `llama` executable on ComfyUI's `PATH` takes priority; otherwise, the runtime uses a completed internal b11146 installation if one is available. ComfyUI starts a Python supervisor with its own interpreter; the supervisor owns the server process and watches a private lifetime pipe. It reports `running` only after `/health` returns `{"status":"ok"}`. Startup is bounded to 30 seconds.

### Downloading the local runtime

In ComfyUI Settings, open **Ollama-ImageList → llama.cpp Daemon** and use **Download llama.cpp** when no `llama` executable is available on `PATH`. The button is offered only for a supported environment without an existing internal installation. The downloader selects the release asset from the OS and CPU architecture of the ComfyUI process and, on Windows/Linux, the CUDA or ROCm backend reported by ComfyUI's own PyTorch. It checks the official b11146 asset digest before installation. It does not change the system `PATH` or install `llama-cpp-python`; this download is only for the optional local server in this section.

The files are stored under ComfyUI's protected system-user directory, returned by [`folder_paths.get_system_user_directory("llama_cpp")`](https://github.com/Comfy-Org/ComfyUI/blob/master/folder_paths.py): `<ComfyUI user directory>/__llama_cpp/artifacts/b11146/<os>-<arch>-<backend>/`. ComfyUI's configured user directory is used; the operating-system home directory is not. A successful install becomes the fallback executable when `PATH` has no `llama`. If internal runtime activation is already enabled, ComfyUI attempts to start the server after installation; otherwise enable **Internal llama.cpp runtime activation**.

The b11146 downloader supports these release combinations. The linked [official release](https://github.com/ggml-org/llama.cpp/releases/tag/b11146) lists these assets; its [build attestation](https://github.com/ggml-org/llama.cpp/attestations/49623059) provides the digests used for verification.

| ComfyUI environment | llama.cpp asset | Additional asset |
| --- | --- | --- |
| Windows x64 CPU | `llama-b11146-bin-win-cpu-x64.zip` | — |
| Windows arm64 CPU | `llama-b11146-bin-win-cpu-arm64.zip` | — |
| Windows x64 CUDA | `llama-b11146-bin-win-cuda-13.4-x64.zip` | `cudart-llama-bin-win-cuda-13.4-x64.zip` |
| Windows arm64 CUDA | `llama-b11146-bin-win-cuda-13.4-arm64.zip` | `cudart-llama-bin-win-cuda-13.4-arm64.zip` |
| Windows x64 ROCm | `llama-b11146-bin-win-rocm-10.0-x64.zip` | — |
| macOS x64 | `llama-b11146-bin-macos-x64.tar.gz` | — |
| macOS arm64 | `llama-b11146-bin-macos-arm64.tar.gz` | — |
| Linux x64 CPU | `llama-b11146-bin-ubuntu-x64.tar.gz` | — |
| Linux arm64 CPU | `llama-b11146-bin-ubuntu-arm64.tar.gz` | — |
| Linux x64 CUDA | `llama-b11146-bin-ubuntu-cuda-13.4-x64.tar.gz` | `cudart-llama-b11146-bin-ubuntu-cuda-13.4-x64.tar.gz` |
| Linux arm64 CUDA | `llama-b11146-bin-ubuntu-cuda-13.4-arm64.tar.gz` | `cudart-llama-b11146-bin-ubuntu-cuda-13.4-arm64.tar.gz` |
| Linux x64 ROCm | `llama-b11146-bin-ubuntu-rocm-10.0-x64.tar.gz` | — |

Backend selection checks `torch.version.hip`, then `torch.version.cuda`, then CPU. macOS selects its OS/architecture asset regardless of PyTorch MPS. Unsupported combinations are rejected instead of silently falling back to CPU; for example, b11146 has no Windows arm64 or Linux arm64 ROCm asset. Linux packages are built for Ubuntu, so compatibility with other distributions is not guaranteed.

CUDA assets target CUDA 13.4 and include a companion `cudart` runtime archive. They do not install an NVIDIA driver. A CUDA-capable GPU and compatible NVIDIA driver are still required; NVIDIA lists driver 580 as the CUDA 13.x minor-version-compatibility baseline, while CUDA 13.4 features or newly enabled platforms may require the R615 driver branch or later. See the [NVIDIA CUDA release notes](https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/) for current details.

ROCm assets target ROCm 10.0.0 and require a supported AMD GPU, OS, and driver stack. Confirm the exact combination in AMD's [ROCm 10.0 compatibility matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html); installing the llama.cpp archive does not install or update the AMD GPU driver.

If download or installation fails, read the progress/error shown in the Settings entry. For a server startup failure, check the **Internal service state**, **PATH availability**, **llama executable path**, and **llama version** entries in the same section, then inspect the ComfyUI console for the reported launch error. The executable path shows whether the PATH copy or internal installation was selected.

Turning the setting off stops the owned server. Changing its context size, port, or model directory while enabled stops the old server completely before starting the new configuration. The settings show `stopped`, `starting`, `running`, `stopping`, or `failed`.

Use **Restart internal daemon** in the same Settings section to retry a failed or stopped daemon with the saved configuration. The action does not write settings. Runtime activation must be enabled; if it is off, the button explains how to enable it. Restarting can interrupt requests using the internal server; it does not stop external llama.cpp servers or affect **Llama.cpp Connect Session**.

When ComfyUI exits unexpectedly, the lifetime pipe closes and the supervisor shuts down its server. The separate **Llama.cpp Connect Session** node only connects to a server supplied by the workflow; its optional `api_key` input is used for model discovery and generation. It does not own or stop that external server.

## Workflow-owned runtime sessions

`[llama.cpp] Create Native Session`, `[llama.cpp] Create Runtime Session`, `[llama.cpp] Connect Session`, and `[llama.cpp] Unload Session` are in `llama_cpp/session`; `[llama.cpp] Generate (Session)` and `[llama.cpp] Generate (Sequential)` are in `llama_cpp/generate`.

**[llama.cpp] Create Native Session** takes its handler from the connected Model Profile and owns the optional `custom_chat_template` setting. A Generate (Session) Model Profile can override sampling and reasoning per request, but its handler is ignored because the session model and handler are initialized at creation.

**[llama.cpp] Generate (Session)** and **[llama.cpp] Decide (Session)** also accept an optional `model_profile`. On Native Sessions, Generate uses it for per-request sampling and reasoning; the handler remains the one selected when the session was created. Server-backed sessions apply the profile's sampling values and explicit `on`/`off` reasoning mode per request; the server handler and custom Jinja template remain fixed at server startup.

**[llama.cpp] Generate (Sequential)** has the same inputs as **Generate (Session)**. It sends one request per IMAGE, AUDIO, or VIDEO item through the connected session, in modality order. A single `prompt` is shared across items; a prompt list must have one entry per item. Its five outputs are parallel lists. `session_unload` closes the session after the whole sequence.

`[llama.cpp] Create Runtime Session` starts a local `llama server` only when the workflow executes the node. It uses the existing `OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION` socket, so connect it to the existing **Generate (Session)** and **Unload Session** nodes. This path does not require `llama-cpp-python` or enable the always-on Internal runtime. It leaves the daemon's saved settings and running process alone.

Each runtime session assigns its own random API key to the server and keeps that key inside the session handle. Model-list and Generate requests include it automatically, so direct requests to protected server endpoints without the session's key are rejected.

The node resolves the executable the same way as the Internal runtime: a `llama` executable on ComfyUI's `PATH` takes priority, followed by a completed Internal runtime installation. If neither is available, creation fails before returning a session. Each execution starts its own supervised server on an OS-assigned free `127.0.0.1` port; a bind/start conflict fails that execution and does not stop another process. The session is returned only after the server process is alive and `/health` reports `ok`. Startup failure or timeout cleans up the process started by that node.

The node accepts the same model, projector, and typed profiles as **[llama.cpp] Create Native Session**. The model and optional projector are resolved GGUF paths and become `--model` and `--mmproj`; `n_ctx` becomes `--ctx-size`. A disconnected `hardware_profile` uses **Automatic Offload**, allowing llama.cpp to choose the GPU layer count to fit available device memory. The profile's handler is accepted but ignored because the server handles chat templates. Profile sampling values (`temperature`, `top_p`, `top_k`, `min_p`, `presence_penalty`, and `repeat_penalty`) seed the session defaults; a connected `model_profile` on Generate or Decide overrides those values per request. The node's optional `custom_chat_template` input overrides the GGUF metadata template when connected; when disconnected, the GGUF template is used. A non-empty selected template is written to a temporary Jinja file and passed using `--jinja --chat-template-file`; the file is removed after the server exits and the template cannot be replaced per request. `recommended_reasoning_mode` supplies the default when reasoning is disconnected or `auto`; an explicitly conflicting mode fails before launch.

Hardware settings map to server options as follows: `n_batch` to `--batch-size`, positive `n_ubatch` to `--ubatch-size`, `gpu_layers` to `--gpu-layers` (`cpu` becomes `0`), `main_gpu` to `--main-gpu`, positive `n_threads` to `--threads`, and `flash_attention` to `--flash-attn` (`enabled`/`disabled` become `on`/`off`). `use_mmap` maps to `--load-mode mmap` or `--load-mode none`. Zero `n_ubatch` and `n_threads` omit those options. Positive `image_min_tokens` and `image_max_tokens` map to `--image-min-tokens` and `--image-max-tokens`; zero omits the option, and when both are positive, minimum may not exceed maximum. `reasoning_mode` and non-`auto` `reasoning_effort` map to `--reasoning` and `--reasoning-effort`. A positive `max_reasoning_tokens` maps to `--reasoning-budget`; zero omits the option. With reasoning off, effort and budget are omitted. `preserve_thinking` is passed only when the selected executable advertises its corresponding option; otherwise that field is ignored.

Native speculative settings map to `--spec-type` (`draft-mtp`, `draft-dflash`, or `draft-dspark`), `--spec-draft-model`, `--spec-draft-n-max`, `--spec-draft-p-min`, `--spec-draft-ngl`, and the `--spec-draft-backend-sampling` / `--no-spec-draft-backend-sampling` pair. External MTP requires a draft GGUF, while internal MTP does not. N-gram `k` uses `ngram-map-k` with `--spec-ngram-map-k-size-n`, `--spec-ngram-map-k-size-m`, and `--spec-ngram-map-k-min-hits`; `k4v` uses `ngram-map-k4v` with `--spec-ngram-map-k4v-size-n`, `--spec-ngram-map-k4v-size-m`, and `--spec-ngram-map-k4v-min-hits`. Those options receive `ngram_size`, `num_pred_tokens`, and `ngram_min_hits`. `ngram_max_entries_per_key` is accepted but ignored. Off omits speculative options. The session's sampling, hardware, reasoning, and speculative settings remain fixed; Generate's existing request inputs such as `max_tokens`, `seed`, and `stop` still apply per request. `verbose` enables `--verbose`. See the [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) for the server option reference.

Connect **Unload Session** to the session and connect the loop's final `timing` result to its `timing` input so unload runs after the last Generate. Unload closes the owned server; an interrupted workflow also closes tracked sessions at prompt end. If ComfyUI exits abnormally, the supervisor's lifetime pipe detects process exit and shuts down its child. These ownership rules apply only to Runtime Session handles: **Connect Session** retains its existing external-server `/models/unload` behavior and never owns or stops that server.

## Decision sessions

Decision nodes require the optional `llama` dependencies, including `makoto-decision`. **[llama.cpp] Create Native Session** uses the JamePeng `llama-cpp-python` chat-prefill API. **[llama.cpp] Create Runtime Session** formats the decision through the workflow-owned `llama-server` chat template, then uses `/tokenize` and grammar-constrained `/completion` to score candidates. **Connect Session** remains unsupported.

**[llama.cpp] Create Question** accepts one question and 2–26 answer strings. Set `inputcount`, click **Update inputs**, then fill the visible `answer_N` widgets. Reducing the count hides extra answers without deleting their saved values; increasing it restores them. **[llama.cpp] Create Question From Input** accepts one `STRING` question and a flat ComfyUI `STRING` list output. It rejects multiple question values and nested answer lists.

Connect the question output and a Native or Runtime Session to **[llama.cpp] Decide (Session)**. It returns the selected original answer, an input-ordered `probabilities_json` object, and the same session handle for the next operation. The `system` and `context` text are labeled and prepended to the decision context; `makoto-decision` does not provide a separate system-role input here.

The decision uses `A`–`Z` as candidate targets. Before scoring, each target must tokenize to one distinct token ID; multi-token targets, duplicate token IDs, or missing server probability fields fail the execution. Native probabilities are a softmax over candidate logits. Runtime probabilities come from constrained completion, then are renormalized over the requested candidates; they are not raw logits or calibrated confidence estimates. Decision inputs are text-only.

## Supported files and handlers

The main model must be a single-file GGUF supported by the installed llama.cpp build. Safetensors/Transformers directories, PyTorch checkpoints, ONNX files, and Ollama model names are not accepted.

Any request containing IMAGE, AUDIO, or VIDEO requires a matching `mmproj` GGUF. Matching means the projector was produced for that exact model family and supports the requested modality; a `.gguf` extension alone does not establish compatibility.

| Handler | Intended behavior |
| --- | --- |
| `auto` | Uses model metadata and the fork's generic MTMD path. This is the normal starting point. |
| `generic` | Explicitly creates the generic MTMD chat handler. |
| `gemma4` | Applies the fork's Gemma 4-specific handler and `enable_thinking`. |
| `qwen3_vl` | Applies the Qwen 3 VL handler and `force_reasoning`. |
| `qwen25_vl` | Applies the Qwen 2.5 VL handler. |
| `qwen3_asr` | Applies the Qwen 3 ASR handler supplied by compatible fork builds. |
| `qwen35` | Applies the Qwen 3.5 handler. |

`thinking` is an explicit Boolean request. It does not infer a model default and cannot turn an Instruct-only checkpoint into a Thinking checkpoint. The generic path supplies both known template arguments so the model template can use the one it recognizes.

## One-execution list semantics

Generate declares ComfyUI V3 `is_input_list=True`. IMAGE batches, ComfyUI data lists, nested lists, AUDIO batches/lists, and VIDEO lists are flattened deterministically. They become one multimodal user message followed by one `create_chat_completion` call:

```text
system + prompt + IMAGE items + AUDIO items + VIDEO items -> one completion
```

Media group order is always IMAGE, then AUDIO, then VIDEO. Order inside each group is preserved. For Generate, a list becomes one multimodal request; Sequential Generate instead creates one independent request per IMAGE, AUDIO, or VIDEO item. Scalar fields such as model, handler, system, and runtime settings resolve to one value. Sequential prompts accept one shared value or one value per execution item.

## Media transport

| Input | Native message representation | Notes |
| --- | --- | --- |
| IMAGE | Independent lossless PNG data URI in an `image_url` part | No resize, crop, montage, or padding is performed. |
| AUDIO | Lossless PCM16 WAV data URI in an `input_audio` part | Requires an audio-capable model/projector/template. |
| VIDEO | Original encoded ComfyUI stream in an internal `video` part | Native `libmtmd` decoding requires `MTMD_VIDEO` in the wheel build. `video_with_audio` optionally extracts the first embedded audio track with PyAV and adds it as an `input_audio` part. |

Generate (Session) and the compact Generate nodes expose `video_with_audio` (default `false`). When enabled, PyAV (`av>=16.0.0`) decodes the first embedded audio track, which is converted to mono 16 kHz PCM16 WAV through the existing AUDIO normalization path. In either sequential node, the extracted audio is paired with its VIDEO item in the same request; explicitly connected AUDIO items remain separate execution items.

## Generate inputs

The detailed Generate node and its Sampling, Gemma 4 Runtime, and N-gram Preset helpers
remain registered for saved-workflow compatibility under `llama_cpp / legacy`.
They are marked V3 development-only, so normal ComfyUI sessions hide them from search
and the add-node menu. Enable developer mode only when the detailed interface is needed.

The principal inputs are:

| Input | Default | Purpose |
| --- | ---: | --- |
| `model_path` | first discovered GGUF | Main model. |
| `mmproj_path` | `[none]` | Matching multimodal projector; required when media are connected. |
| `handler` | `auto` | Chat-handler and template behavior. |
| `thinking` | `false` | Explicitly requests supported thinking/reasoning mode. |
| `reasoning_strength` | `auto` | Advanced reasoning effort hint. `auto` omits the hint and lets the model template decide; ignored when thinking is disabled. |
| `reasoning_budget` | `0` | Maximum reasoning tokens for recognized Qwen/Gemma formats. `0` means no budget; ignored when thinking is disabled. |
| `system` | empty | System-role message, passed without rewriting. |
| `prompt` | empty | User text, passed without rewriting. |
| `n_ctx` | `8192` | Total context window, including media and generated tokens. |
| `max_tokens` | `512` | Maximum generated tokens. |
| `seed` | `-1` | `-1` keeps llama.cpp random-seed behavior. |
| `ngram_speculative` | disconnected | Optional typed N-gram Speculative Preset for the normal Generate node only. |

Advanced inputs retain manual control when no preset is connected:

| Input | Default | Notes |
| --- | ---: | --- |
| `gpu_layers` | `all` | `all`, `auto`, or CPU-only offload. |
| `temperature` | `0.2` | Overridden by a connected Sampling Preset. |
| `top_p` | `0.95` | Overridden by a connected Sampling Preset. |
| `top_k` | `40` | Overridden by a connected Sampling Preset. |
| `min_p` | `0.05` | Overridden by a connected Sampling Preset. |
| `repeat_penalty` | `1.0` | Overridden by a connected Sampling Preset. |
| `stop` | empty | Optional single stop string. |
| `n_batch` | `512` | Logical prompt batch size. |
| `override_n_ubatch` | `false` | When disabled, the adjacent value is not passed. |
| `n_ubatch` | `512` | Physical batch size when its override is enabled. |
| `override_image_min_tokens` | `false` | When disabled, the projector/backend default remains authoritative. |
| `image_min_tokens` | `1024` | Per-image or per-video-frame floor when enabled; useful for Qwen-VL grounding accuracy. |
| `override_image_max_tokens` | `false` | When disabled, the projector/backend default remains authoritative. |
| `image_max_tokens` | `1120` | Per-image or per-video-frame ceiling when enabled. |
| `main_gpu` | `0` | Main GPU index. |
| `n_threads` | `0` | `0` lets llama-cpp-python choose. |
| `flash_attention` | `auto` | `auto`, enabled, or disabled. |

`reasoning_budget` uses llama.cpp's native reasoning budget arguments. Positive values
are applied only when the GGUF chat template exposes Qwen `<think>...</think>` tags or
Gemma channel tags; an unsupported template produces a clear error instead of silently
ignoring the limit. Reasoning tokens share the `max_tokens` output allowance, so increase
`max_tokens` when enabling a substantial budget.
| `use_mmap` | `true` | Memory-maps the GGUF while the model is loaded. |
| `verbose` | `false` | Controls model, timing, and handler diagnostics from both model and handler construction. |

If an image token floor or ceiling is explicitly overridden for an IMAGE or VIDEO request, the effective limit cannot exceed `n_ctx`, `n_batch`, or the effective `n_ubatch`. When both are set, `image_min_tokens` cannot exceed `image_max_tokens`. Invalid combinations fail before loading the model rather than reaching a native assertion.

## Profile nodes

`[llama.cpp] Model Profile`, `[llama.cpp] Hardware Runtime Profile`,
`[llama.cpp] Thinking / Reasoning Profile`, and `[llama.cpp] Native Speculative Profile`
live under `llama_cpp / profile` and provide typed inputs to Compact Generate.

## Compact nodes

The nodes under `llama_cpp / compact` keep model selection, request budgets,
prompts, seed, media, and diagnostics visible while moving stable model and hardware
tuning behind separate typed connections:

```text
[llama.cpp] Model Profile -------------------------+-> [llama.cpp] Generate
[llama.cpp] Hardware Runtime Profile (optional) ---/
[llama.cpp] Thinking / Reasoning Profile ---------/
[llama.cpp] N-gram Speculative Config -----------\
[llama.cpp] Native Speculative Profile ----------+-> speculative (choose one)
```

N-gram Speculative Config, Generate, and Sequential Generate live under
`llama_cpp / compact`. Sequential Generate
receives the complete input list in one call, loads the model once, calls `Llama.reset()`
before every independent completion on native-speculative forks, and otherwise clears the
underlying context memory before setting `n_tokens=0`. It retains results as data lists and
unloads once after the sequence. Speculative configs are rejected on this node because
their decoder history cannot yet be guaranteed independent. Native Speculative Profile
providers still require experimental backend support.

Its `prompt` input is also a list: with media, it must contain either one shared prompt
or exactly one prompt per execution item; any other length is rejected. Sequential execution
is modality-major (`images[]`, then `audio[]`, then `video[]`), with one media item per
request. The `response` output preserves that flat execution order. `response_seq`
provides a typed list of `{ request_index, kind, modality_index, response }` records
using the `LLAMA_SEQUENTIAL_RESPONSE` type; `kind` is `image`, `audio`, `video`, or
`text`, and `modality_index` is zero-based within that kind.
Without media, multiple prompts run as independent text-only items.

Model Profile choices come from the `name` field in `presets/model/*.json`; the built-in choices
are `General`, `Gemma 4 Vision`, `Muse Glimmer`, `Qwen 3.5+ Thinking`, `Qwen 3.5+ Non-thinking`,
and `Qwen 3 VL`. Add a JSON object there with `name`, `handler`,
`recommended_reasoning_mode`, and the sampling fields from `temperature` through
`presence_penalty`, then restart ComfyUI. Selecting `Custom` enables the Advanced handler and
six sampling inputs; switching back to a named profile preserves those custom widget values
without applying them. The built-in values are:

| Profile | temperature | top_p | top_k | min_p | presence_penalty | repeat_penalty | reasoning mode |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| General | 0.2 | 0.95 | 40 | 0.05 | 0.0 | 1.0 | model default |
| Gemma 4 Vision | 1.0 | 0.95 | 64 | 0.0 | 0.0 | 1.0 | model default |
| Muse Glimmer | 1.0 | 0.95 | 64 | 0.0 | 0.0 | 1.0 | model default |
| Qwen 3.5+ Thinking | 1.0 | 0.95 | 20 | 0.0 | 0.0 | 1.0 | on |
| Qwen 3.5+ Non-thinking | 0.7 | 0.8 | 20 | 0.0 | 1.5 | 1.0 | off |
| Qwen 3 VL | 0.7 | 0.8 | 20 | 0.0 | 1.5 | 1.0 | model default |

The Qwen 3 VL card does not prescribe `min_p`; its profile uses `0.0` so no additional
minimum-probability filter is imposed. `presence_penalty` is forwarded directly to
the targeted JamePeng llama-cpp-python fork as its API spelling `present_penalty`.
Hardware Runtime Profile is
optional: a disconnected Compact Generate uses Automatic Offload (`n_batch=512`, automatic GPU
layer selection, main GPU 0, automatic CPU threads and flash attention, mmap enabled, and no explicit
`n_ubatch` override). Connect it to override `n_batch`, `n_ubatch`, GPU offload, main GPU,
CPU threads, flash attention, or mmap settings. Its `n_ubatch=0` means that no explicit
override is sent to llama.cpp.

Thinking / Reasoning Profile has exactly `reasoning_mode`, `reasoning_effort`, and
`max_reasoning_tokens`. `auto` or a disconnected socket leaves chat-template reasoning
controls untouched for ordinary profiles; Qwen 3.5+ Thinking/Non-thinking instead applies
the mode named by the profile. An explicitly connected opposite mode fails before model
loading. `off` explicitly disables reasoning; `on` applies effort and a positive token
budget. `max_reasoning_tokens=0` omits the separate reasoning limit, but reasoning and the
final answer still share Generate's `max_tokens` allowance.

Compact Generate keeps `n_ctx`, `max_tokens`, `image_min_tokens`, and `image_max_tokens`
visible because these are request budgets. A value of `0` for either image-token setting
leaves that mmproj/handler default untouched; a positive value enables the explicit override.
For Qwen-VL grounding tasks, set `image_min_tokens=1024`. Explicit image-token limits must
fit within `n_ctx`, `n_batch`, and the effective `n_ubatch`. Reasoning effort, context,
and output length remain user-selected even when a Qwen 3.5+ profile supplies its mode.

Native Speculative Profile choices are `Off`, `External MTP`, `Internal MTP`, `DFlash`,
`DSpark`, and `Custom`. The `draft_model` selector is enabled for External MTP,
DFlash, DSpark, and Custom, while Internal MTP uses embedded NextN layers and does
not use a draft GGUF. `draft_n_max` and `draft_p_min` are shared proposal controls; the former
is visible and the latter remains advanced. The advanced draft-engine controls are
`draft_n_gpu_layers` (`auto` or `all`) and `draft_backend_sampling`. The Compact N-gram and
Native Speculative Profile nodes intentionally
emit the same typed `speculative` output, so one Generate node dispatches either strategy and
the graph cannot connect both simultaneously. The same backend validation, dependency checks,
statistics, and cleanup paths used by the detailed nodes remain active.

Compact node IDs are new and do not replace or reorder the inputs of existing saved
workflows.

## Sampling presets

Connect `sampling` to override all five sampling widgets together. While the socket is connected, the Generate node disables those widgets but preserves their values. Disconnecting it restores editing and makes the preserved values effective again.

| Preset | temperature | top_p | top_k | min_p | repeat_penalty |
| --- | ---: | ---: | ---: | ---: | ---: |
| Image analysis | 0.2 | 0.95 | 40 | 0.05 | 1.0 |
| Gemma 4 | 1.0 | 0.95 | 64 | 0.0 | 1.0 |
| Gemma 4 Uncensored | 0.6 | 0.90 | 64 | 0.05 | 1.1 |
| llama.cpp default | 0.8 | 0.95 | 40 | 0.05 | 1.0 |

## Gemma 4 runtime presets

The Runtime Preset has three outputs. Connect them explicitly:

```text
Preset.runtime    -> Generate.runtime
Preset.n_ctx      -> Generate.n_ctx
Preset.max_tokens -> Generate.max_tokens
```

The typed `runtime` connection carries only `n_batch`, `override_n_ubatch`, `n_ubatch`, `override_image_max_tokens`, and `image_max_tokens`. These five Generate widgets are disabled while the socket is connected and recover their preserved values when disconnected. Context and output length remain visible as ordinary integer connections.

| Preset | n_ctx | max_tokens | n_batch | n_ubatch override/value | image tokens override/value |
| --- | ---: | ---: | ---: | --- | --- |
| Text / Audio | 16384 | 2048 | 512 | off / 512 | off / 512 |
| Vision Standard | 16384 | 1024 | 512 | on / 512 | on / 512 |
| Vision Long / Thinking | 32768 | 4096 | 512 | on / 512 | on / 512 |
| Multi-image / Video | 32768 | 2048 | 512 | on / 512 | on / 512 |
| High Detail / OCR (Experimental) | 32768 | 2048 | 1120 | on / 1120 | on / 1120 |

These profiles are named for Gemma 4 because the image-token and physical-batch values target its dynamic-resolution vision path. They are starting points rather than universal requirements. The `Vision Long / Thinking` preset reserves generation room but does not enable the separate `thinking` Boolean.

## N-gram speculative preset

Connect **Llama.cpp N-gram Speculative Preset** to the normal Generate node's optional `ngram_speculative` input. The Preset and input are registered under `llama_cpp`; the Experimental native DFlash/DSpark node does not expose or consume this type.

`off` preserves the normal target-only path: no speculative module is imported and the `Llama` constructor receives exactly the same arguments as before. The detail widgets are disabled in this mode without resetting their values, so switching back to `ngram` restores the previous configuration. `ngram` uses JamePeng's official stateful `SpecConfig` path with `SpeculativeType.NGRAM_MAP_K` or `NGRAM_MAP_K4V`, passed to `Llama(speculative=...)`. It does not use the deprecated `Llama(draft_model=...)` callback or construct `LlamaNGramMapDecoding` directly. N-gram predicts candidates from repeated patterns already present in the verified prompt and generated history, requires no additional GGUF, and uses little additional VRAM. The stateful native speculative path is currently text-only, and the target model still verifies every proposed token, so this is not a reduced-accuracy generation mode.

| Preset input | Default | Allowed values | Constructor argument |
| --- | ---: | --- | --- |
| `speculative_mode` | `off` | `off`, `ngram` | Enables or bypasses construction |
| `ngram_size` | `3` | 1–8 | `ngram_size` |
| `num_pred_tokens` | `10` | 1–32 | `num_pred_tokens` |
| `ngram_mode` | `k` | `k`, `k4v` | `mode` |
| `ngram_min_hits` | `2` | 1–16 | `min_hits` |
| `ngram_max_entries_per_key` | `8` | 0–1024 | `max_entries_per_key`; 0 becomes `None` |

`k` stores historical positions and normally uses less memory. `k4v` caches continuation values for cheaper lookup and should generally keep a finite entries-per-key cap. The installed package's public `SpecConfig` and `SpeculativeType` are imported only when `ngram` is selected; if they are unavailable or do not support the N-gram fields, that Generate Job fails with an upgrade-or-disable message while node registration and `off` workflows remain available. `ngram_size` maps to `SpecConfig.ngram_size_n`, `num_pred_tokens` maps to `ngram_size_m`, and `ngram_mode` selects the public `NGRAM_MAP_K`/`NGRAM_MAP_K4V` enum.

`metrics_json` retains the existing load/generation/cleanup timings and records the effective configuration and public `Llama.last_speculative_stats` under `ngram_speculative`; it does not inspect private engine fields. Speedup depends on repeated context and accepted proposals, and may be negligible for short or non-repetitive responses.

## Outputs and diagnostics

Generate returns `response`, extracted `thinking`, payload-free `raw_json`, `metrics_json`, and a typed `media_diagnostics` receipt. `metrics_json` contains load, generation, and cleanup timings, token usage when supplied by the backend, the effective runtime overrides, and `model_unloaded: true` after successful cleanup.

Connect the typed receipt to **Llama.cpp Media Diagnostics** to obtain:

- `All Media Evaluated`;
- Vision, Audio, and Video availability flags;
- evaluated IMAGE, AUDIO, and VIDEO counts;
- full JSON and compact formatted text.

A successful `mtmd_evaluated` receipt confirms capability checks, decoding, marker/chunk validation, and native MTMD evaluation for every requested item. It does not prove semantic understanding or answer quality.

## Native speculative decoding (Experimental)

`[llama.cpp] Native Speculative Profile` is registered under `llama_cpp / profile` and connects to Compact Generate. The detailed `[llama.cpp] Speculative Generate (Experimental)` implementation remains in the source tree and test suite but is intentionally omitted from extension registration.

This node remains completely separate from the normal node's typed N-gram Preset: it has no `ngram_speculative` input and uses the official `SpecConfig`/`SpeculativeType` API. DFlash, DSpark, and external MTP require a separate draft GGUF. Internal MTP instead uses NextN layers embedded in the target and ignores the draft selector. A direct backend call that attempts to enable N-gram and any native provider together is rejected before either decoder is created.

The node requires a fork wheel that provides `llama_cpp.llama_speculative.SpecConfig` and `SpeculativeType`, plus the corresponding native engines. The dependency is checked at the beginning of Speculative node execution. If it is missing or cannot load its native DLLs, that Job fails with an installation error before media normalization, GGUF validation, or model loading; node registration, ComfyUI startup, and non-speculative workflows do not import the experimental module. New code must pass `speculative=SpecConfig(...)` to `Llama`; the deprecated `draft_model=` callback path is not used. Any wheel must match ComfyUI's exact Python, platform, CUDA runtime, and bundled native DLLs.

Choose `preset=Off` for target-only generation; all Native Speculative Profile fields are disabled and the output is an off config. For External MTP, DFlash, or DSpark, choose a compatible GGUF in `draft_model`. Internal MTP uses no separate draft GGUF. `Custom` exposes `custom_spec_type` and `custom_mtp_provider`; the latter is enabled only for Custom. `draft_n_max` and `draft_p_min` are accepted for every non-Off preset. The target and draft pair is not validated by filename and an incompatible pair fails explicitly during initialization or generation.

For Native MTP, choose one explicit `mtp_provider`:

| Provider | Target | `draft_model` | Native decoder path |
| --- | --- | --- | --- |
| `off` | Existing DFlash/DSpark behavior | Required | Selected draft GGUF |
| `external` | Target GGUF | Selected draft GGUF required | Selected draft GGUF |
| `internal` | Target GGUF containing embedded NextN/MTP layers | Must be unselected | `None` |

Select `spec_type=draft-mtp` together with an external or internal MTP provider. MTP uses the same `draft_n_max` and `draft_p_min` values as DFlash/DSpark. Native MTP diagnostics automatically follow the node's existing `verbose` switch; there is no separate MTP verbose input. `draft-mtp` with `mtp_provider=off` is rejected before model loading. Provider choice is never inferred from filenames, and an explicitly selected provider never silently falls back to target-only generation. The native bridge remains responsible for architecture, hidden-width, vocabulary, assistant, and embedded-layer compatibility checks.

All current stateful native speculative engines are text-only and single-sequence. Native MTP additionally requires `gpu_layers=all`; IMAGE, AUDIO, VIDEO, context shifting, grammar/JSON-schema constraints, custom logits processors, prefix/state-cache reuse, and multi-sequence batching are unsupported.

The backend builds a `SpecConfig` before target-model construction and passes it as `Llama(speculative=...)`. `Llama` then creates and owns the stateful N-gram/MTP/DFlash/DSpark engine and any external draft resources; `Llama.close()` releases them. Draft statistics are copied from the public `llm.last_speculative_stats` property before cleanup and exposed under the corresponding speculative metrics. The backend does not inspect native engine internals or non-public engine metadata, create/close an engine directly, or use the deprecated `draft_model=` callback:

```json
{
  "enabled": true,
  "implementation": "draft-dflash",
  "draft_model": "dflash-kquant.gguf",
  "n_max": 8,
  "n_min": 0,
  "p_min": 0.0,
  "stats": {
    "draft_calls": 70,
    "drafted_tokens": 1050,
    "accepted_tokens": 89,
    "acceptance_rate": 0.085,
    "mean_accepted_tokens": 1.27
  }
}
```

Zero or missing draft activity produces a ComfyUI console warning. Context shifting, multimodal generation, multi-sequence generation, grammar/JSON-schema constraints, custom logits processors, and Python state-cache restoration are outside this node's supported scope. Target plus draft weights can consume substantial additional VRAM, and speculative decoding may be slower than target-only generation.

MTP metrics use the same object and add `mtp_provider`, `n_layer_nextn`, `completion_tokens`, `tokens_per_second`, and `finish_reason`. Its `stats` values come from the request-local `Llama.last_speculative_stats` snapshot. For a normal-length smoke test, `draft_calls` and `drafted_tokens` should be greater than zero; a very short completion can finish before the first draft cycle.

## Model lifetime and concurrency

Native executions are serialized within the ComfyUI process. Each execution follows this lifecycle:

```text
normalize -> load model/projector -> one completion -> close -> garbage collection
```

Cleanup is in `finally`, so generation errors still close any constructed model or handler. The node does not expose a model output and does not maintain a cache. The operating system may retain file-system pages used by `mmap`, and native CUDA libraries may retain a small process-level baseline, but the model context and GPU buffers owned by the node are not intentionally kept for later workflow runs.

The caller's llama.cpp surface is limited to public `Llama` methods and properties:
`create_chat_completion()`, `detokenize()`, token-id helpers, `last_speculative_stats`,
`n_layer_nextn()`, and `close()`. Handler capability flags and `close()` are also read only
through their public contract. Native engine internals and non-public metadata are not
observed. If `Llama.close()` fails, the fallback closes only the
caller-created handler and preserves the original inference
exception when one already exists.

## Troubleshooting

### Optional dependency unavailable

Confirm that the wheel was installed into the interpreter that launches ComfyUI. A successful import in another virtual environment does not make it available to ComfyUI.

### No GGUF models found

Place `.gguf` files under `ComfyUI/models/LLM` or register an `LLM` path in `extra_model_paths.yaml`, then reload node definitions or restart ComfyUI.

### Media marker mismatch

Errors containing `media marker mismatch`, `marker_count`, or `media_count` mean the selected chat template did not render exactly one MTMD marker per supplied media item. Verify the main model/projector pairing and try the appropriate handler. VIDEO must use a fork build and template that understand the internal `video` content part.

### Media is described as unavailable or ignored

Connect Media Diagnostics first. Check the handler's Vision/Audio/Video capability flags and evaluated counts. A projector that works for IMAGE does not necessarily support AUDIO or VIDEO.

### Native batch assertion or image token error

Use a Gemma 4 Runtime Preset or ensure that explicit `image_min_tokens` and `image_max_tokens` values are no larger than `n_batch` and the effective `n_ubatch`. Increase `n_ctx` when the total media tokens plus requested output exceed the context window; increasing context alone does not repair a mismatched model, projector, or template.

### VIDEO fails before generation

Confirm that the installed fork wheel was built with `MTMD_VIDEO` support and that Media Diagnostics reports Video availability. No separate FFmpeg executable is required by this node. Generate and both sequential nodes can use `video_with_audio`; in either sequential node, enable it to include each VIDEO item's embedded soundtrack in that item's request.

### Console output is unexpectedly long

Keep Generate's `verbose` input disabled. Some model-load warnings originate from native code and may still be printed even when ordinary verbose diagnostics are disabled.

## N-gram manual smoke test

Run the normal Generate node twice with identical model, prompt, `max_tokens`, seed, and sampling values. Leave the N-gram Preset at `off` for the first run and switch it to `ngram` for the second. A suitable repetition-heavy prompt is:

```text
Create Python CRUD functions for users, products, orders, and invoices.
Each section must use the same function structure and error-handling pattern.
```

Confirm that both runs return a non-empty response with a normal `finish_reason`, neither run enters a repetition loop, and both unload cleanly. Compare `metrics_json.generation_seconds` or derived tokens-per-second. Token-exact output equality is not required; the comparison is meaningful only when model, sampling, seed, and output length are otherwise held constant.
