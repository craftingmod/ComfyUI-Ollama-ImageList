import type { AudioPreviewPlayer, AudioPreviewSnapshot } from "../audio-preview-player";
import { LocalHistory } from "../history";
import type { TimeRange } from "../types";

export interface TrimEditorOptions {
  kind: "audio" | "video";
  filename: string;
  duration: number;
  caption: string;
  crop?: TimeRange;
  waveform?: ReadonlyArray<readonly [number, number]>;
  playback?: {
    player: AudioPreviewPlayer;
    owner: string;
    url: string;
    enabled: boolean;
  };
  signal?: AbortSignal;
}

export interface TrimEditorResult {
  crop: TimeRange;
  caption: string;
}

const MIN_RANGE_SECONDS = 0.01;

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character] ?? character);
}

function drawWaveform(canvas: HTMLCanvasElement, pairs: ReadonlyArray<readonly [number, number]>): void {
  const width = 900;
  const height = 180;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#141821";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "#8eb9ff";
  context.lineWidth = 1;
  context.beginPath();
  pairs.forEach(([minimum, maximum], index) => {
    const x = (index / Math.max(1, pairs.length - 1)) * width;
    context.moveTo(x, height / 2 - maximum * height * 0.45);
    context.lineTo(x, height / 2 - minimum * height * 0.45);
  });
  context.stroke();
}

