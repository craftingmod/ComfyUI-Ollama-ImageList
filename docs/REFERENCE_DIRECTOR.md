# Reference Director

`Reference Director` is a ComfyUI V3 node for arranging local image, audio, and video references before another node analyzes or generates from them. It owns file ingestion, independent image/video/audio ordering, raw user captions, enable state, and non-destructive edits. It does not load an LLM/VLM, rewrite captions, or assemble a generation prompt.

The node appears under `Ollama / Multimodal`. A minimal saved graph is available as [`Reference_Director.json`](../workflows/Reference_Director.json).

## Installation

Install the custom node from ComfyUI Manager or unpack a release archive under `ComfyUI/custom_nodes`. Releases include the compiled `web/index.js`, so a normal ComfyUI installation does not need Bun, Node.js, TypeScript, or Vite.

Frontend development requires Bun 1.3.14 or newer and uses Vite 8:

```bash
bun install --frozen-lockfile
bun run check:frontend
bun run dev
bun run build
```

The Python media libraries used at execution time—Pillow, PyAV, NumPy, and torch—are provided by ComfyUI. Registration keeps those imports lazy so an unavailable decoder reports an execution/API error instead of preventing the entire node pack from loading.

Automatic image background removal is optional. Install the CPU-backed extra in the same Python environment as ComfyUI:

```bash
pip install ".[rembg]"
```

The extra is available on Python versions supported by `rembg` (currently Python 3.11–3.13). GPU users can install the compatible `rembg[gpu]`/ONNX Runtime combination themselves instead. `rembg` is imported only when an edit requests automatic removal, and its default model may be downloaded on first use; without the extra, all other Director features continue to work and Apply reports a focused dependency error.

## Quick start

1. Add **Reference Director** from `Ollama / Multimodal`.
2. Click **Add media**, select one or more local image/audio/video files, or drop them onto the Director.
3. Enter captions directly on the cards. Captions remain raw strings and are not automatically inserted into any prompt.
4. Drag from any non-control area of a card, or use the arrow buttons, to set order. The card that will exchange position is highlighted while dragging. Images, Videos, and Audio are independently ordered.
5. Use **I**, **V**, or **A** to include or exclude a card from its matching output channel.
6. Use an Audio card's **▶/■** button for audio auditioning, or a VIDEO card's **▶/■** button for an on-demand picture-and-sound preview of its applied range. Open **Edit** to crop/flip an image, optionally extract its foreground with `rembg`, paint an erase/restore keep mask, restore a materialized edit to its immutable original, choose transparent or solid background output, or trim and audition one audio/video item by seconds.
7. Connect each media output and its matching caption output to a node that accepts ComfyUI data lists. Use `manifest_json` when stable IDs or provenance are needed.

Saving the workflow serializes versioned Director state into the node widget. Reloading restores card order, captions, toggles, edit recipes, trim ranges, and display preferences. Undo/redo is available for board changes and inside each editor; undo history itself is session-local.

## Board and editor behavior

The node renders three equal, vertically stacked top-level boards: **Images**, **Videos**, and **Audio**. It does not introduce a nested Visual category or a tab-selection state. An image appears only under Images, standalone audio only under Audio, and a video appears under both Videos and Audio. Each board has its own order and output toggle. A video's two cards share one source and trim range, while retaining independent video/audio enable switches; **V** defaults on, **A** defaults off, and a confirmed silent video's Audio control is disabled automatically. Editing the video's caption in Audio creates an audio-caption override; otherwise its derived audio inherits the Videos caption. Empty boards collapse to a compact status row instead of reserving a full card area.

