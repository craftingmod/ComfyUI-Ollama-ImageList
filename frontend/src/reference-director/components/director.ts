import type { ComfyNode } from "../../comfyui";
import { ReferenceDirectorApi } from "../api";
import { AudioPreviewPlayer } from "../audio-preview-player";
import { openImageEditor } from "../editors/image-editor";
import { openTrimEditor } from "../editors/trim-editor";
import {
  canRedo,
  canUndo,
  commitHistory,
  createHistory,
  redoHistory,
  undoHistory,
  type HistoryState,
} from "../history";
import { directorReducer, type DirectorAction, type DirectorChannel } from "../reducer";
import { deserializeDirectorState, serializeDirectorState } from "../serialization";
import {
  createMediaItem,
  isAudioItem,
  type DirectorState,
  type ItemRuntime,
  type MediaItem,
} from "../types";
import { VideoPreviewPlayer } from "../video-preview-player";

interface PendingUpload {
  id: string;
  file: File;
  objectUrl: string;
}

interface RuntimeLoadOptions {
  renderStart?: boolean;
  completionRender?: "immediate" | "scheduled";
}

export interface DirectorChangeEvents {
  beforeChange?(): void;
  afterChange?(): void;
}

export interface DirectorDisplayState {
  gridColumns: number;
  previewPixels: number;
  showCaptions: boolean;
}

const DRAG_MIME = "application/x-reference-director-item";
const NODE_PROPERTY_KEY = "referenceDirector";
const MEDIA_EXTENSIONS = {
  image: new Set(["jpg", "jpeg", "png", "webp", "bmp", "gif", "tif", "tiff"]),
  audio: new Set(["wav", "mp3", "flac", "ogg", "opus", "m4a", "aac", "mka"]),
  video: new Set(["mp4", "mkv", "webm", "mov", "avi"]),
} as const;
const MEDIA_LIMITS = { image: 32, audio: 8, video: 4 } as const;

function fileMediaKind(file: File): keyof typeof MEDIA_EXTENSIONS | undefined {
  const mimeMatch = /^(image|audio|video)\//.exec(file.type);
  if (mimeMatch) return mimeMatch[1] as keyof typeof MEDIA_EXTENSIONS;
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!extension) return undefined;
  for (const [kind, extensions] of Object.entries(MEDIA_EXTENSIONS)) {
    if ((extensions as ReadonlySet<string>).has(extension)) return kind as keyof typeof MEDIA_EXTENSIONS;
  }
  return undefined;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;",
    };
    return entities[character] ?? character;
  });
}

function filename(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] ?? path;
}

function itemFilename(item: MediaItem): string {
  return item.sourceFilename || filename(item.source.path);
}

function showCaptionsProperty(node: ComfyNode): boolean {
  const value = node.properties?.[NODE_PROPERTY_KEY];
  if (typeof value !== "object" || value === null) return true;
  const showCaptions = (value as Record<string, unknown>).showCaptions;
  return typeof showCaptions === "boolean" ? showCaptions : true;
}

function setShowCaptionsProperty(node: ComfyNode, showCaptions: boolean): void {
  const current = node.properties?.[NODE_PROPERTY_KEY];
  const namespace = typeof current === "object" && current !== null
    ? current as Record<string, unknown>
    : {};
  node.properties = {
    ...node.properties,
    [NODE_PROPERTY_KEY]: { ...namespace, showCaptions },
  };
}

function durationLabel(item: MediaItem, runtime: ItemRuntime | undefined): string {
  const duration = item.kind === "image" ? undefined : item.crop ? item.crop.end - item.crop.start : runtime?.metadata?.duration;
  return duration === undefined ? "" : `${duration.toFixed(duration < 10 ? 2 : 1)}s`;
}

function drawWaveform(canvas: HTMLCanvasElement, pairs: ReadonlyArray<readonly [number, number]>): void {
  const width = Math.max(160, Math.floor(canvas.clientWidth * (globalThis.devicePixelRatio || 1)));
  const height = Math.max(80, Math.floor(canvas.clientHeight * (globalThis.devicePixelRatio || 1)));
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, width, height);
  context.strokeStyle = "#8eb9ff";
  context.lineWidth = Math.max(1, globalThis.devicePixelRatio || 1);
  context.beginPath();
  pairs.forEach(([minimum, maximum], index) => {
    const x = (index / Math.max(1, pairs.length - 1)) * width;
    context.moveTo(x, height / 2 - maximum * height * 0.42);
    context.lineTo(x, height / 2 - minimum * height * 0.42);
  });
  context.stroke();
}

type ReleaseRuntimeSlot = () => void;

interface RuntimeWaiter {
  signal: AbortSignal;
  resolve: (release: ReleaseRuntimeSlot | undefined) => void;
  onAbort: () => void;
}

class RuntimeLoadLimiter {
  #active = 0;
  #queue: RuntimeWaiter[] = [];

  constructor(private readonly limit: number) {}

  acquire(signal: AbortSignal): Promise<ReleaseRuntimeSlot | undefined> {
    if (signal.aborted) return Promise.resolve(undefined);
    return new Promise((resolve) => {
      const waiter: RuntimeWaiter = {
        signal,
        resolve,
        onAbort: () => {
          const index = this.#queue.indexOf(waiter);
          if (index >= 0) this.#queue.splice(index, 1);
          resolve(undefined);
        },
      };
      signal.addEventListener("abort", waiter.onAbort, { once: true });
      this.#queue.push(waiter);
      this.#pump();
    });
  }

  #pump(): void {
    while (this.#active < this.limit && this.#queue.length > 0) {
      const waiter = this.#queue.shift();
      if (!waiter) return;
      waiter.signal.removeEventListener("abort", waiter.onAbort);
      if (waiter.signal.aborted) {
        waiter.resolve(undefined);
        continue;
      }
      this.#active += 1;
      let released = false;
      waiter.resolve(() => {
        if (released) return;
        released = true;
        this.#active -= 1;
        this.#pump();
      });
    }
  }
}