function formatTime(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${(safe % 60).toFixed(2).padStart(5, "0")}`;
}

function sameRange(left: TimeRange, right: TimeRange): boolean {
  return left.start === right.start && left.end === right.end;
}

function clampSeekPosition(range: TimeRange, value: number): number {
  return Math.max(range.start, Math.min(range.end, value));
}

function sliderRange(current: TimeRange, field: "start" | "end", value: number, duration: number): TimeRange {
  if (field === "start") {
    return { ...current, start: Math.max(0, Math.min(current.end - MIN_RANGE_SECONDS, value)) };
  }
  return { ...current, end: Math.min(duration, Math.max(current.start + MIN_RANGE_SECONDS, value)) };
}

export function openTrimEditor(options: TrimEditorOptions): Promise<TrimEditorResult | null> {
  return new Promise((resolve) => {
    const duration = Math.max(MIN_RANGE_SECONDS, options.duration);
    const initialRange = options.crop ?? { start: 0, end: duration };
    const history = new LocalHistory(initialRange);
    let draft = history.value;
    let seekPosition = draft.start;
    let seekTouched = false;
    let wasOwningPlayback = false;
    const dialog = document.createElement("dialog");
    dialog.className = "rd-modal rd-trim-editor";
    dialog.setAttribute("aria-label", `${options.kind} trim editor`);
    dialog.innerHTML = `
      <form method="dialog" class="rd-modal__panel">
        <header><div><strong>${options.kind === "video" ? "Video" : "Audio"} trim</strong><small>No shared timeline; this range affects only this reference.</small><small class="rd-modal__filename">File: ${escapeHtml(options.filename)}</small></div><button type="button" data-action="cancel" aria-label="Close">×</button></header>
        <label class="rd-modal__caption">Caption<textarea data-field="caption" rows="2" maxlength="16384" placeholder="Caption">${escapeHtml(options.caption)}</textarea></label>
        <div class="rd-trim-timeline">
          <canvas aria-label="Waveform preview"></canvas>
          <div class="rd-trim-selection" aria-hidden="true"></div>
          <div class="rd-trim-playhead" aria-hidden="true" hidden></div>
          <input class="rd-trim-range rd-trim-range--start" data-field="range-start" type="range" min="0" max="${duration}" step="0.01" aria-label="Trim start">
          <input class="rd-trim-range rd-trim-range--end" data-field="range-end" type="range" min="0" max="${duration}" step="0.01" aria-label="Trim end">
        </div>
        <label class="rd-trim-seekbar"><span>Seek</span><input data-field="seek" type="range" min="${initialRange.start}" max="${initialRange.end}" step="0.01" value="${initialRange.start}" aria-label="Audio playback position"${options.playback?.enabled ? "" : " disabled"}></label>
        <div class="rd-trim-transport" aria-label="Audio preview controls">
          <button type="button" data-action="playback-toggle" aria-label="Play audio preview"${options.playback?.enabled ? "" : " disabled"}>▶ Play</button>
          <button type="button" data-action="stop" disabled>■ Stop</button>
          <output data-field="playback-time" aria-live="off">${formatTime(initialRange.start)} / ${formatTime(initialRange.end)}</output>
        </div>
        <p class="rd-playback-error" role="alert" hidden></p>
        <div class="rd-trim-fields">
          <label>Start (seconds)<input data-field="start" type="number" min="0" max="${duration}" step="0.01"></label>
          <label>End (seconds)<input data-field="end" type="number" min="0" max="${duration}" step="0.01"></label>
        </div>
        <div class="rd-editor-history"><button type="button" data-action="undo">Undo</button><button type="button" data-action="redo">Redo</button></div>
        <p class="rd-modal__error" role="alert" hidden></p>
        <footer><button type="button" data-action="cancel">Cancel</button><button type="button" class="rd-primary" data-action="apply">Apply</button></footer>
      </form>`;
    const canvas = dialog.querySelector("canvas");
    if (canvas) drawWaveform(canvas, options.waveform ?? []);
    let settled = false;

    const renderTransport = (snapshot?: AudioPreviewSnapshot): void => {
      const ownsPlayback = snapshot?.owner === options.playback?.owner;
      const playing = ownsPlayback && snapshot?.status === "playing";
      const loading = ownsPlayback && snapshot?.status === "loading";
      const paused = ownsPlayback && snapshot?.status === "paused";
      if (ownsPlayback) {
        seekPosition = clampSeekPosition(draft, snapshot?.currentTime ?? seekPosition);
      } else if (wasOwningPlayback && snapshot?.status === "idle") {
        seekPosition = draft.start;
        seekTouched = false;
      }
      wasOwningPlayback = ownsPlayback;
      const playbackToggle = dialog.querySelector<HTMLButtonElement>('[data-action="playback-toggle"]');
      const stop = dialog.querySelector<HTMLButtonElement>('[data-action="stop"]');
      if (playbackToggle) {
        playbackToggle.disabled = !options.playback?.enabled || loading;
        playbackToggle.textContent = loading ? "Loading…" : playing ? "Ⅱ Pause" : paused ? "▶ Resume" : "▶ Play";
        playbackToggle.setAttribute("aria-label", loading
          ? "Loading audio preview"
          : playing
            ? "Pause audio preview"
            : paused
              ? "Resume audio preview"
              : "Play audio preview");
      }
      if (stop) stop.disabled = !(playing || loading || paused);
      const current = seekPosition;
      const seek = dialog.querySelector<HTMLInputElement>('[data-field="seek"]');
      if (seek) {
        seek.min = String(draft.start);
        seek.max = String(draft.end);
        seek.value = String(current);
        seek.disabled = !options.playback?.enabled;
      }
      const output = dialog.querySelector<HTMLOutputElement>('[data-field="playback-time"]');
      if (output) output.value = `${formatTime(current)} / ${formatTime(draft.end)}`;
      const playhead = dialog.querySelector<HTMLElement>(".rd-trim-playhead");
      if (playhead) {
        playhead.hidden = !(playing || loading || paused || seekTouched);
        playhead.style.left = `${(Math.max(0, Math.min(duration, current)) / duration) * 100}%`;
      }
      const playbackError = dialog.querySelector<HTMLElement>(".rd-playback-error");
      if (playbackError && ownsPlayback && snapshot?.error) {
        playbackError.hidden = false;
        playbackError.textContent = snapshot.error;
      }
    };

    const render = (): void => {
      const start = dialog.querySelector<HTMLInputElement>('[data-field="start"]');
      const end = dialog.querySelector<HTMLInputElement>('[data-field="end"]');
      const rangeStart = dialog.querySelector<HTMLInputElement>('[data-field="range-start"]');
      const rangeEnd = dialog.querySelector<HTMLInputElement>('[data-field="range-end"]');
      if (start) start.value = draft.start.toFixed(2);
      if (end) end.value = draft.end.toFixed(2);
      if (rangeStart) {
        rangeStart.value = String(draft.start);
      }
      if (rangeEnd) {
        rangeEnd.value = String(draft.end);
      }
      seekPosition = clampSeekPosition(draft, seekPosition);
      const selection = dialog.querySelector<HTMLElement>(".rd-trim-selection");
      if (selection) {
        selection.style.left = `${(draft.start / duration) * 100}%`;
        selection.style.right = `${(1 - draft.end / duration) * 100}%`;
      }
      const undo = dialog.querySelector<HTMLButtonElement>('[data-action="undo"]');
      const redo = dialog.querySelector<HTMLButtonElement>('[data-action="redo"]');
      if (undo) undo.disabled = !history.canUndo;
      if (redo) redo.disabled = !history.canRedo;
      renderTransport(options.playback?.player.snapshot);
    };

    const unsubscribePlayback = options.playback?.player.subscribe((snapshot) => {
      if (!settled) renderTransport(snapshot);
    });
    const finish = (value: TrimEditorResult | null): void => {
      if (settled) return;
      settled = true;
      options.signal?.removeEventListener("abort", onAbort);
      unsubscribePlayback?.();
      if (options.playback) options.playback.player.stop(options.playback.owner);
      dialog.remove();
      resolve(value);
    };
    const onAbort = (): void => finish(null);
    const showRangeError = (): void => {
      const error = dialog.querySelector<HTMLElement>(".rd-modal__error");
      if (!error) return;
      error.hidden = false;
      error.textContent = "The end must be at least 0.01 seconds after the start.";
    };
    const clearRangeError = (): void => {
      const error = dialog.querySelector<HTMLElement>(".rd-modal__error");
      if (error) error.hidden = true;
    };
    const commitDraft = (): void => {
      if (!sameRange(history.value, draft)) history.commit(draft);
      clearRangeError();
      render();
    };

    dialog.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.dataset.field === "seek") {
        const value = Number(target.value);
        if (!Number.isFinite(value)) return;
        seekPosition = clampSeekPosition(draft, value);
        seekTouched = true;
        if (options.playback) options.playback.player.seek(options.playback.owner, seekPosition);
        renderTransport(options.playback?.player.snapshot);
        return;
      }
      if (target.dataset.field !== "range-start" && target.dataset.field !== "range-end") return;
      const value = Number(target.value);
      if (!Number.isFinite(value)) return;
      draft = sliderRange(draft, target.dataset.field === "range-start" ? "start" : "end", value, duration);
      seekPosition = clampSeekPosition(draft, seekPosition);
      if (options.playback) options.playback.player.setRange(options.playback.owner, draft);
      clearRangeError();
      render();
    });
    dialog.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.dataset.field === "range-start" || target.dataset.field === "range-end") {
        commitDraft();
        return;
      }
      if (target.dataset.field !== "start" && target.dataset.field !== "end") return;
      const number = Math.max(0, Math.min(duration, Number(target.value)));
      if (!Number.isFinite(number)) return;
      const next = target.dataset.field === "start" ? { ...draft, start: number } : { ...draft, end: number };
      if (next.end - next.start < MIN_RANGE_SECONDS) {
        showRangeError();
        render();
        return;
      }
      draft = next;
      seekPosition = clampSeekPosition(draft, seekPosition);
      if (options.playback) options.playback.player.setRange(options.playback.owner, draft);
      commitDraft();
    });
    dialog.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action]");
      if (!button) return;
      switch (button.dataset.action) {
        case "cancel":
          finish(null);
          break;
        case "undo":
          draft = history.undo();
          seekPosition = clampSeekPosition(draft, seekPosition);
          if (options.playback) options.playback.player.setRange(options.playback.owner, draft);
          render();
          break;
        case "redo":
          draft = history.redo();
          seekPosition = clampSeekPosition(draft, seekPosition);
          if (options.playback) options.playback.player.setRange(options.playback.owner, draft);
          render();
          break;
        case "playback-toggle":
          if (options.playback?.enabled) {
            const snapshot = options.playback.player.snapshot;
            if (snapshot.owner === options.playback.owner && snapshot.status === "playing") {
              options.playback.player.pause(options.playback.owner);
              break;
            }
            const playbackError = dialog.querySelector<HTMLElement>(".rd-playback-error");
            if (playbackError) playbackError.hidden = true;
            void options.playback.player.play(
              options.playback.owner,
              options.playback.url,
              draft,
              seekPosition,
            ).catch(() => undefined);
          }
          break;
        case "stop":
          seekPosition = draft.start;
          seekTouched = false;
          if (options.playback) options.playback.player.stop(options.playback.owner);
          renderTransport(options.playback?.player.snapshot);
          break;
        case "apply":
          finish({
            crop: draft,
            caption: dialog.querySelector<HTMLTextAreaElement>('textarea[data-field="caption"]')?.value.slice(0, 16_384) ?? options.caption,
          });
          break;
      }
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      finish(null);
    });
    options.signal?.addEventListener("abort", onAbort, { once: true });
    document.body.append(dialog);
    render();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });
}