The media type and duration badges share the preview's upper-left corner, and the red × removal button is overlaid in the upper-right corner. Every enabled card also shows a 1-based `#N` badge matching its position in that board's actual output list; disabled cards have no index and do not leave numbering gaps. Images, Videos, and Audio calculate these indices independently, so the two projections of one video may have different numbers. Every Images, Videos, and Audio preview has a lightly shaded bottom gradient strip containing the safe original filename without increasing card height; long names use a single-line ellipsis and expose the complete name through a tooltip. Both image and trim detail editors also show the filename. Double-clicking a card's media area—including its preview, waveform, badges, or filename—opens Edit; double-clicks in the Caption/footer body or on the overlaid × do not. Each card footer contains only its board's **I**, **V**, or **A** output toggle plus context-appropriate **▶/■**, arrows, and an accessible inline pencil Edit icon below the optional Caption field. An all-zero decoded waveform shows a center line and **Silent** label in both Grid and Trim while retaining playback; a VIDEO without an audio track instead shows **No audio track** and keeps its Audio controls disabled. Disabling an output applies a moderate grayscale and light dimming only to the image, video, waveform, or placeholder; the card border, filename, badges, Caption, and all controls remain at normal brightness and stay interactive. A VIDEO card keeps its bounded first-frame WebP as an idle poster and replaces it with one inline, sound-enabled, `playsinline` video only during explicit playback. Caption text is also editable in the detail dialogs, including while card Caption fields are hidden. During an internal reorder, the prospective destination card receives a tinted overlay and accent border until the drag leaves, ends, or drops. The red × deletes the shared source from every board; use the board-specific output toggle when only one projection should be disabled.

Image edits default to **View** interaction mode and split interaction into **View**, **Crop**, and **Mask** around an explicit crop viewport. Choose **Crop** to activate the Crop frame, which initially has focus. The responsive Image Editor expands to 1280px when space permits. Caption sits directly below the media viewport and fills the remaining left-column height, while errors and **Restore original**/**Cancel**/**Apply** stay at the bottom of the right controls column. Audio and Video Trim keep their single-column footer. When all four corners are inside the Viewport, its handles are visible, dragging inside moves the frame, and dragging a handle resizes it. Clicking outside removes focus and hides/disables every handle. A short click inside selects the frame again; if any corner is outside the Viewport, the selection enters resize-only mode. In resize-only mode, body drags and Zoom/Pan controls change only the viewport, the actual source crop stays fixed, and only corner handles currently inside the Viewport remain editable. A corner resize intentionally changes the source crop. Pan, Zoom, and resize gestures retain their starting role until completion, after which a frame with all four corners visible automatically returns to normal focused behavior. Holding **Ctrl** when starting a drag pans from anywhere, including a focused frame, a resize handle, and Mask mode, without depending on the document's keyboard focus. View mode pans without changing the crop recipe, while Mask reserves ordinary drag input for painting. With a fully visible frame focused, Crop-mode wheel input keeps the frame fixed while scaling the image and keep mask beneath it, then updates the source-pixel crop coordinates to the newly framed region. View, Mask, unfocused Crop, and resize-only Crop wheel input changes only the viewport. Zoom-out stops at the initial image-filling scale of `1×`, zoom-in is capped at `3×`, and every wheel, slider, reset, frame move/resize, and pointer-pan result passes through zoom-dependent Pan bounds. Those bounds use the entire editor Stage rather than only the Crop rectangle: at `1×`, Pan X/Y are locked to zero; after zooming in, only the image overflow may be panned. The full preview therefore remains image-covered without exposing checkerboard or empty Stage space. View-only Pan, Zoom, and Reset View changes update the live viewport without creating Undo entries. Numeric Zoom/Pan controls remain hidden from the right panel, while **Reset view** sits beside Undo/Redo. Other continuous wheel or pointer gestures remain one Undo step, and Interaction mode is included in local history so Undo/Redo restores View, Crop, or Mask together with its edit state. Crop focus remains transient UI state and is neither serialized nor added to Undo history. Clicking the backdrop closes an Image, Audio, or Video editor only when both Undo and Redo are unavailable; once either direction contains history, explicit Cancel or Close is required. The pointer policy uses explicit `unfocused`/`focused`/`clipped` selection states and a single active gesture, keeping these UX rules centralized and testable. The visible X, Y, Width, and Height controls are source-image pixel integers and remain synchronized with the selected source region. Crop offers `Custom`, `Original`, `1:1`, `4:3`, `3:4`, `3:2`, `2:3`, `16:9`, and `9:16` aspect presets. Selecting a locked preset immediately fits inward around the current crop center; corner resizing keeps the opposite corner anchored, and Width/Height pixel edits update their paired dimension. The selected preset participates in local Undo/Redo but is not added to the backend edit recipe. Mask mode enables the erase/restore keep-mask brush, size, and opacity controls. Horizontal/vertical flips, optional `rembg` foreground extraction, and transparent or solid-color background output are also available. Enabling `rembg` requests and displays a bounded transparent WebP preview before **Apply** becomes available. Its full-resolution source-SHA foreground cache is reused by Apply, so automatic extraction runs only once for an unchanged source; crop, flip, manual-mask multiplication, and background compositing then follow in that order. The manual mask uses the same normalized source coordinate space as crop, so a bounded proxy-sized mask is cropped/flipped before being resampled to the output image. **Apply** uploads the bounded PNG mask as a content-addressed sidecar and writes a new content-addressed PNG under the managed edit directory. The serialized image item retains an immutable `originalSource`; **Restore original** resets the current source to it, clears the materialized edit recipe, and preserves caption, enable state, and ordering across workflow reloads. The edit revision prevents a stale editor from overwriting a later revision. Rotation is not part of this release.

