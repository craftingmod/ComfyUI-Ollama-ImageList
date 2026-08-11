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

The experimental Speculative Generate node adds a `draft_model` Combo from the same inventory directly below `mmproj_path`. It stably prioritizes filenames containing `dflash`, `dspark`, `draft`, or `mtp`, but does not infer target compatibility from a filename.

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

If `image_max_tokens` is explicitly overridden for an IMAGE or VIDEO request, it cannot exceed `n_ctx`, `n_batch`, or the effective `n_ubatch`. Invalid combinations fail before loading the model rather than reaching a native assertion.

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

Connect **Llama.cpp N-gram Speculative Preset** to the normal Generate node's optional `ngram_speculative` input. The Preset and input are registered under `Ollama / llama_cpp`; the Experimental native DFlash/DSpark node does not expose or consume this type.

`off` preserves the normal target-only path: no draft object is constructed, no speculative module is imported, and the `Llama` constructor receives exactly the same arguments as before. The detail widgets are disabled in this mode without resetting their values, so switching back to `ngram` restores the previous configuration. `ngram` lazily imports `LlamaNGramMapDecoding` and passes one request-local instance as `Llama(draft_model=...)`. It predicts candidates from repeated patterns already present in the verified prompt and generated history, requires no additional GGUF, and uses little additional VRAM. The target model still verifies every proposed token, so this is not a reduced-accuracy generation mode.

| Preset input | Default | Allowed values | Constructor argument |
| --- | ---: | --- | --- |
| `speculative_mode` | `off` | `off`, `ngram` | Enables or bypasses construction |
| `ngram_size` | `3` | 1–8 | `ngram_size` |
| `num_pred_tokens` | `10` | 1–32 | `num_pred_tokens` |
| `ngram_mode` | `k` | `k`, `k4v` | `mode` |
| `ngram_min_hits` | `2` | 1–16 | `min_hits` |
| `ngram_max_entries_per_key` | `8` | 0–1024 | `max_entries_per_key`; 0 becomes `None` |
| `ngram_sync_check_tokens` | `16` | 1–256 | `sync_check_tokens` |

