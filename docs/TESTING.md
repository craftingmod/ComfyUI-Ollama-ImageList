# Testing

Install the locked development dependencies:

```bash
bun install --frozen-lockfile
uv sync --locked --group dev
```

Run the same validation sequence as CI:

```bash
bun run fmt:check
bun run lint
bun run typecheck
bun run test:unit
bun run build
bun run build:custom-node
```

`bun run test:frontend` runs Bun frontend tests and `bun run test:backend` runs the Python suite. Generated frontend files live in `dist/`; edit `frontend/` rather than the bundle.

The automated suite covers:

- image/audio/video normalization, list flattening, limits, PNG encoding, and PCM16 WAV encoding;
- Ollama request/response handling through a local mock HTTP server;
- llama.cpp image-only, audio-only, video-only, and mixed-media message construction;
- model-specific and generic thinking arguments, response/thinking extraction, sampling presets, and Gemma 4 runtime presets;
- `n_ubatch` and image-token override validation;
- typed MTMD diagnostics, availability flags, evaluated counts, and payload-free receipts;
- unconditional native cleanup on success and failure through test doubles;
- Sequential Generate single-load execution, native-fork `reset()` and non-native memory-clear paths, independent per-item media messages, explicit list outputs, and final unload through test doubles;
- native speculative early dependency failure, draft ordering, parameter forwarding, stats capture, target-only isolation, validation, and initialization-failure cleanup through test doubles;
- Compact Model/Hardware Profile and Native Speculative Config typing, published Gemma/Muse/Qwen sampling values, presence-penalty forwarding, Qwen 3.5 reasoning-mode consistency, Custom Model Profile forwarding, zero-sentinel override behavior, Muse DFlash defaults, unified speculative forwarding, and Compact execution through test doubles;
- normal-node N-gram Preset typing, off-path isolation, lazy API failure, parameter forwarding, 0-to-None conversion, multimodal preservation, mode separation, and cleanup through test doubles;
- native CLIP Generate Text system templates, IMAGE list flattening, model detection, and Gemma 4 named-parameter compatibility;
- V3 schemas, backend-specific node categories, extension registration, and the thin package entrypoint;
- MiniMax system-prompt preset file selection, validated enum-string override, common/reference base concatenation, and release packaging.

The suite does not install or load a real GGUF, start ComfyUI, exercise native `MTMD_VIDEO` decoding, launch a browser, or contact Ollama. Those integrations remain manual because wheel, GPU backend, model, projector, and chat-template compatibility are environment-specific.

Before publishing a llama.cpp build, manually verify in the target ComfyUI environment:

1. Model Profile, Hardware Runtime Profile, Thinking / Reasoning Config, N-gram Speculative Config, Generate, and Sequential Generate appear under `Ollama / llama_cpp / compact`; Native Speculative Config appears under `experimental`; Diagnostics and Muse Parser appear under `utils`; the four registered legacy schemas are hidden from search/menu outside developer mode; and the detailed Speculative Generate node is not registered;
2. GGUF files from the local and any `extra_model_paths.yaml` `LLM` directories appear in both Combos;
3. the selected main model and projector complete the intended IMAGE, AUDIO, and/or VIDEO request;
4. Media Diagnostics reports the requested capability and evaluated item counts;
5. `metrics_json.model_unloaded` is `true` after a successful completion;
6. Sequential Generate loads one model for a connected AUDIO list, resets context before each independent item, produces one output set per item, and unloads once after the list;
7. a second diffusion workflow can reclaim the released VRAM.

For Native Speculative Config, connect one compatible text target/draft pair to Compact Generate and verify one initial image-prefill request where supported. Confirm that `metrics_json.speculative.stats.draft_calls` and `drafted_tokens` are greater than zero, the completion stops normally, and target/draft VRAM is reclaimed after the response.

For both MTP paths, first select `spec_type=draft-mtp` and start with the shared `spec_n_max=2`, `spec_n_min=0`, and `spec_p_min=0.0`. For Gemma 4 external MTP, select `mtp_provider=external_gemma4`, a Gemma 4 target, and its matching `gemma4-assistant` GGUF in `draft_model`; use `gpu_layers=all`. For Qwen 3.5 internal MTP, select `mtp_provider=internal_qwen35`, leave `draft_model` unselected, and use a target GGUF that contains embedded NextN layers. Confirm enabling the normal `verbose` switch also enables MTP diagnostics. Run text-only prompts long enough to open draft cycles. Confirm `implementation` is `draft-mtp`, the requested `mtp_provider` is reported, `draft_calls` and `drafted_tokens` increase, Qwen reports `n_layer_nextn > 0`, and target/decoder VRAM is reclaimed. Also confirm Gemma without an assistant, Qwen with a selected assistant, Qwen without NextN layers, and any MTP request with media fail explicitly without target-only fallback.

For normal-node n-gram speculative decoding, run the same repetition-heavy prompt with Preset mode `off` and `ngram`, keeping model, sampling, seed, and `max_tokens` fixed. Confirm non-empty normal completions, no damaged repetition loop, clean unload, and compare `generation_seconds` or tokens per second. Do not require token-exact equality.

In the frontend, confirm that N-gram detail widgets are disabled at `off` and restored with their prior values at `ngram` on both N-gram configuration nodes. Confirm Model and Hardware Profile custom widgets are enabled only for `Custom`, retain their values across profile changes, and that `n_ubatch=0` reaches the backend as no override. Confirm Compact Generate accepts a disconnected Hardware Runtime input as GPU Full Offload, then applies a connected Hardware Runtime Profile instead. On Thinking / Reasoning Config, confirm effort and token-limit widgets are enabled only for `on`; verify disconnected/`auto` leaves template arguments untouched for ordinary profiles, selects `on` for Qwen 3.5 Thinking and `off` for Qwen 3.5 Non-thinking, and rejects an explicitly contradictory mode. Verify `off` sends an explicit disable and `max_reasoning_tokens=0` sends no budget. Confirm `presence_penalty` is editable in Custom and reaches the targeted fork as `present_penalty`. Confirm the node is discoverable by both `thinking` and `reasoning` searches. Confirm Compact Generate sends no image-token override at `image_max_tokens=0` and enables it for a positive value. Confirm the Compact N-gram and Native Speculative nodes can each connect to the same Compact Generate `speculative` input. On Native Speculative Config, confirm custom fields are enabled only for `Custom`, the draft selector is disabled for `Off` and Qwen internal MTP, and `mtp_provider` normalization matches the chosen provider. On the normal Generate node, connect and disconnect Sampling and Runtime presets and confirm that only their corresponding overridden widgets are disabled, with values preserved across each round trip.

Before publishing native CLIP support, also verify Qwen3-VL or Qwen3.5 with two IMAGE list items and verify Gemma 4 with both a same-resolution batch and, on a ComfyUI build containing PR #15450, two different resolutions.
