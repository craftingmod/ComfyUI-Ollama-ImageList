# Native llama.cpp backend

The nodes under `Ollama / llama_cpp` run a GGUF model directly inside the ComfyUI process through `llama-cpp-python`. They are intended for one stateless text or multimodal chat completion. No model object, context, KV cache, or projector is exposed to the workflow or retained after execution.

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

After adding files or changing `extra_model_paths.yaml`, restart ComfyUI or refresh the node definitions. A saved relative selection is resolved through ComfyUI's registered model paths again at execution time.

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

`thinking` is an explicit Boolean request. It does not infer a model default and cannot turn an Instruct-only checkpoint into a Thinking checkpoint. The generic path supplies both known template arguments so the model template can use the one it recognizes.

## One-execution list semantics

Generate declares ComfyUI V3 `is_input_list=True`. IMAGE batches, ComfyUI data lists, nested lists, AUDIO batches/lists, and VIDEO lists are flattened deterministically. They become one multimodal user message followed by one `create_chat_completion` call:

```text
system + prompt + IMAGE items + AUDIO items + VIDEO items -> one completion
```

Media group order is always IMAGE, then AUDIO, then VIDEO. Order inside each group is preserved. A list does not cause one completion per item, and scalar fields such as model, handler, system, prompt, and runtime settings must resolve to one value.

## Media transport

| Input | Native message representation | Notes |
| --- | --- | --- |
| IMAGE | Independent lossless PNG data URI in an `image_url` part | No resize, crop, montage, or padding is performed. |
| AUDIO | Lossless PCM16 WAV data URI in an `input_audio` part | Requires an audio-capable model/projector/template. |
| VIDEO | Original encoded ComfyUI stream in an internal `video` part | Native `libmtmd` decoding requires `MTMD_VIDEO` in the wheel build. Embedded audio is not ingested. |

Connect AUDIO separately when a video's soundtrack is required. The code deliberately uses the fork's internal `video` representation instead of a `video_url` widget because model templates such as Gemma 4 may not render `video_url` into an MTMD media marker.

## Generate inputs

The principal inputs are:

| Input | Default | Purpose |
| --- | ---: | --- |
| `model_path` | first discovered GGUF | Main model. |
| `mmproj_path` | `[none]` | Matching multimodal projector; required when media are connected. |
| `handler` | `auto` | Chat-handler and template behavior. |
| `thinking` | `false` | Explicitly requests supported thinking/reasoning mode. |
| `system` | empty | System-role message, passed without rewriting. |
| `prompt` | empty | User text, passed without rewriting. |
| `n_ctx` | `8192` | Total context window, including media and generated tokens. |
| `max_tokens` | `512` | Maximum generated tokens. |
| `seed` | `-1` | `-1` keeps llama.cpp random-seed behavior. |

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
| `override_image_max_tokens` | `false` | When disabled, the projector/backend default remains authoritative. |
| `image_max_tokens` | `1120` | Per-image or per-video-frame ceiling when enabled. |
| `main_gpu` | `0` | Main GPU index. |
| `n_threads` | `0` | `0` lets llama-cpp-python choose. |
| `flash_attention` | `auto` | `auto`, enabled, or disabled. |
| `use_mmap` | `true` | Memory-maps the GGUF while the model is loaded. |
| `verbose` | `false` | Controls model, timing, and handler diagnostics from both model and handler construction. |

If `image_max_tokens` is explicitly overridden for an IMAGE or VIDEO request, it cannot exceed `n_ctx`, `n_batch`, or the effective `n_ubatch`. Invalid combinations fail before loading the model rather than reaching a native assertion.

## Sampling presets

Connect `sampling` to override all five sampling widgets together.

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

The typed `runtime` connection carries only `n_batch`, `override_n_ubatch`, `n_ubatch`, `override_image_max_tokens`, and `image_max_tokens`. Context and output length remain visible as ordinary integer connections.

| Preset | n_ctx | max_tokens | n_batch | n_ubatch override/value | image tokens override/value |
| --- | ---: | ---: | ---: | --- | --- |
| Text / Audio | 16384 | 2048 | 512 | off / 512 | off / 512 |
| Vision Standard | 16384 | 1024 | 512 | on / 512 | on / 512 |
| Vision Long / Thinking | 32768 | 4096 | 512 | on / 512 | on / 512 |
| Multi-image / Video | 32768 | 2048 | 512 | on / 512 | on / 512 |
| High Detail / OCR (Experimental) | 32768 | 2048 | 1120 | on / 1120 | on / 1120 |

These profiles are named for Gemma 4 because the image-token and physical-batch values target its dynamic-resolution vision path. They are starting points rather than universal requirements. The `Vision Long / Thinking` preset reserves generation room but does not enable the separate `thinking` Boolean.

## Outputs and diagnostics

Generate returns `response`, extracted `thinking`, payload-free `raw_json`, `metrics_json`, and a typed `media_diagnostics` receipt. `metrics_json` contains load, generation, and cleanup timings, token usage when supplied by the backend, the effective runtime overrides, and `model_unloaded: true` after successful cleanup.

Connect the typed receipt to **Llama.cpp Media Diagnostics** to obtain:

- `All Media Evaluated`;
- Vision, Audio, and Video availability flags;
- evaluated IMAGE, AUDIO, and VIDEO counts;
- full JSON and compact formatted text.

A successful `mtmd_evaluated` receipt confirms capability checks, decoding, marker/chunk validation, and native MTMD evaluation for every requested item. It does not prove semantic understanding or answer quality.

## Model lifetime and concurrency

Native executions are serialized within the ComfyUI process. Each execution follows this lifecycle:

```text
normalize -> load model/projector -> one completion -> close -> garbage collection
```

Cleanup is in `finally`, so generation errors still close any constructed model or handler. The node does not expose a model output and does not maintain a cache. The operating system may retain file-system pages used by `mmap`, and native CUDA libraries may retain a small process-level baseline, but the model context and GPU buffers owned by the node are not intentionally kept for later workflow runs.

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

Use a Gemma 4 Runtime Preset or ensure that an explicit `image_max_tokens` value is no larger than `n_batch` and the effective `n_ubatch`. Increase `n_ctx` when the total media tokens plus requested output exceed the context window; increasing context alone does not repair a mismatched model, projector, or template.

### VIDEO fails before generation

Confirm that the installed fork wheel was built with `MTMD_VIDEO` support and that Media Diagnostics reports Video availability. No separate FFmpeg executable is required by this node. Connect AUDIO separately for the soundtrack.

### Console output is unexpectedly long

Keep Generate's `verbose` input disabled. Some model-load warnings originate from native code and may still be printed even when ordinary verbose diagnostics are disabled.