Keep-mask editing provides an Undoable **Invert mask** action. In Mask mode, the native crosshair is replaced by a circular screen-space cursor matching the current brush size: Erase is red and Restore is green. Holding **Alt** temporarily reverses Erase/Restore for both drawing and cursor color without changing the selected tool or adding modifier state to history.

A focused Crop frame that exactly fills the Viewport (`0, 0, 1, 1`) is the one movement exception: dragging its body pans the image beneath the fixed frame because the frame itself has nowhere to move. Its four corner handles remain available for resizing. At `1×` the bounded Pan range is zero, so this gesture becomes effective after zooming in.

Audio and video trims use one `[start, end]` range in seconds for that item. Video Trim adds one contained `HTMLVideoElement` above a half-height waveform, showing the current seek frame and playing embedded sound when present without generating a filmstrip; silent videos retain visual seek and playback while the waveform reports **No audio track**. The detail editor provides two range handles, precise numeric fields, selection shading, a native Seekbar bounded to the draft range, a Play/Pause/Resume toggle, and Stop. Caption sits below all timeline/range controls immediately above the footer. The footer labels range-only history as **Undo trim**/**Redo trim** on the left and keeps **Cancel**/**Apply** on the right. Seek can be set before playback or changed while playing or paused; Video Trim limits continuous seek decoding to one update per 100ms and applies the exact position when the gesture commits. Stop and an out-of-range trim adjustment return/clamp it to the draft range. During playback, Seekbar/time/playhead snapshots are timestamp-throttled to 30fps rather than tied to the display refresh count, while the trim-end boundary is checked on every RAF and `timeupdate` remains a background-tab fallback. The transient seek position is not serialized and is not part of undo history. Grid preview plays only the already-applied range and Stop returns to its start. There is no shared timeline, synchronization layer, transition editor, looping, or audio mixer. Trimming a video creates a native ComfyUI trimmed VIDEO value at execution; trimming its Audio channel decodes the same time range into a separate AUDIO value.

The server exposes playback-only `audio_preview` and `video_preview` GET routes. Both resolve the source descriptor through the same managed-path, size, MIME, link, and complete SHA-256 checks used by execution. `aiohttp.FileResponse` supplies byte-range handling, and responses are private, inline, and cached for one hour. `audio_preview` accepts standalone AUDIO sources only. `video_preview` accepts VIDEO sources regardless of whether they contain audio; the Videos Grid consumes its picture and embedded sound through an `HTMLVideoElement`, while VIDEO-derived Audio auditioning consumes the same original container through `HTMLAudioElement`. Neither route extracts tracks or transcodes, so actual browser playback depends on browser container/codec support.

One detached `HTMLAudioElement` is shared between Audio Grid and Audio Edit playback. At most one board `HTMLVideoElement` is attached to a Videos card, while an open Video Trim owns one modal-local video element that is destroyed with the dialog. Starting board audio or video stops the other. VIDEO Grid playback uses only the already-applied trim range, returns to the WebP poster on Stop or completion, and releases its source/decoder when idle. Playback also stops on deletion, restoration, editor opening, or widget teardown.