`k` stores historical positions and normally uses less memory. `k4v` caches continuation values for cheaper lookup and should generally keep a finite entries-per-key cap. The installed package is imported only when `ngram` is selected; if the class is unavailable, that Generate Job fails with an upgrade-or-disable message while node registration and `off` workflows remain available. The constructor signature is based on the current [JamePeng `LlamaNGramMapDecoding` source](https://github.com/JamePeng/llama-cpp-python/blob/main/llama_cpp/llama_speculative.py).

No stable acceptance statistics are assumed for this Python draft class. `metrics_json` retains the existing load/generation/cleanup timings and records the effective configuration under `ngram_speculative`; it does not inspect private draft fields. Speedup depends on repeated context and accepted proposals, and may be negligible for short or non-repetitive responses.

## Outputs and diagnostics

Generate returns `response`, extracted `thinking`, payload-free `raw_json`, `metrics_json`, and a typed `media_diagnostics` receipt. `metrics_json` contains load, generation, and cleanup timings, token usage when supplied by the backend, the effective runtime overrides, and `model_unloaded: true` after successful cleanup.

Connect the typed receipt to **Llama.cpp Media Diagnostics** to obtain:

- `All Media Evaluated`;
- Vision, Audio, and Video availability flags;
- evaluated IMAGE, AUDIO, and VIDEO counts;
- full JSON and compact formatted text.

A successful `mtmd_evaluated` receipt confirms capability checks, decoding, marker/chunk validation, and native MTMD evaluation for every requested item. It does not prove semantic understanding or answer quality.

## Native speculative decoding (Experimental)

`Llama.cpp Speculative Generate (Experimental)` is registered under `Ollama / llama_cpp / experimental`. It mirrors the normal Generate schema and outputs, so the existing Sampling Preset, Gemma 4 Runtime Preset, and Media Diagnostics nodes connect without experimental variants.

This node remains completely separate from the normal node's typed N-gram Preset: it has no `ngram_speculative` input and uses only `LlamaNativeSpeculativeDecoding`. DFlash, DSpark, and Gemma 4 external MTP require a separate draft/assistant GGUF. Qwen 3.5 internal MTP instead uses NextN layers embedded in the target and requires `draft_model` to remain unselected. A direct backend call that attempts to enable N-gram and any native provider together is rejected before either decoder is created.

The node requires an experimental wheel that provides `llama_cpp.llama_speculative.LlamaNativeSpeculativeDecoding`. The dependency is checked at the beginning of Speculative node execution. If it is missing or cannot load its native DLLs, that Job fails with an installation error before media normalization, GGUF validation, or model loading; node registration, ComfyUI startup, and non-speculative workflows do not import the experimental module. Installation details for the existing DFlash/DSpark build are in the [v0.3.46 native speculative release](https://github.com/craftingmod/llama-cpp-python/releases/tag/v0.3.46-native-speculative.1). Native MTP additionally requires a wheel freshly built from the experimental fork with `draft-mtp`, external/internal MTP bridging, and speculative ABI v2; the older DFlash/DSpark wheel is not sufficient. Any wheel must match ComfyUI's exact Python, platform, CUDA runtime, and bundled native DLLs.

Choose `spec_type=none` for target-only generation; the three `spec_n_*` widgets are disabled in this mode and no native speculative dependency is imported. The `draft_model` selector uses `[none]` when no file is needed. For DFlash or DSpark, choose a compatible GGUF in `draft_model`, then select `draft-dflash` or `draft-dspark`. The shared defaults are `spec_n_max=2`, `spec_n_min=0`, and `spec_p_min=0.0`. The target and draft pair is not validated by filename and an incompatible pair fails explicitly during initialization or generation.

For Native MTP, choose one explicit `mtp_provider`:

| Provider | Target | `draft_model` | Native decoder path |
| --- | --- | --- | --- |
| `off` | Existing DFlash/DSpark behavior | Required | Selected draft GGUF |
| `external_gemma4` | Gemma 4 target GGUF | Matching `gemma4-assistant` GGUF required | Selected assistant GGUF |
| `internal_qwen35` | Qwen 3.5 GGUF containing embedded NextN/MTP layers | Must be unselected | `None` |

Select `spec_type=draft-mtp` together with an external or internal MTP provider. The `mtp_provider` widget is disabled for every other `spec_type`, and any preserved inactive value is treated as `off` during node execution. MTP uses the same `spec_n_max`, `spec_n_min`, and `spec_p_min` values as DFlash/DSpark. Native MTP diagnostics automatically follow the node's existing `verbose` switch; there is no separate MTP verbose input. `draft-mtp` with `mtp_provider=off` is rejected before model loading. Provider choice is never inferred from filenames, and an explicitly selected provider never silently falls back to target-only generation. The native bridge remains responsible for architecture, hidden-width, vocabulary, assistant, and embedded-layer compatibility checks.

Native MTP currently supports one text-only request with `gpu_layers=all`. It sets `n_seq_max=1` and `native_context_reprefill=false`; IMAGE, AUDIO, VIDEO, context shifting, grammar/JSON-schema constraints, custom logits processors, prefix/state-cache reuse, and multi-sequence batching are unsupported. These restrictions apply only to MTP: existing DFlash/DSpark initial multimodal prefill remains available.

Draft construction occurs before target-model construction. After successful target construction, `Llama.close()` owns cleanup of the attached draft resource. If target construction fails before ownership transfer, the node closes the draft directly. Draft statistics are copied before cleanup and exposed under `metrics_json.speculative`:

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

Zero or missing draft activity produces a ComfyUI console warning. Initial single-request image prefill uses the normal multimodal message path, but context shifting, multi-sequence generation, grammar/JSON-schema constraints, custom logits processors, and Python state-cache restoration are outside this node's supported scope. Target plus draft weights can consume substantial additional VRAM, and short multimodal responses may not become faster.

MTP metrics use the same object and add `mtp_provider`, `n_layer_nextn`, `completion_tokens`, `tokens_per_second`, and `finish_reason`. Its `stats` values are decoder snapshots taken immediately before and after the request, so they represent the current request rather than the decoder lifetime. For a normal-length smoke test, `draft_calls` and `drafted_tokens` should be greater than zero; a very short completion can finish before the first draft cycle.

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

## N-gram manual smoke test

Run the normal Generate node twice with identical model, prompt, `max_tokens`, seed, and sampling values. Leave the N-gram Preset at `off` for the first run and switch it to `ngram` for the second. A suitable repetition-heavy prompt is:

```text
Create Python CRUD functions for users, products, orders, and invoices.
Each section must use the same function structure and error-handling pattern.
```

Confirm that both runs return a non-empty response with a normal `finish_reason`, neither run enters a repetition loop, and both unload cleanly. Compare `metrics_json.generation_seconds` or derived tokens-per-second. Token-exact output equality is not required; the comparison is meaningful only when model, sampling, seed, and output length are otherwise held constant.