export class ReferenceDirectorController {
  readonly root: HTMLElement;
  #node: ComfyNode;
  #api: ReferenceDirectorApi;
  #history: HistoryState<DirectorState>;
  #runtime = new Map<string, ItemRuntime>();
  #runtimeSequences = new Map<string, number>();
  #runtimeSequence = 0;
  #runtimeEpoch = 0;
  #runtimeLimiter = new RuntimeLoadLimiter(4);
  #audioPreview = new AudioPreviewPlayer();
  #videoPreview = new VideoPreviewPlayer();
  #unsubscribeAudioPreview: (() => void) | undefined;
  #unsubscribeVideoPreview: (() => void) | undefined;
  #pending = new Map<string, PendingUpload>();
  #selectedId: string | undefined;
  #status = "Drop image, audio, or video files to begin.";
  #destroyController = new AbortController();
  #stateController = new AbortController();
  #modalController: AbortController | undefined;
  #drag: { id: string; channel: DirectorChannel } | undefined;
  #armedDrag: { id: string; channel: DirectorChannel } | undefined;
  #dropTarget: HTMLElement | undefined;
  #composing = false;
  #renderPending = false;
  #renderFrame: number | undefined;
  #destroyed = false;
  #changeEvents: DirectorChangeEvents;

  constructor(
    root: HTMLElement,
    node: ComfyNode,
    api: ReferenceDirectorApi,
    serialized: unknown,
    changeEvents: DirectorChangeEvents = {},
  ) {
    this.root = root;
    this.#node = node;
    this.#api = api;
    this.#changeEvents = changeEvents;
    const parsed = deserializeDirectorState(serialized);
    this.#history = createHistory(parsed.state);
    if (parsed.issues.length > 0) this.#status = parsed.issues.join(" ");
    this.#installEvents();
    this.#unsubscribeAudioPreview = this.#audioPreview.subscribe(() => this.#syncPlaybackUi());
    this.#unsubscribeVideoPreview = this.#videoPreview.subscribe(() => this.#syncPlaybackUi());
    this.#hydrateRestoredRuntime();
  }

  get state(): DirectorState {
    return this.#history.present;
  }