Ten standard ComfyUI fields are available under **Show advanced inputs**. The first four after the custom Director widget are real backend values with stable positions: `limit_image_pixels` at `widget_values[1]`, `max_image_pixels` at `[2]`, `composite_alpha` at `[3]`, and `alpha_background` at `[4]`. The first Boolean is labeled **Original**/**Limited**, and the float accepts an exact 0.25–40 MPixel ceiling with a 2 MPixel default. `composite_alpha` is labeled **Preserve**/**Opaque** and defaults to Preserve; Opaque composites alpha-bearing IMAGE outputs onto the native color value `alpha_background`, which defaults to black, then emits RGB. The native picker may supply `#RRGGBBAA`; its trailing alpha byte is deliberately discarded so this opaque fallback is always stored and applied as `#RRGGBB`. Upstream BOOLEAN/FLOAT/COLOR values override saved widget fallbacks when connected. In Limited mode, only enabled IMAGE outputs above the ceiling are downscaled with aspect ratio preserved; smaller images are never enlarged. Crop, flip, mask, and per-item background edits run first, global alpha compositing runs next, and MPixel limiting runs before the float32 tensor is allocated. Original uploads, materialized edit files, VIDEO, AUDIO, card metadata, and preview caches remain unchanged.

The other six fields are socketless display-only proxies: `grid_columns` (1–8), float `preview_pixels` in MPixel (0.25–16), `show_captions`, `card_aspect` (1:1, 4:3, 3:4, 16:9, or 9:16), `preview_fit` (`contain` or `cover`), and `waveform_pairs` (100–1000 min/max pairs). Audio media areas use a fixed 16:9 ratio. These six update authoritative Director state, except caption visibility, which remains under the node's `properties.referenceDirector` namespace; restoration and queueing overwrite their widgets from those values, and they remain excluded from execution outputs and the fingerprint. The four output inputs are not stored in Director state or synchronized by the frontend proxy. Their effective backend policy participates in the fingerprint: Original omits inactive `max_image_pixels`, Preserve omits inactive `alpha_background`, while Limited and Opaque record their active values. Hiding captions preserves their text. The server rounds preview requests down to bounded cache buckets, and preview resolution/fit never change execution media.

Workflow restoration initializes every card's loading state before its first render, then hydrates up to four media items concurrently without rerendering at each load start. Runtime completions remain progressive but are coalesced into at most one full board render per animation frame.

## Output contract

All media and caption outputs are explicit data lists. They are not a same-resolution IMAGE batch and are never montaged or padded. IMAGE items retain their edited/original resolution in Original mode; Limited mode independently downsizes only items above `max_image_pixels`, so output dimensions may still differ.

| Output | Type | Ordering and alignment |
| --- | --- | --- |
| `images` | IMAGE list | Enabled cards in Images order |
| `image_captions` | STRING list | Same length/index as `images` |
| `audios` | AUDIO list | Enabled standalone audio and video-derived audio in Audio order |
| `audio_captions` | STRING list | Same length/index as `audios` |
| `videos` | VIDEO list | Enabled cards in Videos order |
| `video_captions` | STRING list | Same length/index as `videos` |
| `manifest_json` | STRING | Payload-free state, source identity, derivation, and active-output mapping |

Disabled references remain in saved state and in the manifest's `items`, but are omitted from the six list outputs. Each media list is independently filtered; an image has no Audio entry, and standalone audio has no Images or Videos entry. If all applicable cards are disabled, that channel emits an empty list.

### Video audio policy

Version 1 fixes `videoAudioPolicy` to `preserve`:

- the VIDEO object retains the source container's embedded audio;
- an audio-enabled video also produces a separately decoded AUDIO value;
- that AUDIO value has the stable derived ID `<video-id>:audio` in the manifest;
- the original video ID, not the derived ID, is stored in `audio_order`.

This makes both downstream choices available without duplicating sound by default: a newly added video's **V** output starts enabled and its separate **A** output starts disabled. Enable **A** only when a downstream consumer needs a separately decoded AUDIO value. A confirmed video without a decodable audio stream keeps **A** unavailable.

## Manifest

