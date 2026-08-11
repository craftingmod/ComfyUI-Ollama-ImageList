# Testing

Install the locked development dependencies and run the Python suite:

```bash
uv sync --locked --group dev
uv run pytest
```

The automated suite covers:

- image/audio/video normalization, list flattening, limits, PNG encoding, and PCM16 WAV encoding;
- Ollama request/response handling through a local mock HTTP server;
- llama.cpp image-only, audio-only, video-only, and mixed-media message construction;
- model-specific and generic thinking arguments, response/thinking extraction, sampling presets, and Gemma 4 runtime presets;
- `n_ubatch` and image-token override validation;
- typed MTMD diagnostics, availability flags, evaluated counts, and payload-free receipts;
- unconditional native cleanup on success and failure through test doubles;
- native speculative early dependency failure, draft ordering, parameter forwarding, stats capture, target-only isolation, validation, and initialization-failure cleanup through test doubles;
- normal-node N-gram Preset typing, off-path isolation, lazy API failure, parameter forwarding, 0-to-None conversion, multimodal preservation, mode separation, and cleanup through test doubles;
- native CLIP Generate Text system templates, IMAGE list flattening, model detection, and Gemma 4 named-parameter compatibility;
- V3 schemas, backend-specific node categories, extension registration, and the thin package entrypoint.

The suite does not install or load a real GGUF, start ComfyUI, exercise native `MTMD_VIDEO` decoding, launch a browser, or contact Ollama. Those integrations remain manual because wheel, GPU backend, model, projector, and chat-template compatibility are environment-specific.

Before publishing a llama.cpp build, manually verify in the target ComfyUI environment:

1. the five standard native nodes appear under `Ollama / llama_cpp`, and Speculative Generate appears under its `experimental` subcategory;
2. GGUF files from the local and any `extra_model_paths.yaml` `LLM` directories appear in both Combos;
3. the selected main model and projector complete the intended IMAGE, AUDIO, and/or VIDEO request;
4. Media Diagnostics reports the requested capability and evaluated item counts;
5. `metrics_json.model_unloaded` is `true` after a successful completion;
6. a second diffusion workflow can reclaim the released VRAM.

For the experimental speculative node, also verify one compatible text target/draft pair and one initial image-prefill request. Confirm that `metrics_json.speculative.stats.draft_calls` and `drafted_tokens` are greater than zero, the completion stops normally, and target/draft VRAM is reclaimed after the response.

For both MTP paths, first select `spec_type=draft-mtp` and start with the shared `spec_n_max=2`, `spec_n_min=0`, and `spec_p_min=0.0`. For Gemma 4 external MTP, select `mtp_provider=external_gemma4`, a Gemma 4 target, and its matching `gemma4-assistant` GGUF in `draft_model`; use `gpu_layers=all`. For Qwen 3.5 internal MTP, select `mtp_provider=internal_qwen35`, leave `draft_model` unselected, and use a target GGUF that contains embedded NextN layers. Confirm enabling the normal `verbose` switch also enables MTP diagnostics. Run text-only prompts long enough to open draft cycles. Confirm `implementation` is `draft-mtp`, the requested `mtp_provider` is reported, `draft_calls` and `drafted_tokens` increase, Qwen reports `n_layer_nextn > 0`, and target/decoder VRAM is reclaimed. Also confirm Gemma without an assistant, Qwen with a selected assistant, Qwen without NextN layers, and any MTP request with media fail explicitly without target-only fallback.

For normal-node n-gram speculative decoding, run the same repetition-heavy prompt with Preset mode `off` and `ngram`, keeping model, sampling, seed, and `max_tokens` fixed. Confirm non-empty normal completions, no damaged repetition loop, clean unload, and compare `generation_seconds` or tokens per second. Do not require token-exact equality.

In the frontend, confirm that N-gram detail widgets are disabled at `off` and restored with their prior values at `ngram`. On the experimental Speculative Generate node, confirm `spec_n_max`, `spec_n_min`, and `spec_p_min` are disabled at `spec_type=none`, re-enabled for each draft type, and preserve their values across mode changes. Confirm `mtp_provider` is enabled only for `draft-mtp` and disabled for `none`, DFlash, and DSpark. On the normal Generate node, connect and disconnect Sampling and Runtime presets and confirm that only their corresponding overridden widgets are disabled, with values preserved across each round trip.

Before publishing native CLIP support, also verify Qwen3-VL or Qwen3.5 with two IMAGE list items and verify Gemma 4 with both a same-resolution batch and, on a ComfyUI build containing PR #15450, two different resolutions.
