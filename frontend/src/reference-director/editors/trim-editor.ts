import { LocalHistory } from "../history";
import type { TimeRange } from "../types";

export interface TrimEditorOptions {
  kind: "audio" | "video";
  duration: number;
  crop?: TimeRange;
  waveform?: ReadonlyArray<readonly [number, number]>;
  signal?: AbortSignal;
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

export function openTrimEditor(options: TrimEditorOptions): Promise<TimeRange | null> {
  return new Promise((resolve) => {
    const duration = Math.max(0.01, options.duration);
    const history = new LocalHistory(options.crop ?? { start: 0, end: duration });
    const dialog = document.createElement("dialog");
    dialog.className = "rd-modal rd-trim-editor";
    dialog.setAttribute("aria-label", `${options.kind} trim editor`);
    dialog.innerHTML = `
      <form method="dialog" class="rd-modal__panel">
        <header><div><strong>${options.kind === "video" ? "Video" : "Audio"} trim</strong><small>No shared timeline; this range affects only this reference.</small></div><button type="button" data-action="cancel" aria-label="Close">×</button></header>
        <canvas aria-label="Waveform preview"></canvas>
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

    const render = (): void => {
      const range = history.value;
      const start = dialog.querySelector<HTMLInputElement>('[data-field="start"]');
      const end = dialog.querySelector<HTMLInputElement>('[data-field="end"]');
      if (start) start.value = range.start.toFixed(2);
      if (end) end.value = range.end.toFixed(2);
      const undo = dialog.querySelector<HTMLButtonElement>('[data-action="undo"]');
      const redo = dialog.querySelector<HTMLButtonElement>('[data-action="redo"]');
      if (undo) undo.disabled = !history.canUndo;
      if (redo) redo.disabled = !history.canRedo;
    };
    const finish = (value: TimeRange | null): void => {
      if (settled) return;
      settled = true;
      options.signal?.removeEventListener("abort", onAbort);
      dialog.remove();
      resolve(value);
    };
    const onAbort = (): void => finish(null);

    dialog.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      const number = Math.max(0, Math.min(duration, Number(target.value)));
      if (!Number.isFinite(number)) return;
      const current = history.value;
      const next = target.dataset.field === "start" ? { ...current, start: number } : { ...current, end: number };
      if (next.end - next.start < 0.01) {
        const error = dialog.querySelector<HTMLElement>(".rd-modal__error");
        if (error) {
          error.hidden = false;
          error.textContent = "The end must be at least 0.01 seconds after the start.";
        }
        render();
        return;
      }
      history.commit(next);
      const error = dialog.querySelector<HTMLElement>(".rd-modal__error");
      if (error) error.hidden = true;
      render();
    });
    dialog.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action]");
      if (!button) return;
      switch (button.dataset.action) {
        case "cancel":
          finish(null);
          break;
        case "undo":
          history.undo();
          render();
          break;
        case "redo":
          history.redo();
          render();
          break;
        case "apply":
          finish(history.value);
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