`manifest_json` is deterministic JSON and contains no tensors, waveforms, encoded frames, base64 media, prompt text beyond the user's explicit captions, or absolute filesystem paths. A shortened example is shown below:

```json
{
  "version": 1,
  "video_audio_policy": "preserve",
  "image_output": {
    "mode": "limited",
    "maxPixels": 2000000,
    "alphaMode": "opaque",
    "alphaBackground": "#000000"
  },
  "image_order": ["image-1"],
  "video_order": ["video-1"],
  "audio_order": ["video-1"],
  "outputs": {
    "images": ["image-1"],
    "audios": ["video-1:audio"],
    "videos": ["video-1"]
  },
  "output_captions": {
    "images": ["costume reference"],
    "audios": ["room tone"],
    "videos": ["movement reference"]
  },
  "items": {
    "image-1": {
      "kind": "image",
      "source": {
        "path": "reference_director/sources/costume.png",
        "mime": "image/png",
        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      },
      "caption": { "text": "costume reference", "source": "user" },
      "enabled": { "image": true }
    },
    "video-1": {
      "kind": "video",
      "source": {
        "path": "reference_director/sources/movement.mp4",
        "mime": "video/mp4",
        "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      },
      "caption": { "text": "movement reference", "source": "user" },
      "enabled": { "video": true, "audio": true }
    },
    "video-1:audio": {
      "kind": "audio",
      "source": {
        "path": "reference_director/sources/movement.mp4",
        "mime": "video/mp4",
        "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      },
      "caption": { "text": "room tone", "source": "user" },
      "enabled": { "audio": true },
      "derived_from": "video-1",
      "derivation": "embedded_audio"
    }
  }
}
```

Caption arrays are included as a direct alignment receipt. The `items` object is the authoritative source/provenance map; image edit recipes and audio/video crop ranges appear there when present.

## Storage, security, and privacy

Browser-selected files are streamed to the same ComfyUI server and stored below its input directory:

```text
ComfyUI/input/reference_director/
├── sources/   # validated original media with safe original filenames
├── edits/     # materialized PNG edits and JSON revision sidecars
├── masks/     # managed mask namespace (brush masks may also use content-addressed sources)
└── cache/     # generated WebP previews, rembg PNG previews, and waveform summaries
```

Uploads are limited to 256 MiB and are content-inspected before a canonical extension is selected. A safe basename derived from the browser-provided original filename is retained under `sources`; path components and platform-invalid characters are removed, and a different file with the same name receives a numbered suffix such as `photo (2).png`. Re-uploading the same bytes under the same name reuses the existing file. Keeping originals in `input/reference_director/sources` separates Director-owned input from unrelated ComfyUI uploads while keeping generated `edits`, `masks`, and `cache` artifacts distinct. Managed API requests accept only relative `reference_director/sources`, `edits`, or `masks` descriptors; absolute paths, traversal segments, symlinks, junctions/reparse points, unsupported suffixes, and identity mismatches are rejected. This includes the query descriptor used by the audio-preview route. Source integrity is bound to the descriptor's complete SHA-256 value rather than its filename. Before ComfyUI decides whether a cached result can be reused—and again while loading an uncached execution—the Director checks containment, link traversal, file size, optional saved size, and the complete SHA-256 hash of every active source and required mask.

Ordinary image previews are bounded, cached WebP derivatives rather than original-file responses. Proxy requests are rounded down to one of seven finite pixel buckets from 65,536 through 16 million pixels, and new image-proxy URLs expose only the first 32 hexadecimal characters (128 bits) of the SHA-derived cache key. The explicit `background_preview` request stores a full-resolution transparent PNG under a separate source-SHA cache for exact Apply reuse, while the browser receives a bounded transparent WebP derivative. Waveform cache keys accept only canonical start/end crop values and bounded peak counts; caches contain min/max pairs, not compressed audio. Image Apply writes a new PNG and provenance sidecar instead of modifying the original. Errors do not disclose absolute server paths.