  get displayState(): DirectorDisplayState {
    return {
      gridColumns: this.state.ui.gridColumns,
      previewPixels: this.state.ui.previewMaxPixels / 1_000_000,
      showCaptions: showCaptionsProperty(this.#node),
    };
  }

  writeDisplayProxy(values: Partial<DirectorDisplayState>): void {
    if (this.#destroyed) return;
    const gridColumns = values.gridColumns === undefined || !Number.isFinite(values.gridColumns)
      ? this.state.ui.gridColumns
      : Math.min(8, Math.max(1, Math.round(values.gridColumns)));
    const previewMaxPixels = values.previewPixels === undefined || !Number.isFinite(values.previewPixels)
      ? this.state.ui.previewMaxPixels
      : Math.min(16_000_000, Math.max(250_000, Math.round(values.previewPixels * 1_000_000)));
    const previewChanged = previewMaxPixels !== this.state.ui.previewMaxPixels;
    if (gridColumns !== this.state.ui.gridColumns || previewChanged) {
      this.#dispatch({ type: "set-ui", values: { gridColumns, previewMaxPixels } });
      if (previewChanged) {
        this.#reloadChannelRuntime("image");
        this.#reloadChannelRuntime("video");
      }
    }
    if (values.showCaptions !== undefined) {
      const showCaptions = Boolean(values.showCaptions);
      if (showCaptions !== showCaptionsProperty(this.#node)) {
        this.#recordGraphChange(() => setShowCaptionsProperty(this.#node, showCaptions));
        this.#node.setDirtyCanvas(true, true);
        this.render();
      }
    }
  }

  restore(serialized: unknown): void {
    if (this.#destroyed) return;
    this.#audioPreview.stop();
    this.#videoPreview.stop();
    this.#modalController?.abort();
    this.#stateController.abort();
    this.#stateController = new AbortController();
    this.#runtimeEpoch += 1;
    for (const pending of this.#pending.values()) URL.revokeObjectURL(pending.objectUrl);
    this.#pending.clear();
    const parsed = deserializeDirectorState(serialized);
    this.#history = createHistory(parsed.state);
    this.#selectedId = undefined;
    this.#runtime.clear();
    this.#runtimeSequences.clear();
    this.#runtimeSequence = 0;
    this.#status = parsed.issues.length > 0 ? parsed.issues.join(" ") : "Workflow state restored.";
    this.#cancelScheduledRender();
    this.#hydrateRestoredRuntime(true);
  }

  serialize(): string {
    return serializeDirectorState(this.state);
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.#destroyed = true;
    this.#cancelScheduledRender();
    this.#modalController?.abort();
    this.#stateController.abort();
    this.#destroyController.abort();
    this.#unsubscribeAudioPreview?.();
    this.#unsubscribeVideoPreview?.();
    this.#audioPreview.destroy();
    this.#videoPreview.destroy();
    for (const pending of this.#pending.values()) URL.revokeObjectURL(pending.objectUrl);
    this.#pending.clear();
    this.#runtime.clear();
    this.#runtimeSequences.clear();
    this.#dropTarget = undefined;
    this.root.replaceChildren();
  }

  render(force = false): void {
    if (this.#destroyed) return;
    this.#cancelScheduledRender();
    const active = document.activeElement;
    if (
      !force &&
      (this.#composing || (active instanceof HTMLTextAreaElement && this.root.contains(active)))
    ) {
      this.#renderPending = true;
      return;
    }
    this.#renderPending = false;
    const state = this.state;
    this.root.style.setProperty("--rd-card-aspect", state.ui.cardAspectRatio);
    this.root.style.setProperty("--rd-grid-columns", String(state.ui.gridColumns));
    this.root.innerHTML = `
      <section class="rd-toolbar" aria-label="Reference Director toolbar">
        <label class="rd-primary rd-file-button">Add media<input type="file" accept="image/*,audio/*,video/*" multiple></label>
        <button type="button" data-action="undo" ${canUndo(this.#history) ? "" : "disabled"} title="Undo (Ctrl+Z)">↶ Undo</button>
        <button type="button" data-action="redo" ${canRedo(this.#history) ? "" : "disabled"} title="Redo (Ctrl+Shift+Z)">↷ Redo</button>
        <span class="rd-toolbar__count">${Object.keys(state.items).length} reference${Object.keys(state.items).length === 1 ? "" : "s"}</span>
      </section>
      <details class="rd-settings"><summary>Display settings</summary><div>
        <label>Card aspect<select data-field="card-aspect"><option value="1 / 1"${state.ui.cardAspectRatio === "1 / 1" ? " selected" : ""}>1:1</option><option value="4 / 3"${state.ui.cardAspectRatio === "4 / 3" ? " selected" : ""}>4:3</option><option value="16 / 9"${state.ui.cardAspectRatio === "16 / 9" ? " selected" : ""}>16:9</option></select></label>
        <label>Waveform pairs<select data-field="waveform-peaks"><option value="200"${state.ui.waveformPeaks === 200 ? " selected" : ""}>200</option><option value="300"${state.ui.waveformPeaks === 300 ? " selected" : ""}>300</option><option value="500"${state.ui.waveformPeaks === 500 ? " selected" : ""}>500</option></select></label>
      </div></details>
      <p class="rd-status" role="status">${escapeHtml(this.#status)}</p>
      ${this.#pendingMarkup()}
      <div class="rd-channels">
        ${this.#channelMarkup("image", "Images", state.imageOrder)}
        ${this.#channelMarkup("video", "Videos", state.videoOrder)}
        ${this.#channelMarkup("audio", "Audio", state.audioOrder)}
      </div>`;
    this.#drawWaveforms();
    this.#syncPlaybackUi();
  }

  #hydrateRestoredRuntime(force = false): void {
    const items = Object.values(this.state.items);
    for (const item of items) this.#runtime.set(item.id, { loading: true });
    this.render(force);
    for (const item of items) {
      void this.#loadRuntime(item, { renderStart: false, completionRender: "scheduled" });
    }
  }

  #scheduleRender(): void {
    if (this.#destroyed || this.#renderFrame !== undefined) return;
    this.#renderFrame = globalThis.requestAnimationFrame(() => {
      this.#renderFrame = undefined;
      this.render();
    });
  }

  #cancelScheduledRender(): void {
    if (this.#renderFrame === undefined) return;
    globalThis.cancelAnimationFrame(this.#renderFrame);
    this.#renderFrame = undefined;
  }

  #pendingMarkup(): string {
    if (this.#pending.size === 0) return "";
    return `<div class="rd-pending" aria-label="Pending uploads">${[...this.#pending.values()]
      .map(
        (pending) =>
          `<div><span class="rd-spinner" aria-hidden="true"></span><span>${escapeHtml(pending.file.name)}</span><small>Uploading…</small></div>`,
      )
      .join("")}</div>`;
  }

  #channelMarkup(channel: DirectorChannel, label: string, order: string[]): string {
    const cards = order.map((id) => this.#cardMarkup(channel, id)).join("");
    const descriptions: Record<DirectorChannel, string> = {
      image: "Image output and captions",
      video: "Video output and captions",
      audio: "Standalone and video sound",
    };
    return `<section class="rd-channel" data-channel="${channel}" aria-label="${label} references">
      <header><div><strong>${label}</strong><span>${order.length}</span></div><small>${descriptions[channel]}</small></header>
      <div class="rd-card-grid${cards ? "" : " is-empty"}" data-drop-zone="${channel}">${cards || `<div class="rd-empty">No ${label.toLowerCase()} added</div>`}</div>
    </section>`;
  }

  #cardMarkup(channel: DirectorChannel, id: string): string {
    const item = this.state.items[id];
    if (!item) return "";
    const runtime = this.#runtime.get(id);
    const selected = this.#selectedId === id;
    const caption = item.kind === "video" && channel === "audio" ? item.audioCaptionOverride ?? item.caption : item.caption;
    const media = this.#mediaMarkup(channel, item, runtime);
    const loading = runtime?.loading ? `<span class="rd-spinner" title="Loading"></span>` : "";
    const error = runtime?.error ? `<p class="rd-card__error" role="alert">${escapeHtml(runtime.error)}</p>` : "";
    const imageEnabled = item.kind === "image" ? item.imageEnabled : false;
    const videoEnabled = item.kind === "video" ? item.videoEnabled : false;
    const silentVideo = item.kind === "video" && runtime?.metadata?.hasAudio === false;
    const audioEnabled = isAudioItem(item) ? item.audioEnabled : false;
    const outputEnabled = channel === "image" ? imageEnabled : channel === "video" ? videoEnabled : audioEnabled;
    const duration = durationLabel(item, runtime);
    const mediaFilename = itemFilename(item);
    const playbackOwner = `grid:${id}`;
    const audioPlaybackActive = this.#audioPreview.snapshot.owner === playbackOwner
      && (this.#audioPreview.snapshot.status === "playing" || this.#audioPreview.snapshot.status === "loading");
    const videoPlaybackActive = this.#videoPreview.snapshot.owner === playbackOwner
      && (this.#videoPreview.snapshot.status === "playing" || this.#videoPreview.snapshot.status === "loading");
    const playbackDuration = item.kind === "image" ? undefined : runtime?.metadata?.duration ?? item.crop?.end;
    const audioPlaybackDisabled = silentVideo || runtime?.loading || playbackDuration === undefined;
    const videoPlaybackDisabled = runtime?.loading || playbackDuration === undefined;
    return `<article class="rd-card${selected ? " is-selected" : ""}${runtime?.error ? " has-error" : ""}${outputEnabled ? "" : " is-output-disabled"}" data-id="${escapeHtml(id)}" data-channel="${channel}" data-output-enabled="${String(outputEnabled)}" tabindex="0" draggable="true" aria-selected="${String(selected)}">
      <div class="rd-card__media" title="Double-click to edit">${media}<div class="rd-media-badges"><span class="rd-kind">${item.kind}</span>${duration ? `<span class="rd-duration">${duration}</span>` : ""}</div><span class="rd-media-filename" title="${escapeHtml(mediaFilename)}">${escapeHtml(mediaFilename)}</span><button type="button" class="rd-remove" data-action="remove" aria-label="Remove reference" title="Delete reference">×</button>${loading}</div>
      <div class="rd-card__body">
        ${showCaptionsProperty(this.#node) ? `<textarea data-field="caption" rows="2" maxlength="16384" placeholder="Caption" aria-label="${labelForCaption(channel)} caption">${escapeHtml(caption)}</textarea>` : ""}
        <div class="rd-card__actions">
        ${channel === "image" && item.kind === "image" ? `<button type="button" data-action="toggle-image" class="${imageEnabled ? "is-on" : ""}" aria-label="Toggle image output" aria-pressed="${String(imageEnabled)}">I</button>` : ""}
        ${channel === "video" && item.kind === "video" ? `<button type="button" data-action="toggle-video" class="${videoEnabled ? "is-on" : ""}" aria-label="Toggle video output" aria-pressed="${String(videoEnabled)}">V</button>` : ""}
        ${channel === "audio" && isAudioItem(item) ? `<button type="button" data-action="toggle-audio" class="${audioEnabled ? "is-on" : ""}" aria-label="Toggle audio output" aria-pressed="${String(audioEnabled)}"${silentVideo ? ' disabled title="No embedded audio track"' : ""}>A</button>` : ""}
        ${channel === "video" && item.kind === "video" ? `<button type="button" data-action="preview-video" data-playback-owner="${escapeHtml(playbackOwner)}" class="rd-preview-media${videoPlaybackActive ? " is-playing" : ""}" aria-label="${videoPlaybackActive ? "Stop" : "Play"} video preview with audio" title="${runtime?.loading || playbackDuration === undefined ? "Loading video preview" : videoPlaybackActive ? "Stop video preview" : "Play trimmed video preview with audio"}"${videoPlaybackDisabled ? " disabled" : ""}>${videoPlaybackActive ? "■" : "▶"}</button>` : ""}
        ${channel === "audio" && isAudioItem(item) ? `<button type="button" data-action="preview-audio" data-playback-owner="${escapeHtml(playbackOwner)}" class="rd-preview-media${audioPlaybackActive ? " is-playing" : ""}" aria-label="${audioPlaybackActive ? "Stop" : "Play"} audio preview" title="${silentVideo ? "No embedded audio track" : runtime?.loading || playbackDuration === undefined ? "Loading audio preview" : audioPlaybackActive ? "Stop audio preview" : "Play trimmed audio preview"}"${audioPlaybackDisabled ? " disabled" : ""}>${audioPlaybackActive ? "■" : "▶"}</button>` : ""}
        <button type="button" data-action="move-back" aria-label="Move earlier" title="Move earlier (Alt+ArrowLeft)">←</button><button type="button" data-action="move-forward" aria-label="Move later" title="Move later (Alt+ArrowRight)">→</button>
        <button type="button" data-action="edit">Edit</button>
        </div>
        ${error}
      </div>
    </article>`;
  }

  #mediaMarkup(channel: DirectorChannel, item: MediaItem, runtime: ItemRuntime | undefined): string {
    if ((channel === "image" || channel === "video") && runtime?.previewUrl) {
      return `<img src="${escapeHtml(runtime.previewUrl)}" alt="" draggable="false">`;
    }
    if (channel === "audio" && (item.kind === "audio" || item.kind === "video")) {
      return `<canvas data-waveform-id="${escapeHtml(item.id)}" aria-label="Waveform"></canvas>`;
    }
    return `<div class="rd-placeholder" aria-hidden="true">▧</div>`;
  }

  #drawWaveforms(): void {
    for (const canvas of this.root.querySelectorAll<HTMLCanvasElement>("canvas[data-waveform-id]")) {
      const id = canvas.dataset.waveformId;
      if (id) drawWaveform(canvas, this.#runtime.get(id)?.waveform ?? []);
    }
  }

  #syncPlaybackUi(): void {
    if (this.#destroyed) return;
    const audioSnapshot = this.#audioPreview.snapshot;
    for (const button of this.root.querySelectorAll<HTMLButtonElement>('button[data-action="preview-audio"]')) {
      if (button.disabled) continue;
      const active = button.dataset.playbackOwner === audioSnapshot.owner
        && (audioSnapshot.status === "playing" || audioSnapshot.status === "loading");
      button.textContent = active ? "■" : "▶";
      button.classList.toggle("is-playing", active);
      button.setAttribute("aria-label", `${active ? "Stop" : "Play"} audio preview`);
      button.title = active ? "Stop audio preview" : "Play trimmed audio preview";
    }
    const videoSnapshot = this.#videoPreview.snapshot;
    let activeMedia: HTMLElement | undefined;
    for (const button of this.root.querySelectorAll<HTMLButtonElement>('button[data-action="preview-video"]')) {
      if (button.disabled) continue;
      const active = button.dataset.playbackOwner === videoSnapshot.owner
        && (videoSnapshot.status === "playing" || videoSnapshot.status === "loading");
      button.textContent = active ? "■" : "▶";
      button.classList.toggle("is-playing", active);
      button.setAttribute("aria-label", `${active ? "Stop" : "Play"} video preview with audio`);
      button.title = active ? "Stop video preview" : "Play trimmed video preview with audio";
      if (active) activeMedia = button.closest<HTMLElement>(".rd-card")?.querySelector<HTMLElement>(".rd-card__media") ?? undefined;
    }
    if (activeMedia) {
      activeMedia.querySelector("img")?.classList.add("is-video-poster-hidden");
      if (this.#videoPreview.element.parentElement !== activeMedia) activeMedia.prepend(this.#videoPreview.element);
    } else {
      this.#videoPreview.element.remove();
      for (const poster of this.root.querySelectorAll("img.is-video-poster-hidden")) {
        poster.classList.remove("is-video-poster-hidden");
      }
    }
  }

  #installEvents(): void {
    const signal = this.#destroyController.signal;
    this.root.addEventListener("click", (event) => this.#onClick(event), { signal });
    this.root.addEventListener("dblclick", (event) => this.#onDoubleClick(event), { signal });
    this.root.addEventListener("input", (event) => this.#onInput(event), { signal });
    this.root.addEventListener("change", (event) => this.#onChange(event), { signal });
    this.root.addEventListener("compositionstart", () => (this.#composing = true), { signal });
    this.root.addEventListener("compositionend", () => {
      this.#composing = false;
    }, { signal });
    this.root.addEventListener("focusout", () => {
      setTimeout(() => {
        if (this.#renderPending && !(document.activeElement instanceof HTMLTextAreaElement && this.root.contains(document.activeElement))) {
          this.render();
        }
      }, 0);
    }, { signal });
    this.root.addEventListener("keydown", (event) => this.#onKeydown(event), { signal });
    this.root.addEventListener("pointerdown", (event) => {
      const target = event.target as Element;
      const card = target.closest<HTMLElement>(".rd-card");
      const interactive = target.closest("button, textarea, input, select, a, [contenteditable='true']");
      this.#armedDrag = !interactive && card?.dataset.id && card.dataset.channel
        ? { id: card.dataset.id, channel: card.dataset.channel as DirectorChannel }
        : undefined;
    }, { signal });
    this.root.addEventListener("pointerup", () => {
      if (!this.#drag) this.#armedDrag = undefined;
    }, { signal });
    this.root.addEventListener("dragstart", (event) => this.#onDragStart(event), { signal });
    this.root.addEventListener("dragend", () => {
      this.#clearDropTarget();
      this.#drag = undefined;
      this.#armedDrag = undefined;
      this.root.classList.remove("is-dragging");
    }, { signal });
    this.root.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = event.dataTransfer.files.length ? "copy" : "move";
      this.#updateDropTarget(event);
    }, { signal });
    this.root.addEventListener("dragleave", (event) => {
      const related = event.relatedTarget;
      if (!(related instanceof Node) || !this.root.contains(related)) this.#clearDropTarget();
    }, { signal });
    this.root.addEventListener("drop", (event) => this.#onDrop(event), { signal });
  }

  #onClick(event: MouseEvent): void {
    const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action]");
    if (!button) {
      const card = (event.target as Element).closest<HTMLElement>(".rd-card");
      if (card?.dataset.id && !(event.target instanceof HTMLTextAreaElement)) {
        this.#selectItem(card.dataset.id);
      }
      return;
    }
    const card = button.closest<HTMLElement>(".rd-card");
    const id = card?.dataset.id;
    const channel = card?.dataset.channel as DirectorChannel | undefined;
    switch (button.dataset.action) {
      case "undo":
        this.#recordGraphChange(() => {
          this.#history = undoHistory(this.#history);
        });
        this.#changed(true);
        return;
      case "redo":
        this.#recordGraphChange(() => {
          this.#history = redoHistory(this.#history);
        });
        this.#changed(true);
        return;
      case "remove":
        if (id && this.#audioPreview.snapshot.owner === `grid:${id}`) this.#audioPreview.stop();
        if (id && this.#videoPreview.snapshot.owner === `grid:${id}`) this.#videoPreview.stop();
        if (id) this.#dispatch({ type: "remove", id });
        this.#runtime.delete(id ?? "");
        return;
      case "toggle-image":
        if (id) this.#dispatch({ type: "toggle", id, channel: "image" });
        return;
      case "toggle-video":
        if (id) this.#dispatch({ type: "toggle", id, channel: "video" });
        return;
      case "toggle-audio":
        if (id) this.#dispatch({ type: "toggle", id, channel: "audio" });
        return;
      case "preview-audio":
        if (id) void this.#toggleAudioPreview(id);
        return;
      case "preview-video":
        if (id) void this.#toggleVideoPreview(id);
        return;
      case "move-back":
      case "move-forward":
        if (id && channel) this.#dispatch({ type: "move", id, channel, delta: button.dataset.action === "move-back" ? -1 : 1 });
        return;
      case "edit":
        if (id) void this.#editItem(id, channel);
    }
  }

  #onDoubleClick(event: MouseEvent): void {
    const target = event.target as Element;
    if (target.closest("button, textarea, input, select, a, [contenteditable='true']")) return;
    const media = target.closest<HTMLElement>(".rd-card__media");
    if (!media) return;
    const card = media.closest<HTMLElement>(".rd-card");
    if (card?.dataset.id) {
      void this.#editItem(card.dataset.id, card.dataset.channel as DirectorChannel | undefined);
    }
  }

  #selectItem(id: string): void {
    this.#selectedId = id;
    for (const card of this.root.querySelectorAll<HTMLElement>(".rd-card")) {
      const selected = card.dataset.id === id;
      card.classList.toggle("is-selected", selected);
      card.setAttribute("aria-selected", String(selected));
    }
  }

  async #toggleAudioPreview(id: string): Promise<void> {
    const item = this.state.items[id];
    const runtime = this.#runtime.get(id);
    if (!item || !isAudioItem(item) || runtime?.loading || (item.kind === "video" && runtime?.metadata?.hasAudio === false)) return;
    const duration = runtime?.metadata?.duration ?? item.crop?.end;
    if (duration === undefined) return;
    const owner = `grid:${id}`;
    const snapshot = this.#audioPreview.snapshot;
    if (snapshot.owner === owner && (snapshot.status === "playing" || snapshot.status === "loading")) {
      this.#audioPreview.stop(owner);
      return;
    }
    try {
      this.#videoPreview.stop();
      const url = item.kind === "video"
        ? this.#api.videoPreviewUrl(item.source)
        : this.#api.audioPreviewUrl(item.source);
      await this.#audioPreview.play(owner, url, item.crop ?? { start: 0, end: duration });
    } catch (error) {
      if (this.#destroyed) return;
      this.#status = `${itemFilename(item)}: ${error instanceof Error ? error.message : "Audio preview failed."}`;
      this.render();
    }
  }

  async #toggleVideoPreview(id: string): Promise<void> {
    const item = this.state.items[id];
    const runtime = this.#runtime.get(id);
    if (!item || item.kind !== "video" || runtime?.loading) return;
    const duration = runtime?.metadata?.duration ?? item.crop?.end;
    if (duration === undefined) return;
    const owner = `grid:${id}`;
    const snapshot = this.#videoPreview.snapshot;
    if (snapshot.owner === owner && (snapshot.status === "playing" || snapshot.status === "loading")) {
      this.#videoPreview.stop(owner);
      return;
    }
    try {
      this.#audioPreview.stop();
      await this.#videoPreview.play(
        owner,
        this.#api.videoPreviewUrl(item.source),
        item.crop ?? { start: 0, end: duration },
      );
    } catch (error) {
      if (this.#destroyed) return;
      this.#status = `${itemFilename(item)}: ${error instanceof Error ? error.message : "Video preview failed."}`;
      this.render();
    }
  }

  #onInput(event: Event): void {
    const textarea = event.target;
    if (!(textarea instanceof HTMLTextAreaElement) || textarea.dataset.field !== "caption") return;
    const card = textarea.closest<HTMLElement>(".rd-card");
    const id = card?.dataset.id;
    const channel = card?.dataset.channel as DirectorChannel | undefined;
    if (!id || !channel) return;
    const next = directorReducer(this.state, { type: "set-caption", id, caption: textarea.value, channel });
    if (next === this.state) return;
    this.#recordGraphChange(() => {
      this.#history = commitHistory(this.#history, next, { mergeKey: this.#composing ? `ime:${channel}:${id}` : `caption:${channel}:${id}` });
    });
    this.#syncCaptionFields(id, textarea);
    this.#node.setDirtyCanvas(true, true);
  }

  #syncCaptionFields(id: string, source?: HTMLTextAreaElement): void {
    const item = this.state.items[id];
    if (!item) return;
    for (const textarea of this.root.querySelectorAll<HTMLTextAreaElement>('textarea[data-field="caption"]')) {
      if (textarea === source || document.activeElement === textarea) continue;
      const card = textarea.closest<HTMLElement>(".rd-card");
      if (card?.dataset.id !== id) continue;
      const channel = card.dataset.channel as DirectorChannel | undefined;
      textarea.value = item.kind === "video" && channel === "audio"
        ? item.audioCaptionOverride ?? item.caption
        : item.caption;
    }
  }

  #onChange(event: Event): void {
    const input = event.target;
    if (input instanceof HTMLSelectElement) {
      const field = input.dataset.field;
      if (field === "card-aspect") {
        this.#dispatch({ type: "set-ui", values: { cardAspectRatio: input.value } });
      } else if (field === "waveform-peaks") {
        this.#dispatch({ type: "set-ui", values: { waveformPeaks: Number(input.value) } });
        this.#reloadChannelRuntime("audio");
      }
      return;
    }
    if (!(input instanceof HTMLInputElement) || input.type !== "file") return;
    const files = [...(input.files ?? [])];
    input.value = "";
    void this.#uploadFiles(files);
  }

  #onKeydown(event: KeyboardEvent): void {
    const card = (event.target as Element).closest<HTMLElement>(".rd-card");
    if (event.altKey && card?.dataset.id && card.dataset.channel && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
      const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
      this.#dispatch({ type: "move", id: card.dataset.id, channel: card.dataset.channel as DirectorChannel, delta });
      return;
    }
  }

  #onDragStart(event: DragEvent): void {
    const card = (event.target as Element).closest<HTMLElement>(".rd-card");
    if (
      !card?.dataset.id ||
      !card.dataset.channel ||
      !this.#armedDrag ||
      this.#armedDrag.id !== card.dataset.id ||
      this.#armedDrag.channel !== card.dataset.channel
    ) {
      event.preventDefault();
      return;
    }
    this.#drag = { id: card.dataset.id, channel: card.dataset.channel as DirectorChannel };
    event.dataTransfer?.setData(DRAG_MIME, JSON.stringify(this.#drag));
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
    this.root.classList.add("is-dragging");
  }

  #updateDropTarget(event: DragEvent): void {
    const target = event.target;
    if (!(target instanceof Element) || !this.#drag || (event.dataTransfer?.files.length ?? 0) > 0) {
      this.#clearDropTarget();
      return;
    }
    const zone = target.closest<HTMLElement>("[data-drop-zone]");
    const card = target.closest<HTMLElement>(".rd-card");
    const valid = zone?.dataset.dropZone === this.#drag.channel
      && card?.dataset.channel === this.#drag.channel
      && card.dataset.id !== this.#drag.id;
    this.#setDropTarget(valid ? card : undefined);
  }

  #setDropTarget(card: HTMLElement | undefined): void {
    if (this.#dropTarget === card) return;
    this.#dropTarget?.classList.remove("is-drop-target");
    this.#dropTarget = card;
    this.#dropTarget?.classList.add("is-drop-target");
  }

  #clearDropTarget(): void {
    this.#setDropTarget(undefined);
  }

