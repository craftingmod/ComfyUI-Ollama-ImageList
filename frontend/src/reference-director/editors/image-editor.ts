import { LocalHistory } from "../history";
import type { ImageEditRecipe, ImageItem, NormalizedCrop } from "../types";

export type MaskBrushTool = "erase" | "restore";

export interface ImageEditorDraft {
  crop: NormalizedCrop;
  flipX: boolean;
  flipY: boolean;
  removeBackground: boolean;
  backgroundMode: "transparent" | "solid";
  backgroundColor: string;
  tool: MaskBrushTool;
  brushSize: number;
  brushOpacity: number;
  zoom: number;
  panX: number;
  panY: number;
  maskPixels?: Uint8ClampedArray;
  maskWidth?: number;
  maskHeight?: number;
  maskTouched: boolean;
}

export interface ImageEditorOptions {
  item: ImageItem;
  previewUrl?: string;
  signal?: AbortSignal;
}

export interface ImageEditorResult {
  edit: ImageEditRecipe;
  caption: string;
  maskFile?: File;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character] ?? character);
}

function filename(path: string): string {
  return path.split("/").pop() ?? path;
}

export function updateNormalizedCrop(
  crop: NormalizedCrop,
  field: keyof NormalizedCrop,
  value: number,
): NormalizedCrop {
  if (field === "x") return { ...crop, x: clamp(value, 0, 1 - crop.width) };
  if (field === "y") return { ...crop, y: clamp(value, 0, 1 - crop.height) };
  if (field === "width") return { ...crop, width: clamp(value, 0.01, 1 - crop.x) };
  return { ...crop, height: clamp(value, 0.01, 1 - crop.y) };
}

export function createInitialImageDraft(item: ImageItem): ImageEditorDraft {
  const materialized = item.source.path.startsWith("reference_director/edits/");
  return {
    crop: materialized ? { x: 0, y: 0, width: 1, height: 1 } : item.edit?.crop ?? { x: 0, y: 0, width: 1, height: 1 },
    flipX: materialized ? false : item.edit?.flipX ?? false,
    flipY: materialized ? false : item.edit?.flipY ?? false,
    removeBackground: materialized ? false : item.edit?.removeBackground ?? false,
    backgroundMode: materialized ? "transparent" : item.edit?.background?.mode ?? "transparent",
    backgroundColor: materialized ? "#ffffff" : item.edit?.background?.color ?? "#ffffff",
    tool: "erase",
    brushSize: 48,
    brushOpacity: 1,
    zoom: 1,
    panX: 0,
    panY: 0,
    maskTouched: false,
  };
}

function recipeFromDraft(item: ImageItem, draft: ImageEditorDraft): ImageEditRecipe {
  const materialized = item.source.path.startsWith("reference_director/edits/");
  return {
    crop: draft.crop,
    flipX: draft.flipX,
    flipY: draft.flipY,
    ...(draft.removeBackground ? { removeBackground: true } : {}),
    background: { mode: draft.backgroundMode, color: draft.backgroundColor },
    ...(!materialized && item.edit?.mask ? { mask: item.edit.mask, maskMode: "keep" as const } : {}),
    revision: (item.source.revision ?? item.edit?.revision ?? 0) + 1,
  };
}

export function initialImageEditorRecipe(item: ImageItem): ImageEditRecipe {
  return recipeFromDraft(item, createInitialImageDraft(item));
}