The core Director does not contact Ollama or a cloud inference service. If automatic removal is enabled and the default `rembg` model is not cached yet, the `rembg` library may download that model from its configured host; inference then runs locally on the ComfyUI server. Files also travel from the browser to the ComfyUI host, so anyone authorized to use that server should be treated as able to create managed media. Workflow JSON contains captions, managed relative paths, hashes, sizes, and edit state but not the media bytes. Original uploads may still contain their original file metadata on disk.

There is no automatic garbage collection. Delete unreferenced files under `ComfyUI/input/reference_director` only after confirming that no saved workflow needs them. A workflow copied to another ComfyUI installation is not self-contained; copy its referenced managed media or add the files again.

## Limits

| Resource | Limit |
| --- | ---: |
| Images per state | 32 |
| Standalone audio items per state | 8 |
| Videos per state | 4 |
| Maximum possible AUDIO outputs | 12 (8 standalone + 4 video-derived) |
| Source file | 256 MiB |
| Serialized Director state / JSON API request | 1,000,000 characters / 1 MiB |
| Caption | 16,384 characters |
| Image upload inspection / IMAGE execution | 40,000,000 decoded pixels |
| Audio duration | 2 hours |
| Selected decoded AUDIO waveform | 256 MiB per output item |
| Aggregate decoded IMAGE + AUDIO tensors | 1 GiB per Director execution |
| Video duration | 1 hour |
| Preview proxy | 65,536–16,000,000 bucketed pixels (advanced input accepts 0.25–16 MP) |
| Waveform summary | 200–500 min/max pairs |

Limits are validated again by the backend. Audio decoding retains only the selected crop, and rejects an output before its float32 waveform would exceed the per-item memory bound. Editing or replacing managed files outside the Director can invalidate size/hash/revision checks and intentionally stops execution.

## Compatibility and known limitations

- The project declares ComfyUI 0.19.3 or newer. VIDEO output and trimming additionally require a ComfyUI build exposing the V3 `InputImpl.VideoFromFile` and `as_trimmed` implementation.
- The custom DOM widget is shipped as one Vite 8 bundle at `web/index.js` and uses standard modern browser APIs, including modal dialogs, drag/drop, `AbortController`, canvas, and object URLs.
- Transparent image output is an RGBA tensor (`[1,H,W,4]`). Some IMAGE consumers assume RGB (`[B,H,W,3]`); choose a solid editor background before connecting those nodes.
- Animated image formats are treated as one still IMAGE rather than a VIDEO sequence.
- Empty typed lists are valid Director outputs, but some downstream nodes assume at least one item and may fail. Keep one item enabled or insert an empty-list-aware adapter for those consumers.
- VIDEO preserves embedded audio while the Audio channel can emit the same soundtrack separately. This is deliberate, not automatic deduplication.
- For standalone audio containing multiple tracks, waveform preview and AUDIO output use the first supported track. Attached cover art is not treated as a video track during upload inspection.
- To keep metadata, proxy, derived AUDIO, and native ComfyUI VIDEO selection aligned across supported ComfyUI versions, a VIDEO source must have exactly one primary video track, no attached-picture video track, and at most one decodable audio track.
- Card selection is single-item in this release. There are no batch edits, shared timeline, transitions, audio mixing, prompt composer, or built-in media analyzer.
- File ingestion is from local browser files into managed ComfyUI input storage. Arbitrary server paths and remote media URLs are intentionally unsupported.
- Automatic subject/background removal requires the optional `rembg` extra and may download/load its default model on first use. Erase/Restore remains available for manual refinement or as a dependency-free alternative.
- There is no montage, padding, sample-rate conversion, or frame-rate conversion. IMAGE execution resizing occurs only when the explicit **Limited** output policy is enabled; explicit edits/trims and EXIF orientation normalization can also change dimensions/orientation, while preview scaling never changes execution media.

## Manual smoke checklist

Run this after building a release against the target ComfyUI version:

1. Start ComfyUI, add `Reference Director`, and confirm the full DOM board appears without a console error.
2. Add two differently sized images, one audio file, one video with sound, and one silent video. Confirm upload progress, image/video previews, Audio-channel waveforms, and metadata; confirm both videos start with **A** off and the silent video's **A** control is unavailable. Enable **A** on the video with sound for the derived-AUDIO checks below.
3. Give every output item a unique caption. Give the video's Audio card a different caption from its Videos card.
4. Confirm Images, Videos, and Audio are equal top-level sections stacked vertically, with empty sections rendered compactly. Reorder them independently by dragging from the card surface and by using the footer arrow controls below Caption; verify the prospective destination card is highlighted while the controls remain clickable and do not initiate a drag. Confirm every media preview has a light bottom filename gradient with ellipsis and a full-name tooltip without changing card height, and that filenames remain visible in each detail editor. Toggle each output off and confirm only its media visual becomes moderately desaturated and lightly dimmed while the border, filename, badges, Caption, and controls remain at normal brightness. Confirm each card shows only its section's output toggle, and the overlaid red × removes a shared video from both Videos and Audio.
5. Confirm the wider image editor opens in View mode with Caption below the viewport. Confirm numeric Viewport controls are hidden and Reset view is beside Undo/Redo. Click the untouched backdrop and confirm the editor closes; reopen it, create an edit, and confirm backdrop clicks are then ignored. Change View Pan/Zoom and confirm Undo remains unchanged; then select Crop and Mask and verify Undo/Redo restores each Interaction mode. Return to Crop. Exercise Custom, Original, square, landscape, and portrait aspect presets; confirm selection fits inward, Undo/Redo restores the preset, Width/Height remain coupled, and every corner preserves the ratio. Return to Custom, then drag inside the crop to move it, drag outside to pan the image, use Ctrl-drag to pan from inside or from Mask mode, and resize from all four corner handles; confirm the source-pixel integer fields follow every change and Pan remains bounded to an image-covered Stage. Then switch to Mask Drawing, flip one image, enable `rembg` removal, and inspect the extracted foreground before Apply becomes available. Paint with Erase and Restore at different brush sizes/opacities, exercise editor-local undo/redo and viewport pan/zoom, then apply a transparent background. Confirm the rembg cache is reused, a content-addressed mask and a new managed PNG/revision are used without changing the original. Reopen Edit, choose **Restore original**, save/reload the workflow, and confirm the original source returns while caption, enable state, and ordering remain intact. Repeat with a solid background for an RGB-only consumer, and verify an installation without the extra reports the optional-dependency error without breaking node registration.
6. Preview an Audio card and confirm **▶** changes to **■**, Stop returns to the applied trim start, and starting another reference stops the first. Preview a VIDEO and confirm its embedded audio plays with the picture, while starting its Audio card stops the VIDEO and auditions the same range as audio-only. In **Edit**, drag both trim handles, use the numeric fields and Seekbar before/during/after playback, audition the draft selection with the Play/Pause/Resume toggle and Stop, and verify Apply updates output duration while Cancel does not. Confirm playback is disabled for a silent video's Audio card, and the enabled video-derived AUDIO contains the matching trimmed range.
7. Queue the node and inspect `manifest_json`: list/caption lengths match; order matches the board; disabled items remain under `items`; derived audio uses `<video-id>:audio`; no base64 or absolute path appears.
8. Save, reload, and queue the workflow. Confirm state restoration and identical execution order.
9. Disable every item in one channel and verify the Director emits an empty list; record whether the intended downstream consumer accepts it.
10. Modify or replace a managed source file outside ComfyUI and confirm the next execution stops on its size/hash identity check, then restore or re-add the source.
11. Open **Show advanced inputs**, change `grid_columns`, the float `preview_pixels` MPixel value, `show_captions`, `card_aspect`, `preview_fit`, and `waveform_pairs`. Confirm the card grid, proxy requests, image/video ratio and fit, and waveform density update while Audio remains 16:9; hidden captions remain editable through **Edit**, and none of the six display fields changes execution outputs or the fingerprint. Then set `limit_image_pixels` to Limited and enter an exact `max_image_pixels` value below a large source's resolution. Confirm only the IMAGE tensor is downscaled, aspect ratio is retained, and small images are not enlarged. Set `composite_alpha` to Opaque and change `alpha_background`; confirm alpha-bearing outputs become three-channel RGB on that color while RGB inputs are unchanged. Confirm inactive max/background values do not change the fingerprint, while active values do.