  #onDrop(event: DragEvent): void {
    event.preventDefault();
    this.#clearDropTarget();
    const files = [...(event.dataTransfer?.files ?? [])];
    if (files.length > 0) {
      void this.#uploadFiles(files);
      return;
    }
    const zone = (event.target as Element).closest<HTMLElement>("[data-drop-zone]");
    const channel = zone?.dataset.dropZone as DirectorChannel | undefined;
    if (!channel || !this.#drag || this.#drag.channel !== channel) return;
    const targetCard = (event.target as Element).closest<HTMLElement>(".rd-card");
    const order = channel === "image"
      ? this.state.imageOrder
      : channel === "video"
        ? this.state.videoOrder
        : this.state.audioOrder;
    const index = targetCard?.dataset.id ? order.indexOf(targetCard.dataset.id) : order.length;
    this.#dispatch({ type: "reorder", channel, id: this.#drag.id, toIndex: Math.max(0, index) });
  }

  async #uploadFiles(files: File[]): Promise<void> {
    const counts = { image: 0, audio: 0, video: 0 };
    for (const item of Object.values(this.state.items)) counts[item.kind] += 1;
    for (const pending of this.#pending.values()) {
      const kind = fileMediaKind(pending.file);
      if (kind) counts[kind] += 1;
    }
    const accepted: File[] = [];
    let skipped = 0;
    for (const file of files) {
      const kind = fileMediaKind(file);
      if (!kind) {
        skipped += 1;
        continue;
      }
      if (counts[kind] >= MEDIA_LIMITS[kind]) {
        skipped += 1;
        continue;
      }
      counts[kind] += 1;
      accepted.push(file);
    }
    if (skipped > 0) this.#status = `${skipped} unsupported or over-limit file${skipped === 1 ? " was" : "s were"} skipped.`;
    if (accepted.length === 0) {
      if (skipped > 0) this.render();
      return;
    }
    await Promise.allSettled(accepted.map((file) => this.#uploadFile(file)));
  }

  #reloadChannelRuntime(channel: DirectorChannel): void {
    const ids = channel === "image"
      ? this.state.imageOrder
      : channel === "video"
        ? this.state.videoOrder
        : this.state.audioOrder;
    for (const id of new Set(ids)) {
      const item = this.state.items[id];
      if (item) void this.#loadRuntime(item);
    }
  }