export function applyMaskBrush(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  centerX: number,
  centerY: number,
  radius: number,
  opacity: number,
  tool: MaskBrushTool,
): Uint8ClampedArray {
  const next = new Uint8ClampedArray(pixels);
  const target = tool === "erase" ? 0 : 255;
  const alpha = clamp(opacity, 0, 1);
  const safeRadius = Math.max(0.5, radius);
  const left = Math.max(0, Math.floor(centerX - safeRadius));
  const right = Math.min(width - 1, Math.ceil(centerX + safeRadius));
  const top = Math.max(0, Math.floor(centerY - safeRadius));
  const bottom = Math.min(height - 1, Math.ceil(centerY + safeRadius));
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      if ((x - centerX) ** 2 + (y - centerY) ** 2 > safeRadius ** 2) continue;
      const index = (y * width + x) * 4;
      const current = next[index] ?? 255;
      const value = Math.round(current + (target - current) * alpha);
      next[index] = value;
      next[index + 1] = value;
      next[index + 2] = value;
      next[index + 3] = 255;
    }
  }
  return next;
}

function canvasFile(canvas: HTMLCanvasElement, filename: string): Promise<File> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("The mask canvas could not be encoded."));
        return;
      }
      resolve(new File([blob], filename, { type: "image/png", lastModified: Date.now() }));
    }, "image/png");
  });
}

