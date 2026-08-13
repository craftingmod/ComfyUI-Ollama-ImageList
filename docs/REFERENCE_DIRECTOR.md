# Reference Director

`Reference Director` is a ComfyUI V3 node for arranging local image, audio, and video references before another node analyzes or generates from them. It owns file ingestion, independent visual/audio ordering, raw user captions, enable state, and non-destructive edits. It does not load an LLM/VLM, rewrite captions, or assemble a generation prompt.

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
4. Drag from any non-control area of a card, or use the arrow buttons, to set order. Visual and audio order are independent.
5. Use **V** and **A** to include or exclude an item from the corresponding output channel.
6. Open **Edit** to crop/flip an image, optionally extract its foreground with `rembg`, paint an erase/restore keep mask, choose transparent or solid background output, or trim one audio/video item by seconds.
7. Connect each media output and its matching caption output to a node that accepts ComfyUI data lists. Use `manifest_json` when stable IDs or provenance are needed.

Saving the workflow serializes versioned Director state into the node widget. Reloading restores card order, captions, toggles, edit recipes, trim ranges, and display preferences. Undo/redo is available for board changes and inside each editor; undo history itself is session-local.

## Board and editor behavior

An image appears only in the **Visual** channel, standalone audio only in **Audio**, and a video in both. The Visual and Audio boards are stacked vertically so each board uses the full node width. The video card shares one source and trim range across the channels, but it has independent visual/audio enable switches. Editing the video's caption in the Audio channel creates an audio-caption override; otherwise its derived audio inherits the video caption.

Image edits support a normalized rectangular crop, horizontal/vertical flips, optional `rembg` foreground extraction, an erase/restore keep-mask brush with size and opacity controls, and transparent or solid-color background output. Automatic extraction runs on the full image before crop, flip, manual-mask multiplication, and background compositing. The manual mask uses the same normalized source coordinate space as crop, so a bounded proxy-sized mask is cropped/flipped before being resampled to the output image. Editor-local undo/redo covers brush strokes and other draft changes. Viewport pan/zoom changes only the editing view; it is not an output transform. **Apply** uploads the bounded PNG mask as a content-addressed sidecar, writes a new content-addressed PNG under the managed edit directory, and retains the original source. The edit revision prevents a stale editor from overwriting a later revision. Rotation is not part of this release.

Audio and video trims use one `[start, end]` range in seconds for that item. There is no shared timeline, synchronization layer, transition editor, or audio mixer. Trimming a video creates a native ComfyUI trimmed VIDEO value at execution; trimming its Audio channel decodes the same time range into a separate AUDIO value.

Display settings such as card aspect ratio, preview resolution, and waveform pair count are persisted for the UI but excluded from the execution fingerprint. Changing only a preview preference does not change the media/caption contract.

## Output contract

All media and caption outputs are explicit data lists. They are not a same-resolution IMAGE batch and are never montaged, padded, or automatically resized.

| Output | Type | Ordering and alignment |
| --- | --- | --- |
| `images` | IMAGE list | Enabled image cards in Visual order |
| `image_captions` | STRING list | Same length/index as `images` |
| `audios` | AUDIO list | Enabled standalone audio and video-derived audio in Audio order |
| `audio_captions` | STRING list | Same length/index as `audios` |
| `videos` | VIDEO list | Enabled video cards in Visual order |
| `video_captions` | STRING list | Same length/index as `videos` |
| `manifest_json` | STRING | Payload-free state, source identity, derivation, and active-output mapping |

Disabled references remain in saved state and in the manifest's `items`, but are omitted from the six list outputs. Each media list is independently filtered; an image has no Audio entry, and standalone audio has no Visual entry. If all applicable cards are disabled, that channel emits an empty list.

### Video audio policy

Version 1 fixes `videoAudioPolicy` to `preserve`:

- the VIDEO object retains the source container's embedded audio;
- an audio-enabled video also produces a separately decoded AUDIO value;
- that AUDIO value has the stable derived ID `<video-id>:audio` in the manifest;
- the original video ID, not the derived ID, is stored in `audio_order`.

This makes both downstream choices available, but a consumer that plays embedded VIDEO audio and the derived AUDIO simultaneously can duplicate the soundtrack. Disable **A** for that video when only the embedded track is wanted. For a video without a decodable audio stream, disable **A** or execution will report that no audio stream is available.

## Manifest

`manifest_json` is deterministic JSON and contains no tensors, waveforms, encoded frames, base64 media, prompt text beyond the user's explicit captions, or absolute filesystem paths. A shortened example is shown below:

```json
{
  "version": 1,
  "video_audio_policy": "preserve",
  "visual_order": ["image-1", "video-1"],
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
        "path": "reference_director/sources/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
        "mime": "image/png",
        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      },
      "caption": { "text": "costume reference", "source": "user" },
      "enabled": { "visual": true }
    },
    "video-1": {
      "kind": "video",
      "source": {
        "path": "reference_director/sources/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4",
        "mime": "video/mp4",
        "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      },
      "caption": { "text": "movement reference", "source": "user" },
      "enabled": { "visual": true, "audio": true }
    },
    "video-1:audio": {
      "kind": "audio",
      "source": {
        "path": "reference_director/sources/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4",
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
├── sources/   # validated original media, named by SHA-256
├── edits/     # materialized PNG edits and JSON revision sidecars
├── masks/     # managed mask namespace (brush masks may also use content-addressed sources)
└── cache/     # generated WebP previews and waveform summaries
```

Uploads are limited to 256 MiB and are content-inspected before a canonical extension is selected. Equal source bytes reuse one content-addressed file. Managed API requests accept only relative `reference_director/sources`, `edits`, or `masks` descriptors; absolute paths, traversal segments, symlinks, junctions/reparse points, unsupported suffixes, and identity mismatches are rejected. Before ComfyUI decides whether a cached result can be reused—and again while loading an uncached execution—the Director checks containment, link traversal, file size, optional saved size, and the complete SHA-256 hash of every active source and required mask.

Previews are bounded, cached WebP derivatives rather than original-file responses. Proxy requests are rounded down to one of seven finite pixel buckets from 65,536 through 16 million pixels. Waveform cache keys accept only canonical start/end crop values and bounded peak counts; caches contain min/max pairs, not compressed audio. Image Apply writes a new PNG and provenance sidecar instead of modifying the original. Errors do not disclose absolute server paths.

The core Director does not contact Ollama or a cloud inference service. If automatic removal is enabled and the default `rembg` model is not cached yet, the `rembg` library may download that model from its configured host; inference then runs locally on the ComfyUI server. Files also travel from the browser to the ComfyUI host, so anyone authorized to use that server should be treated as able to create managed media. Workflow JSON contains captions, relative content-addressed paths, hashes, sizes, and edit state but not the media bytes. Original uploads may still contain their original file metadata on disk.

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
| Preview proxy | 65,536–16,000,000 bucketed pixels (UI choices currently stop at 4 MP) |
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
- There is no automatic execution resize, montage, padding, sample-rate conversion, or frame-rate conversion. Explicit edits/trims and EXIF orientation normalization can change an image's dimensions/orientation; preview scaling never changes execution media.

## Manual smoke checklist

Run this after building a release against the target ComfyUI version:

1. Start ComfyUI, add `Reference Director`, and confirm the full DOM board appears without a console error.
2. Add two differently sized images, one audio file, one video with sound, and one silent video. Confirm upload progress, image/video previews, Audio-channel waveforms, and metadata; confirm the silent video's **A** output is disabled automatically.
3. Give every output item a unique caption. Give the video's Audio card a different caption from its Visual card.
4. Confirm Visual and Audio are stacked vertically. Reorder them independently by dragging from the card surface and by using arrow controls; verify controls remain clickable and do not initiate a drag. Toggle one card off in each channel and confirm the red × removes a reference.
5. Crop and flip one image, enable `rembg` removal, paint with Erase and Restore at different brush sizes/opacities, exercise editor-local undo/redo and viewport pan/zoom, then apply a transparent background. Confirm a content-addressed mask and a new managed PNG/revision are used without changing the original. Repeat with a solid background for an RGB-only consumer, and verify an installation without the extra reports the optional-dependency error without breaking node registration.
6. Trim audio and video to known ranges and verify output durations. Confirm the VIDEO still exposes embedded audio and the enabled video-derived AUDIO contains the matching trimmed range.
7. Queue the node and inspect `manifest_json`: list/caption lengths match; order matches the board; disabled items remain under `items`; derived audio uses `<video-id>:audio`; no base64 or absolute path appears.
8. Save, reload, and queue the workflow. Confirm state restoration and identical execution order.
9. Disable every item in one channel and verify the Director emits an empty list; record whether the intended downstream consumer accepts it.
10. Modify or replace a managed source file outside ComfyUI and confirm the next execution stops on its size/hash identity check, then restore or re-add the source.
