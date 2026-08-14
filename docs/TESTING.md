# Testing

Install the locked development dependencies and run the Python suite:

```bash
uv sync --locked --group dev
uv run pytest
```

The Reference Director frontend requires Bun 1.3.14 or newer. Install the locked frontend dependencies, then run strict TypeScript checks, DOM/state/API unit tests, and the Vite 8 production build:

```bash
bun install --frozen-lockfile
bun run check:frontend
```

For focused iterations, use `bun run typecheck`, `bun run test:frontend`, `bun run build`, or `bun run dev`. The last command type-checks once and rebuilds `web/index.js` in watch mode. Runtime users do not need Bun because the compiled bundle is included in the package.

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
- Reference Director versioned state validation, independent image/video/audio ordering, category-specific toggle and caption semantics, video-derived audio IDs, execution fingerprints that exclude UI-only preferences, payload-free manifests, and output-list alignment;
- Reference Director managed-path containment, symlink/reparse-point rejection, original-name sanitization/collision handling, content hash/size checks, lazy image/audio/video media loading, upload/metadata/image-preview/rembg-preview/audio-preview/waveform/edit routes, rembg cache reuse, mask materialization, shortened proxy cache keys, cache validation, and stale edit revisions;
- Reference Director frontend reducer/history/serialization behavior, immutable original-source restoration, strict current-schema validation, API request mapping, custom-widget restoration/cleanup, batched restoration hydration, write-only native advanced-field proxy synchronization, property-backed caption visibility, channel rendering and caption-footer controls, media-only Edit double-click routing with control exclusions, common media filename gradients, media-only disabled-output desaturation with full-brightness surrounding information and controls, mutually exclusive sound-enabled VIDEO and audio-only preview lifecycles, View/Crop/Mask interaction gating, fixed crop viewports, image-pan dragging, mode-specific wheel behavior, `1×` minimum zoom, zoom-dependent whole-Stage coverage bounds, source-pixel integer crop controls, four-corner resizing, pre-Apply rembg preview gating, dual-ended trim controls and draft playback, detail-editor captions and filenames, bounded mask-brush history, native drag arming, and destination-card highlighting under a browser-like test environment.

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

## Reference Director manual smoke

The automated frontend suite uses a simulated DOM and the Python suite uses decoder/test doubles where appropriate. Before publishing Reference Director, run the following in a real target ComfyUI installation:

1. Add **Reference Director** from `Ollama / Multimodal`; verify the custom board renders, resizes with the node, and reports no browser-console errors.
2. Add two differently sized images, one audio file, one video with audio, and one silent video. Confirm progress state, image/video previews, Audio-channel waveforms, and metadata; confirm the silent video's **A** output is disabled automatically.
3. Enter unique captions, including a separate Audio caption for one video. Confirm every media preview shows the source filename in a compact bottom gradient with ellipsis and a full-name tooltip, and detail editors also show it. Toggle `show_captions` off under **Show advanced inputs**, confirm the card fields collapse without losing text, and edit a caption through **Edit** before showing the fields again. Reorder Images, Videos, and Audio independently with drag/drop and the arrow controls, then toggle one card off in each channel.
4. Use board undo/redo. Open the image editor; confirm Crop is selected, exercise its source-pixel integer controls and corner handles, switch to Mask Drawing, then test viewport pan/zoom, Erase/Restore with different brush sizes/opacities, horizontal/vertical flip, transparent/solid background, bounded local undo/redo, Cancel, and Apply. Confirm Apply stores a content-addressed mask and creates a new content-addressed PNG/revision without changing the original source. Reopen Edit, choose **Restore original**, and confirm the original source returns without changing caption, enable state, or board order, including after save/reload.
5. Use Grid play/stop on Audio cards, then open Edit and adjust both trim handles while checking the draft range with Play/Pause/Stop. Trim the audio and video to known second ranges, cancel once, then apply. Confirm the native AUDIO waveform/sample count and VIDEO duration match the selected ranges.
6. Queue the node. Verify `images`/`image_captions`, `audios`/`audio_captions`, and `videos`/`video_captions` have equal lengths and identical per-channel order. Verify the video-derived manifest ID is `<video-id>:audio`.
7. Confirm VIDEO retains its embedded audio while the enabled video Audio channel emits a separate decoded AUDIO value. Ensure the intended downstream workflow does not play both unintentionally.
8. Inspect `manifest_json`: disabled cards remain in `items`; active IDs match the three output lists; captions are marked `source: user`; no base64 media or absolute server path is present.
9. Save and reload the workflow. Confirm cards, independent orders, captions, toggles, edit/trim state, and display settings are restored, then execute again.
10. Disable every card in one channel and verify an empty list is produced. Test the actual downstream consumer because some third-party nodes assume a non-empty list.
11. Apply a transparent edit and confirm the IMAGE has four RGBA channels. Repeat with a solid background when testing an RGB-only downstream node.
12. Replace a managed source on disk and confirm execution rejects the size/hash mismatch. Restore or re-add the file rather than bypassing identity validation.

The longer operational checklist, storage layout, and compatibility notes are in [`REFERENCE_DIRECTOR.md`](REFERENCE_DIRECTOR.md).