  #disableSilentVideoAudio(id: string): void {
    if (this.#destroyed) return;
    const disable = (state: DirectorState): DirectorState => {
      const candidate = state.items[id];
      return candidate?.kind === "video" && candidate.audioEnabled
        ? directorReducer(state, { type: "toggle", id, channel: "audio" })
        : state;
    };
    const present = disable(this.#history.present);
    if (present === this.#history.present) return;
    this.#recordGraphChange(() => {
      this.#history = {
        ...this.#history,
        past: this.#history.past.map(disable),
        present,
        future: this.#history.future.map(disable),
      };
    });
    this.#node.setDirtyCanvas(true, true);
  }

  async #uploadFile(file: File): Promise<void> {
    const epoch = this.#runtimeEpoch;
    const stateController = this.#stateController;
    const id = `pending-${globalThis.crypto?.randomUUID?.() ?? Math.random()}`;
    const objectUrl = URL.createObjectURL(file);
    this.#pending.set(id, { id, file, objectUrl });
    this.#status = `Uploading ${file.name}…`;
    this.render();
    try {
      const uploaded = await this.#api.upload(file, stateController.signal);
      if (!this.#isStateRequestCurrent(epoch, stateController)) return;
      const canonicalCount = Object.values(this.state.items).filter(
        (candidate) => candidate.kind === uploaded.kind,
      ).length;
      if (canonicalCount >= MEDIA_LIMITS[uploaded.kind]) {
        this.#status = `${file.name}: the server identified this as ${uploaded.kind}, but that media limit is already full.`;
        return;
      }
      const item = createMediaItem(
        uploaded.kind,
        uploaded.source,
        undefined,
        uploaded.metadata.hasAudio === undefined ? {} : { hasAudio: uploaded.metadata.hasAudio },
      );
      this.#runtime.set(item.id, { loading: true, metadata: uploaded.metadata });
      this.#dispatch({ type: "add", item });
      this.#selectedId = item.id;
      this.#status = `${file.name} added.`;
      await this.#loadRuntime(item);
    } catch (error) {
      if (!this.#isStateRequestCurrent(epoch, stateController)) return;
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        this.#status = `${file.name}: ${error instanceof Error ? error.message : "Upload failed."}`;
      }
    } finally {
      if (this.#pending.get(id)?.objectUrl === objectUrl) this.#pending.delete(id);
      URL.revokeObjectURL(objectUrl);
      if (this.#isStateRequestCurrent(epoch, stateController)) this.render();
    }
  }

  async #loadRuntime(item: MediaItem, options: RuntimeLoadOptions = {}): Promise<void> {
    if (this.#destroyed) return;
    const epoch = this.#runtimeEpoch;
    const stateController = this.#stateController;
    const sequence = ++this.#runtimeSequence;
    this.#runtimeSequences.set(item.id, sequence);
    const current = this.#runtime.get(item.id) ?? { loading: true };
    const { error: _previousError, ...withoutError } = current;
    this.#runtime.set(item.id, { ...withoutError, loading: true });
    if (options.renderStart !== false) this.render();
    const release = await this.#runtimeLimiter.acquire(stateController.signal);
    if (!release) return;
    try {
      if (!this.#isStateRequestCurrent(epoch, stateController) || this.#runtimeSequences.get(item.id) !== sequence || !this.state.items[item.id]) return;
      const metadataPromise = this.#api.metadata(item.source, stateController.signal);
      const proxyPromise = item.kind === "image" || item.kind === "video"
        ? this.#api.imageProxy(item.source, this.state.ui.previewMaxPixels, stateController.signal)
        : undefined;
      const [metadata, proxy] = await Promise.all([metadataPromise, proxyPromise]);
      if (!this.#isStateRequestCurrent(epoch, stateController) || this.#runtimeSequences.get(item.id) !== sequence || !this.state.items[item.id]) return;
      if (item.kind === "video" && metadata.hasAudio === false) this.#disableSilentVideoAudio(item.id);
      const waveform = item.kind === "audio" || (item.kind === "video" && metadata.hasAudio !== false)
        ? await this.#api.waveform(item.source, this.state.ui.waveformPeaks, item.crop, stateController.signal)
        : undefined;
      if (!this.#isStateRequestCurrent(epoch, stateController) || this.#runtimeSequences.get(item.id) !== sequence || !this.state.items[item.id]) return;
      const runtimeMetadata = metadata.duration === undefined && waveform?.duration !== undefined
        ? { ...metadata, duration: waveform.duration }
        : metadata;
      this.#runtime.set(item.id, {
        loading: false,
        metadata: runtimeMetadata,
        ...(proxy ? { previewUrl: proxy.url } : {}),
        ...(waveform ? { waveform: waveform.pairs } : {}),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (!this.#isStateRequestCurrent(epoch, stateController) || this.#runtimeSequences.get(item.id) !== sequence || !this.state.items[item.id]) return;
      this.#runtime.set(item.id, { ...current, loading: false, error: error instanceof Error ? error.message : "Preview failed." });
    } finally {
      release();
    }
    if (options.completionRender === "scheduled") this.#scheduleRender();
    else this.render();
  }

  async #editItem(id: string, channel?: DirectorChannel): Promise<void> {
    const item = this.state.items[id];
    if (!item) return;
    this.#audioPreview.stop();
    this.#videoPreview.stop();
    this.#modalController?.abort();
    const modalController = new AbortController();
    this.#modalController = modalController;
    const runtime = this.#runtime.get(id);
    try {
      if (item.kind === "image") {
        const imageMetadata = runtime?.metadata;
        const editorResult = await openImageEditor({
          item,
          signal: modalController.signal,
          ...(runtime?.previewUrl ? { previewUrl: runtime.previewUrl } : {}),
          ...(imageMetadata?.width !== undefined ? { imageWidth: imageMetadata.width } : {}),
          ...(imageMetadata?.height !== undefined ? { imageHeight: imageMetadata.height } : {}),
          ...(imageMetadata?.width === undefined || imageMetadata.height === undefined
            ? { imageMetadata: (signal: AbortSignal) => this.#api.metadata(item.source, signal) }
            : {}),
          backgroundPreview: async (signal) => (await this.#api.backgroundPreview(item.source, signal)).url,
        });
        if (!editorResult) return;
        if (!this.#isEditCurrent(id, item, modalController)) return;
        if (editorResult.action === "restore-original") {
          this.#invalidateRuntime(id);
          this.#runtime.set(id, { loading: true });
          this.#dispatch({
            type: "restore-image-original",
            id,
            caption: editorResult.caption,
          });
          this.render(true);
          const restored = this.state.items[id];
          if (restored) await this.#loadRuntime(restored);
          return;
        }
        let edit = editorResult.edit;
        if (editorResult.maskFile) {
          const uploadedMask = await this.#api.upload(editorResult.maskFile, modalController.signal);
          if (!this.#isEditCurrent(id, item, modalController)) return;
          if (uploadedMask.kind !== "image") throw new Error("The uploaded mask was not recognized as an image.");
          edit = { ...edit, mask: uploadedMask.source, maskMode: "keep" };
        }
        this.#runtime.set(id, { ...runtime, loading: true });
        this.render();
        const result = await this.#api.applyEdit(item.source, edit, modalController.signal);
        if (!this.#isEditCurrent(id, item, modalController)) return;
        this.#invalidateRuntime(id);
        const canonicalEdit = edit.mask && !result.edit.mask
          ? { ...result.edit, mask: edit.mask, maskMode: "keep" as const }
          : result.edit;
        this.#dispatch({
          type: "apply-image-edit",
          id,
          edit: canonicalEdit,
          source: result.source,
          caption: editorResult.caption,
        });
        this.#runtime.set(id, {
          loading: false,
          ...(result.proxyUrl ? { previewUrl: result.proxyUrl } : runtime?.previewUrl ? { previewUrl: runtime.previewUrl } : {}),
          ...(result.metadata ? { metadata: result.metadata } : runtime?.metadata ? { metadata: runtime.metadata } : {}),
        });
        this.render(true);
      } else {
        let metadata = runtime?.metadata;
        if (metadata?.duration === undefined) metadata = await this.#api.metadata(item.source, modalController.signal);
        if (!this.#isEditCurrent(id, item, modalController)) return;
        let editorWaveform = runtime?.waveform;
        if (item.crop && (item.kind === "audio" || metadata?.hasAudio !== false)) {
          editorWaveform = (await this.#api.waveform(
            item.source,
            this.state.ui.waveformPeaks,
            undefined,
            modalController.signal,
          )).pairs;
        }
        if (!this.#isEditCurrent(id, item, modalController)) return;
        const caption = item.kind === "video" && channel === "audio"
          ? item.audioCaptionOverride ?? item.caption
          : item.caption;
        const editorResult = await openTrimEditor({
          kind: item.kind,
          filename: itemFilename(item),
          duration: metadata?.duration ?? item.crop?.end ?? 1,
          caption,
          signal: modalController.signal,
          playback: {
            player: this.#audioPreview,
            owner: `editor:${id}`,
            url: item.kind === "video"
              ? this.#api.videoPreviewUrl(item.source)
              : this.#api.audioPreviewUrl(item.source),
            enabled: item.kind === "audio" || metadata?.hasAudio !== false,
          },
          ...(item.crop ? { crop: item.crop } : {}),
          ...(editorWaveform ? { waveform: editorWaveform } : {}),
        });
        if (!editorResult) return;
        if (!this.#isEditCurrent(id, item, modalController)) return;
        this.#dispatch({
          type: "apply-time-range",
          id,
          crop: editorResult.crop,
          caption: editorResult.caption,
          ...(channel ? { channel } : {}),
        });
        this.render(true);
        const updated = this.state.items[id];
        if (updated) await this.#loadRuntime(updated);
      }
    } catch (error) {
      if (!this.#isEditCurrent(id, item, modalController)) return;
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        this.#runtime.set(id, { ...runtime, loading: false, error: error instanceof Error ? error.message : "Edit failed." });
        this.render();
      }
    } finally {
      if (this.#modalController === modalController) this.#modalController = undefined;
    }
  }

  #isEditCurrent(id: string, original: MediaItem, controller: AbortController): boolean {
    if (this.#destroyed || controller.signal.aborted || this.#modalController !== controller) return false;
    const current = this.state.items[id];
    return Boolean(
      current &&
      current.kind === original.kind &&
      current.source.path === original.source.path &&
      current.source.sha256 === original.source.sha256 &&
      current.source.revision === original.source.revision,
    );
  }

  #isStateRequestCurrent(epoch: number, controller: AbortController): boolean {
    return !this.#destroyed && !controller.signal.aborted && this.#stateController === controller && this.#runtimeEpoch === epoch;
  }

  #invalidateRuntime(id: string): void {
    this.#runtimeSequences.set(id, ++this.#runtimeSequence);
  }

  #dispatch(action: DirectorAction): void {
    if (this.#destroyed) return;
    const next = directorReducer(this.state, action);
    if (next === this.state) return;
    this.#recordGraphChange(() => {
      this.#history = commitHistory(this.#history, next);
    });
    this.#changed();
  }

  #recordGraphChange(change: () => void): void {
    const graph = this.#node.graph;
    this.#changeEvents.beforeChange?.();
    graph?.beforeChange?.(this.#node);
    try {
      change();
    } finally {
      graph?.afterChange?.(this.#node);
      this.#changeEvents.afterChange?.();
    }
  }

  #changed(reloadRuntime = false): void {
    if (this.#destroyed) return;
    if (this.#selectedId && !this.state.items[this.#selectedId]) this.#selectedId = undefined;
    for (const id of this.#runtime.keys()) {
      if (!this.state.items[id]) {
        this.#runtime.delete(id);
        this.#invalidateRuntime(id);
        this.#runtimeSequences.delete(id);
      }
    }
    this.#node.setDirtyCanvas(true, true);
    this.render();
    if (reloadRuntime) {
      for (const item of Object.values(this.state.items)) void this.#loadRuntime(item);
    }
  }

}

function labelForCaption(channel: DirectorChannel): string {
  return channel === "image" ? "Image" : channel === "video" ? "Video" : "Audio";
}
