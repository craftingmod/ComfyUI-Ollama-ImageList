import type { ComfyNode } from "../../comfyui";
import { ReferenceDirectorApi } from "../api";
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
  isVisualItem,
  type DirectorState,
  type ItemRuntime,
  type MediaItem,
} from "../types";

interface PendingUpload {
  id: string;
  file: File;
  objectUrl: string;
}

export interface DirectorChangeEvents {
  beforeChange?(): void;
  afterChange?(): void;
}

const DRAG_MIME = "application/x-reference-director-item";
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
  #pending = new Map<string, PendingUpload>();
  #selectedId: string | undefined;
  #status = "Drop image, audio, or video files to begin.";
  #destroyController = new AbortController();
  #stateController = new AbortController();
  #modalController: AbortController | undefined;
  #drag: { id: string; channel: DirectorChannel } | undefined;
  #armedDrag: { id: string; channel: DirectorChannel } | undefined;
  #composing = false;
  #renderPending = false;
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
    this.render();
    for (const item of Object.values(this.state.items)) void this.#loadRuntime(item);
  }

  get state(): DirectorState {
    return this.#history.present;
  }

  restore(serialized: unknown): void {
    if (this.#destroyed) return;
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
    this.render(true);
    for (const item of Object.values(this.state.items)) void this.#loadRuntime(item);
  }

  serialize(): string {
    return serializeDirectorState(this.state);
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.#destroyed = true;
    this.#modalController?.abort();
    this.#stateController.abort();
    this.#destroyController.abort();
    for (const pending of this.#pending.values()) URL.revokeObjectURL(pending.objectUrl);
    this.#pending.clear();
    this.#runtime.clear();
    this.#runtimeSequences.clear();
    this.root.replaceChildren();
  }

  render(force = false): void {
    if (this.#destroyed) return;
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
    this.root.innerHTML = `
      <section class="rd-toolbar" aria-label="Reference Director toolbar">
        <label class="rd-primary rd-file-button">Add media<input type="file" accept="image/*,audio/*,video/*" multiple></label>
        <button type="button" data-action="undo" ${canUndo(this.#history) ? "" : "disabled"} title="Undo (Ctrl+Z)">↶ Undo</button>
        <button type="button" data-action="redo" ${canRedo(this.#history) ? "" : "disabled"} title="Redo (Ctrl+Shift+Z)">↷ Redo</button>
        <span class="rd-toolbar__count">${Object.keys(state.items).length} reference${Object.keys(state.items).length === 1 ? "" : "s"}</span>
      </section>
      <details class="rd-settings"><summary>Display settings</summary><div>
        <label>Card aspect<select data-field="card-aspect"><option value="1 / 1"${state.ui.cardAspectRatio === "1 / 1" ? " selected" : ""}>1:1</option><option value="4 / 3"${state.ui.cardAspectRatio === "4 / 3" ? " selected" : ""}>4:3</option><option value="16 / 9"${state.ui.cardAspectRatio === "16 / 9" ? " selected" : ""}>16:9</option></select></label>
        <label>Preview pixels<select data-field="preview-pixels"><option value="262144"${state.ui.previewMaxPixels === 262_144 ? " selected" : ""}>0.25 MP</option><option value="1000000"${state.ui.previewMaxPixels === 1_000_000 ? " selected" : ""}>1 MP</option><option value="2000000"${state.ui.previewMaxPixels === 2_000_000 ? " selected" : ""}>2 MP</option><option value="4000000"${state.ui.previewMaxPixels === 4_000_000 ? " selected" : ""}>4 MP</option></select></label>
        <label>Waveform pairs<select data-field="waveform-peaks"><option value="200"${state.ui.waveformPeaks === 200 ? " selected" : ""}>200</option><option value="300"${state.ui.waveformPeaks === 300 ? " selected" : ""}>300</option><option value="500"${state.ui.waveformPeaks === 500 ? " selected" : ""}>500</option></select></label>
      </div></details>
      <p class="rd-status" role="status">${escapeHtml(this.#status)}</p>
      ${this.#pendingMarkup()}
      <div class="rd-channels">
        ${this.#channelMarkup("visual", "Visual", state.visualOrder)}
        ${this.#channelMarkup("audio", "Audio", state.audioOrder)}
      </div>`;
    this.#drawWaveforms();
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
    return `<section class="rd-channel" data-channel="${channel}" aria-label="${label} references">
      <header><div><strong>${label}</strong><span>${order.length}</span></div><small>${channel === "visual" ? "Images and video" : "Audio and video sound"}</small></header>
      <div class="rd-card-grid" data-drop-zone="${channel}">${cards || `<div class="rd-empty">Drop ${channel} references here</div>`}</div>
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
    const visualEnabled = isVisualItem(item) ? item.visualEnabled : false;
    const silentVideo = item.kind === "video" && runtime?.metadata?.hasAudio === false;
    const audioEnabled = isAudioItem(item) ? item.audioEnabled : false;
    return `<article class="rd-card${selected ? " is-selected" : ""}${runtime?.error ? " has-error" : ""}" data-id="${escapeHtml(id)}" data-channel="${channel}" tabindex="0" draggable="true" aria-selected="${String(selected)}">
      <div class="rd-card__media" title="Double-click to edit">${media}<span class="rd-kind">${item.kind}</span>${durationLabel(item, runtime) ? `<span class="rd-duration">${durationLabel(item, runtime)}</span>` : ""}${loading}</div>
      <div class="rd-card__body">
        <div class="rd-card__title"><span title="${escapeHtml(item.source.path)}">${escapeHtml(filename(item.source.path))}</span><button type="button" class="rd-remove" data-action="remove" aria-label="Remove reference" title="Delete reference">×</button></div>
        <textarea data-field="caption" rows="2" maxlength="16384" placeholder="Caption" aria-label="${labelForCaption(channel)} caption">${escapeHtml(caption)}</textarea>
        <div class="rd-card__actions">
          ${isVisualItem(item) ? `<button type="button" data-action="toggle-visual" class="${visualEnabled ? "is-on" : ""}" aria-pressed="${String(visualEnabled)}">V</button>` : ""}
          ${isAudioItem(item) ? `<button type="button" data-action="toggle-audio" class="${audioEnabled ? "is-on" : ""}" aria-pressed="${String(audioEnabled)}"${silentVideo ? ' disabled title="No embedded audio track"' : ""}>A</button>` : ""}
          <button type="button" data-action="move-back" title="Move earlier (Alt+ArrowLeft)">←</button><button type="button" data-action="move-forward" title="Move later (Alt+ArrowRight)">→</button>
          <button type="button" data-action="edit">Edit</button>
        </div>${error}
      </div>
    </article>`;
  }

  #mediaMarkup(channel: DirectorChannel, item: MediaItem, runtime: ItemRuntime | undefined): string {
    if (channel === "visual" && (item.kind === "image" || item.kind === "video") && runtime?.previewUrl) {
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
      this.#drag = undefined;
      this.#armedDrag = undefined;
      this.root.classList.remove("is-dragging");
    }, { signal });
    this.root.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = event.dataTransfer.files.length ? "copy" : "move";
    }, { signal });
    this.root.addEventListener("drop", (event) => this.#onDrop(event), { signal });
  }

  #onClick(event: MouseEvent): void {
    const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action]");
    if (!button) {
      const card = (event.target as Element).closest<HTMLElement>(".rd-card");
      if (card?.dataset.id && !(event.target instanceof HTMLTextAreaElement)) {
        this.#selectedId = card.dataset.id;
        this.render();
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
        if (id) this.#dispatch({ type: "remove", id });
        this.#runtime.delete(id ?? "");
        return;
      case "toggle-visual":
        if (id) this.#dispatch({ type: "toggle", id, channel: "visual" });
        return;
      case "toggle-audio":
        if (id) this.#dispatch({ type: "toggle", id, channel: "audio" });
        return;
      case "move-back":
      case "move-forward":
        if (id && channel) this.#dispatch({ type: "move", id, channel, delta: button.dataset.action === "move-back" ? -1 : 1 });
        return;
      case "edit":
        if (id) void this.#editItem(id);
    }
  }

  #onDoubleClick(event: MouseEvent): void {
    const card = (event.target as Element).closest<HTMLElement>(".rd-card");
    if (card?.dataset.id && !(event.target instanceof HTMLTextAreaElement)) void this.#editItem(card.dataset.id);
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
    this.#node.setDirtyCanvas(true, true);
  }

  #onChange(event: Event): void {
    const input = event.target;
    if (input instanceof HTMLSelectElement) {
      const field = input.dataset.field;
      if (field === "card-aspect") {
        this.#dispatch({ type: "set-ui", values: { cardAspectRatio: input.value } });
      } else if (field === "preview-pixels") {
        this.#dispatch({ type: "set-ui", values: { previewMaxPixels: Number(input.value) } });
        this.#reloadChannelRuntime("visual");
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

  #onDrop(event: DragEvent): void {
    event.preventDefault();
    const files = [...(event.dataTransfer?.files ?? [])];
    if (files.length > 0) {
      void this.#uploadFiles(files);
      return;
    }
    const zone = (event.target as Element).closest<HTMLElement>("[data-drop-zone]");
    const channel = zone?.dataset.dropZone as DirectorChannel | undefined;
    if (!channel || !this.#drag || this.#drag.channel !== channel) return;
    const targetCard = (event.target as Element).closest<HTMLElement>(".rd-card");
    const order = channel === "visual" ? this.state.visualOrder : this.state.audioOrder;
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
    const ids = channel === "visual" ? this.state.visualOrder : this.state.audioOrder;
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

  async #loadRuntime(item: MediaItem): Promise<void> {
    if (this.#destroyed) return;
    const epoch = this.#runtimeEpoch;
    const stateController = this.#stateController;
    const sequence = ++this.#runtimeSequence;
    this.#runtimeSequences.set(item.id, sequence);
    const current = this.#runtime.get(item.id) ?? { loading: true };
    const { error: _previousError, ...withoutError } = current;
    this.#runtime.set(item.id, { ...withoutError, loading: true });
    this.render();
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
    this.render();
  }

  async #editItem(id: string): Promise<void> {
    const item = this.state.items[id];
    if (!item) return;
    this.#modalController?.abort();
    const modalController = new AbortController();
    this.#modalController = modalController;
    const runtime = this.#runtime.get(id);
    try {
      if (item.kind === "image") {
        const editorResult = await openImageEditor({
          item,
          signal: modalController.signal,
          ...(runtime?.previewUrl ? { previewUrl: runtime.previewUrl } : {}),
        });
        if (!editorResult) return;
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
        this.#dispatch({ type: "apply-image-edit", id, edit: canonicalEdit, source: result.source });
        this.#runtime.set(id, {
          loading: false,
          ...(result.proxyUrl ? { previewUrl: result.proxyUrl } : runtime?.previewUrl ? { previewUrl: runtime.previewUrl } : {}),
          ...(result.metadata ? { metadata: result.metadata } : runtime?.metadata ? { metadata: runtime.metadata } : {}),
        });
        this.render();
      } else {
        let metadata = runtime?.metadata;
        if (metadata?.duration === undefined) metadata = await this.#api.metadata(item.source, modalController.signal);
        if (!this.#isEditCurrent(id, item, modalController)) return;
        const crop = await openTrimEditor({
          kind: item.kind,
          duration: metadata?.duration ?? item.crop?.end ?? 1,
          signal: modalController.signal,
          ...(item.crop ? { crop: item.crop } : {}),
          ...(runtime?.waveform ? { waveform: runtime.waveform } : {}),
        });
        if (!crop) return;
        if (!this.#isEditCurrent(id, item, modalController)) return;
        this.#dispatch({ type: "apply-time-range", id, crop });
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
  return channel === "visual" ? "Visual" : "Audio";
}