export function openImageEditor(options: ImageEditorOptions): Promise<ImageEditorResult | null> {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rd-modal rd-image-editor";
    dialog.setAttribute("aria-label", "Image reference editor");
    dialog.innerHTML = `
      <form method="dialog" class="rd-modal__panel">
        <header><div><strong>Image editor</strong><small>Crop, mask, flip, and background changes are non-destructive.</small><small class="rd-modal__filename" title="${escapeHtml(options.item.source.path)}">File: ${escapeHtml(options.item.sourceFilename || filename(options.item.source.path))}</small></div><button type="button" data-action="cancel" aria-label="Close">×</button></header>
        <label class="rd-modal__caption">Caption<textarea data-field="caption" rows="2" maxlength="16384" placeholder="Caption">${escapeHtml(options.item.caption)}</textarea></label>
        <div class="rd-editor-layout">
          <div class="rd-editor-preview"><div class="rd-editor-stage"><img alt="Selected reference preview"><canvas aria-label="Editable keep mask"></canvas></div></div>
          <div class="rd-editor-controls">
            <fieldset><legend>Viewport (preview only)</legend>
              <label>Zoom <input data-field="zoom" type="range" min="0.5" max="3" step="0.05"></label>
              <label>Pan X <input data-field="pan-x" type="range" min="-100" max="100" step="1"></label>
              <label>Pan Y <input data-field="pan-y" type="range" min="-100" max="100" step="1"></label>
              <button type="button" data-action="reset-view">Reset view</button>
            </fieldset>
            <fieldset><legend>Normalized crop</legend>
              <label>X <input data-field="x" type="number" min="0" max="1" step="0.01"></label>
              <label>Y <input data-field="y" type="number" min="0" max="1" step="0.01"></label>
              <label>Width <input data-field="width" type="number" min="0.01" max="1" step="0.01"></label>
              <label>Height <input data-field="height" type="number" min="0.01" max="1" step="0.01"></label>
            </fieldset>
            <fieldset><legend>Keep mask</legend>
              <button type="button" data-action="erase" aria-pressed="true">Erase</button>
              <button type="button" data-action="restore" aria-pressed="false">Restore</button>
              <label>Brush size <input data-field="brush-size" type="range" min="4" max="200" step="1"></label>
              <label>Opacity <input data-field="brush-opacity" type="range" min="0.05" max="1" step="0.05"></label>
            </fieldset>
            <fieldset><legend>Transform</legend>
              <button type="button" data-action="flip-x">Flip horizontal</button>
              <button type="button" data-action="flip-y">Flip vertical</button>
            </fieldset>
            <fieldset><legend>Background</legend>
              <button type="button" class="rd-control-wide" data-action="remove-background" aria-pressed="false">Remove background (rembg)</button>
              <small class="rd-editor-note">Optional server dependency. Runs when you apply the edit; the first run may download a model.</small>
              <select data-field="background-mode"><option value="transparent">Transparent</option><option value="solid">Solid color</option></select>
              <input data-field="background-color" type="color" aria-label="Background color">
            </fieldset>
            <div class="rd-editor-history"><button type="button" data-action="undo">Undo</button><button type="button" data-action="redo">Redo</button></div>
          </div>
        </div>
        <p class="rd-modal__error" role="alert" hidden></p>
        <footer><button type="button" data-action="cancel">Cancel</button><button type="button" class="rd-primary" data-action="apply">Apply</button></footer>
      </form>`;

    const image = dialog.querySelector<HTMLImageElement>("img");
    const stage = dialog.querySelector<HTMLElement>(".rd-editor-stage");
    const maskCanvas = dialog.querySelector<HTMLCanvasElement>("canvas");
    // At most ~20 MiB of 512px RGBA mask snapshots, plus lightweight recipe references.
    const history = new LocalHistory(createInitialImageDraft(options.item), 20);
    let settled = false;
    let painting = false;
    let canvasReady = false;
    let lastPoint: readonly [number, number] | undefined;

    const getInput = (field: string): HTMLInputElement | HTMLSelectElement | null =>
      dialog.querySelector(`[data-field="${field}"]`);

    const initializeCanvas = (): void => {
      if (!maskCanvas || !image) return;
      const naturalWidth = Math.max(1, image.naturalWidth || 1024);
      const naturalHeight = Math.max(1, image.naturalHeight || 1024);
      const scale = Math.min(1, 512 / Math.max(naturalWidth, naturalHeight));
      maskCanvas.width = Math.max(1, Math.round(naturalWidth * scale));
      maskCanvas.height = Math.max(1, Math.round(naturalHeight * scale));
      if (stage) {
        const aspect = naturalWidth / naturalHeight;
        const viewportHeight = Math.max(360, globalThis.innerHeight || 900);
        const maxStageWidth = Math.max(1, Math.min(1024, viewportHeight * 0.65 * aspect));
        stage.style.aspectRatio = `${naturalWidth} / ${naturalHeight}`;
        stage.style.width = `min(100%, ${maxStageWidth}px)`;
      }
      const context = maskCanvas.getContext("2d");
      if (context) {
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
      }
      canvasReady = true;
      maskCanvas.setAttribute("aria-disabled", "false");
    };

    const restoreMask = (draft: ImageEditorDraft): void => {
      if (!maskCanvas) return;
      const context = maskCanvas.getContext("2d");
      if (!context) return;
      if (
        draft.maskPixels &&
        draft.maskWidth === maskCanvas.width &&
        draft.maskHeight === maskCanvas.height &&
        typeof ImageData !== "undefined"
      ) {
        context.putImageData(new ImageData(new Uint8ClampedArray(draft.maskPixels), maskCanvas.width, maskCanvas.height), 0, 0);
      } else {
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
      }
    };

    const render = (): void => {
      const draft = history.value;
      for (const field of ["x", "y", "width", "height"] as const) {
        const input = getInput(field);
        if (input) input.value = String(draft.crop[field]);
      }
      for (const [field, value] of [
        ["zoom", draft.zoom],
        ["pan-x", draft.panX],
        ["pan-y", draft.panY],
        ["brush-size", draft.brushSize],
        ["brush-opacity", draft.brushOpacity],
      ] as const) {
        const input = getInput(field);
        if (input) input.value = String(value);
      }
      const mode = getInput("background-mode");
      const color = getInput("background-color");
      if (mode) mode.value = draft.backgroundMode;
      if (color) {
        color.value = draft.backgroundColor;
        color.toggleAttribute("disabled", draft.backgroundMode !== "solid");
      }
      dialog.querySelector<HTMLButtonElement>('[data-action="erase"]')?.setAttribute("aria-pressed", String(draft.tool === "erase"));
      dialog.querySelector<HTMLButtonElement>('[data-action="restore"]')?.setAttribute("aria-pressed", String(draft.tool === "restore"));
      dialog.querySelector<HTMLButtonElement>('[data-action="remove-background"]')?.setAttribute("aria-pressed", String(draft.removeBackground));
      const clipPath = `inset(${draft.crop.y * 100}% ${(1 - draft.crop.x - draft.crop.width) * 100}% ${(1 - draft.crop.y - draft.crop.height) * 100}% ${draft.crop.x * 100}%)`;
      const transform = `translate(${draft.panX}px, ${draft.panY}px) scale(${draft.zoom}) scaleX(${draft.flipX ? -1 : 1}) scaleY(${draft.flipY ? -1 : 1})`;
      if (stage) stage.style.background = draft.backgroundMode === "solid" ? draft.backgroundColor : "repeating-conic-gradient(#666 0 25%, #888 0 50%) 0 / 18px 18px";
      if (image) {
        image.style.transform = transform;
        image.style.clipPath = clipPath;
      }
      if (maskCanvas) {
        maskCanvas.style.transform = transform;
        maskCanvas.style.clipPath = clipPath;
        restoreMask(draft);
      }
      const undo = dialog.querySelector<HTMLButtonElement>('[data-action="undo"]');
      const redo = dialog.querySelector<HTMLButtonElement>('[data-action="redo"]');
      if (undo) undo.disabled = !history.canUndo;
      if (redo) redo.disabled = !history.canRedo;
    };

    const finish = (value: ImageEditorResult | null): void => {
      if (settled) return;
      settled = true;
      options.signal?.removeEventListener("abort", onAbort);
      dialog.remove();
      resolve(value);
    };
    const onAbort = (): void => finish(null);

    const commitMask = (): void => {
      if (!maskCanvas) return;
      const context = maskCanvas.getContext("2d");
      if (!context) return;
      const snapshot = context.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
      history.commit({
        ...history.value,
        maskPixels: new Uint8ClampedArray(snapshot.data),
        maskWidth: maskCanvas.width,
        maskHeight: maskCanvas.height,
        maskTouched: true,
      });
      render();
    };

    const canvasPoint = (event: PointerEvent): readonly [number, number] | undefined => {
      if (!maskCanvas) return undefined;
      const rect = maskCanvas.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return undefined;
      let x = ((event.clientX - rect.left) / rect.width) * maskCanvas.width;
      let y = ((event.clientY - rect.top) / rect.height) * maskCanvas.height;
      if (history.value.flipX) x = maskCanvas.width - x;
      if (history.value.flipY) y = maskCanvas.height - y;
      return [x, y];
    };

    const paint = (from: readonly [number, number], to: readonly [number, number]): void => {
      if (!maskCanvas) return;
      const context = maskCanvas.getContext("2d");
      if (!context) return;
      const draft = history.value;
      const rect = maskCanvas.getBoundingClientRect();
      const canvasScale = maskCanvas.width / Math.max(1, rect.width);
      context.save();
      context.strokeStyle = draft.tool === "erase" ? "#000000" : "#ffffff";
      context.globalAlpha = draft.brushOpacity;
      context.lineWidth = draft.brushSize * canvasScale;
      context.lineCap = "round";
      context.lineJoin = "round";
      context.beginPath();
      if (from[0] === to[0] && from[1] === to[1]) {
        context.fillStyle = context.strokeStyle;
        context.arc(from[0], from[1], context.lineWidth / 2, 0, Math.PI * 2);
        context.fill();
      } else {
        context.moveTo(from[0], from[1]);
        context.lineTo(to[0], to[1]);
        context.stroke();
      }
      context.restore();
    };

    maskCanvas?.addEventListener("pointerdown", (event) => {
      if (!canvasReady) return;
      const point = canvasPoint(event);
      if (!point) return;
      event.preventDefault();
      painting = true;
      lastPoint = point;
      maskCanvas.setPointerCapture?.(event.pointerId);
      paint(point, point);
    });
    maskCanvas?.addEventListener("pointermove", (event) => {
      if (!painting || !lastPoint) return;
      const point = canvasPoint(event);
      if (!point) return;
      paint(lastPoint, point);
      lastPoint = point;
    });
    const stopPainting = (): void => {
      if (!painting) return;
      painting = false;
      lastPoint = undefined;
      commitMask();
    };
    maskCanvas?.addEventListener("pointerup", stopPainting);
    maskCanvas?.addEventListener("pointercancel", stopPainting);

    dialog.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      const draft = history.value;
      if (action === "cancel") finish(null);
      else if (action === "undo") {
        history.undo();
        render();
      } else if (action === "redo") {
        history.redo();
        render();
      } else if (action === "flip-x") {
        history.commit({ ...draft, flipX: !draft.flipX });
        render();
      } else if (action === "flip-y") {
        history.commit({ ...draft, flipY: !draft.flipY });
        render();
      } else if (action === "remove-background") {
        history.commit({ ...draft, removeBackground: !draft.removeBackground });
        render();
      } else if (action === "erase" || action === "restore") {
        history.commit({ ...draft, tool: action });
        render();
      } else if (action === "reset-view") {
        history.commit({ ...draft, zoom: 1, panX: 0, panY: 0 });
        render();
      } else if (action === "apply") {
        button.disabled = true;
        void (async () => {
          try {
            const edit = recipeFromDraft(options.item, history.value);
            const maskFile = history.value.maskTouched && maskCanvas
              ? await canvasFile(maskCanvas, `${options.item.id}-mask.png`)
              : undefined;
            const caption = dialog.querySelector<HTMLTextAreaElement>('textarea[data-field="caption"]')?.value.slice(0, 16_384) ?? options.item.caption;
            finish({ edit, caption, ...(maskFile ? { maskFile } : {}) });
          } catch (error) {
            button.disabled = false;
            const message = dialog.querySelector<HTMLElement>(".rd-modal__error");
            if (message) {
              message.hidden = false;
              message.textContent = error instanceof Error ? error.message : "The mask could not be prepared.";
            }
          }
        })();
      }
    });

    dialog.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      const value = Number(target.value);
      if (!Number.isFinite(value)) return;
      const draft = history.value;
      if (target.dataset.field === "zoom") history.commit({ ...draft, zoom: clamp(value, 0.5, 3) });
      else if (target.dataset.field === "pan-x") history.commit({ ...draft, panX: clamp(value, -100, 100) });
      else if (target.dataset.field === "pan-y") history.commit({ ...draft, panY: clamp(value, -100, 100) });
      else if (target.dataset.field === "brush-size") history.commit({ ...draft, brushSize: clamp(value, 4, 200) });
      else if (target.dataset.field === "brush-opacity") history.commit({ ...draft, brushOpacity: clamp(value, 0.05, 1) });
      else return;
      render();
    });

    dialog.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
      const field = target.dataset.field;
      const draft = history.value;
      if (field === "background-mode" && (target.value === "solid" || target.value === "transparent")) {
        history.commit({ ...draft, backgroundMode: target.value });
      } else if (field === "background-color" && /^#[\da-f]{6}$/i.test(target.value)) {
        history.commit({ ...draft, backgroundColor: target.value });
      } else if (field === "x" || field === "y" || field === "width" || field === "height") {
        const number = Number(target.value);
        if (!Number.isFinite(number)) return;
        history.commit({ ...draft, crop: updateNormalizedCrop(draft.crop, field, number) });
      }
      render();
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      finish(null);
    });
    options.signal?.addEventListener("abort", onAbort, { once: true });
    if (image && options.previewUrl) {
      maskCanvas?.setAttribute("aria-disabled", "true");
      image.addEventListener("load", () => {
        initializeCanvas();
        render();
      }, { once: true });
      image.src = options.previewUrl;
    } else {
      initializeCanvas();
    }
    document.body.append(dialog);
    render();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });
}
