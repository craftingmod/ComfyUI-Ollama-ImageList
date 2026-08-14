import { LocalHistory } from "../history";
import type { ImageEditRecipe, ImageItem, NormalizedCrop } from "../types";

export type MaskBrushTool = "erase" | "restore";
export type CropHandle = "north-west" | "north-east" | "south-west" | "south-east";

export interface ImageEditorDraft {
  crop: NormalizedCrop;
  cropFrame: NormalizedCrop;
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
  imageWidth?: number;
  imageHeight?: number;
  imageMetadata?: (signal: AbortSignal) => Promise<{ width?: number; height?: number }>;
  backgroundPreview?: (signal: AbortSignal) => Promise<string>;
  signal?: AbortSignal;
}

export interface AppliedImageEditorResult {
  action: "apply";
  edit: ImageEditRecipe;
  caption: string;
  maskFile?: File;
}

export interface RestoredImageEditorResult {
  action: "restore-original";
  caption: string;
}

export type ImageEditorResult = AppliedImageEditorResult | RestoredImageEditorResult;

export interface PixelCrop {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CropViewport {
  zoom: number;
  panX: number;
  panY: number;
  flipX: boolean;
  flipY: boolean;
}

export interface ViewportPanBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

const FULL_STAGE_FRAME: NormalizedCrop = { x: 0, y: 0, width: 1, height: 1 };

export function viewportPanBounds(
  frame: NormalizedCrop,
  zoom: number,
  viewportWidth: number,
  viewportHeight: number,
): ViewportPanBounds {
  const safeZoom = Math.max(1, zoom);
  const width = Math.max(1, viewportWidth);
  const height = Math.max(1, viewportHeight);
  return {
    minX: (frame.x + frame.width - 0.5 - safeZoom / 2) * width,
    maxX: (frame.x - 0.5 + safeZoom / 2) * width,
    minY: (frame.y + frame.height - 0.5 - safeZoom / 2) * height,
    maxY: (frame.y - 0.5 + safeZoom / 2) * height,
  };
}

export function constrainCropViewport(
  frame: NormalizedCrop,
  viewport: Pick<ImageEditorDraft, "zoom" | "panX" | "panY">,
  viewportWidth: number,
  viewportHeight: number,
): Pick<ImageEditorDraft, "zoom" | "panX" | "panY"> {
  const zoom = clamp(viewport.zoom, 1, 3);
  const bounds = viewportPanBounds(frame, zoom, viewportWidth, viewportHeight);
  return {
    zoom,
    panX: clamp(viewport.panX, bounds.minX, bounds.maxX),
    panY: clamp(viewport.panY, bounds.minY, bounds.maxY),
  };
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

export function resizeNormalizedCrop(
  crop: NormalizedCrop,
  handle: CropHandle,
  deltaX: number,
  deltaY: number,
): NormalizedCrop {
  const minimumSize = 0.01;
  let left = crop.x;
  let top = crop.y;
  let right = crop.x + crop.width;
  let bottom = crop.y + crop.height;
  if (handle.endsWith("west")) left = clamp(left + deltaX, 0, right - minimumSize);
  else right = clamp(right + deltaX, left + minimumSize, 1);
  if (handle.startsWith("north")) top = clamp(top + deltaY, 0, bottom - minimumSize);
  else bottom = clamp(bottom + deltaY, top + minimumSize, 1);
  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function moveNormalizedCrop(
  crop: NormalizedCrop,
  deltaX: number,
  deltaY: number,
): NormalizedCrop {
  return {
    ...crop,
    x: clamp(crop.x + deltaX, 0, 1 - crop.width),
    y: clamp(crop.y + deltaY, 0, 1 - crop.height),
  };
}

function viewportCoordinate(value: number, zoom: number, pan: number, flipped: boolean): number {
  const oriented = flipped ? 1 - value : value;
  return 0.5 + (oriented - 0.5) * zoom + pan;
}

function sourceCoordinate(value: number, zoom: number, pan: number, flipped: boolean): number {
  const oriented = (value - 0.5 - pan) / zoom + 0.5;
  return flipped ? 1 - oriented : oriented;
}

export function projectCropToViewport(crop: NormalizedCrop, viewport: CropViewport): NormalizedCrop {
  const x1 = viewportCoordinate(crop.x, viewport.zoom, viewport.panX, viewport.flipX);
  const x2 = viewportCoordinate(crop.x + crop.width, viewport.zoom, viewport.panX, viewport.flipX);
  const y1 = viewportCoordinate(crop.y, viewport.zoom, viewport.panY, viewport.flipY);
  const y2 = viewportCoordinate(crop.y + crop.height, viewport.zoom, viewport.panY, viewport.flipY);
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1),
  };
}

export function unprojectCropFromViewport(crop: NormalizedCrop, viewport: CropViewport): NormalizedCrop {
  const x1 = sourceCoordinate(crop.x, viewport.zoom, viewport.panX, viewport.flipX);
  const x2 = sourceCoordinate(crop.x + crop.width, viewport.zoom, viewport.panX, viewport.flipX);
  const y1 = sourceCoordinate(crop.y, viewport.zoom, viewport.panY, viewport.flipY);
  const y2 = sourceCoordinate(crop.y + crop.height, viewport.zoom, viewport.panY, viewport.flipY);
  const width = clamp(Math.abs(x2 - x1), 1 / 1_000_000, 1);
  const height = clamp(Math.abs(y2 - y1), 1 / 1_000_000, 1);
  return {
    x: clamp(Math.min(x1, x2), 0, 1 - width),
    y: clamp(Math.min(y1, y2), 0, 1 - height),
    width,
    height,
  };
}

export function normalizedCropToPixels(
  crop: NormalizedCrop,
  imageWidth: number,
  imageHeight: number,
): PixelCrop {
  const width = Math.max(1, Math.round(imageWidth));
  const height = Math.max(1, Math.round(imageHeight));
  const left = clamp(Math.round(crop.x * width), 0, width - 1);
  const top = clamp(Math.round(crop.y * height), 0, height - 1);
  const right = clamp(Math.round((crop.x + crop.width) * width), left + 1, width);
  const bottom = clamp(Math.round((crop.y + crop.height) * height), top + 1, height);
  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function pixelCropToNormalized(
  crop: PixelCrop,
  imageWidth: number,
  imageHeight: number,
): NormalizedCrop {
  const width = Math.max(1, Math.round(imageWidth));
  const height = Math.max(1, Math.round(imageHeight));
  const left = clamp(Math.round(crop.x), 0, width - 1);
  const top = clamp(Math.round(crop.y), 0, height - 1);
  const cropWidth = clamp(Math.round(crop.width), 1, width - left);
  const cropHeight = clamp(Math.round(crop.height), 1, height - top);
  return { x: left / width, y: top / height, width: cropWidth / width, height: cropHeight / height };
}

export function updatePixelCrop(
  crop: PixelCrop,
  field: keyof PixelCrop,
  value: number,
  imageWidth: number,
  imageHeight: number,
): PixelCrop {
  const width = Math.max(1, Math.round(imageWidth));
  const height = Math.max(1, Math.round(imageHeight));
  const integer = Math.round(value);
  if (field === "x") return { ...crop, x: clamp(integer, 0, width - crop.width) };
  if (field === "y") return { ...crop, y: clamp(integer, 0, height - crop.height) };
  if (field === "width") return { ...crop, width: clamp(integer, 1, width - crop.x) };
  return { ...crop, height: clamp(integer, 1, height - crop.y) };
}

function isMaterializedEdit(item: ImageItem): boolean {
  return item.source.path !== item.originalSource.path || item.source.sha256 !== item.originalSource.sha256;
}

export function createInitialImageDraft(item: ImageItem): ImageEditorDraft {
  const materialized = isMaterializedEdit(item);
  return {
    crop: materialized ? { x: 0, y: 0, width: 1, height: 1 } : item.edit?.crop ?? { x: 0, y: 0, width: 1, height: 1 },
    cropFrame: materialized ? { x: 0, y: 0, width: 1, height: 1 } : item.edit?.crop ?? { x: 0, y: 0, width: 1, height: 1 },
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
  const materialized = isMaterializedEdit(item);
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
          <div class="rd-editor-preview"><div class="rd-editor-stage"><div class="rd-editor-visual"><img alt="Selected reference preview"><canvas aria-label="Editable keep mask"></canvas></div><div class="rd-crop-overlay" aria-label="Crop viewport; drag inside to move the crop, drag outside or hold Space to pan, and use the mouse wheel to zoom"><button type="button" data-crop-handle="north-west" aria-label="Resize crop from top left"></button><button type="button" data-crop-handle="north-east" aria-label="Resize crop from top right"></button><button type="button" data-crop-handle="south-west" aria-label="Resize crop from bottom left"></button><button type="button" data-crop-handle="south-east" aria-label="Resize crop from bottom right"></button></div></div></div>
          <div class="rd-editor-controls">
            <fieldset class="rd-interaction-modes"><legend>Interaction</legend>
              <button type="button" data-action="mode-view" aria-pressed="false">View</button>
              <button type="button" data-action="mode-crop" aria-pressed="true">Crop</button>
              <button type="button" data-action="mode-mask" aria-pressed="false">Mask</button>
            </fieldset>
            <fieldset><legend>Viewport</legend>
              <label>Zoom <input data-field="zoom" type="range" min="1" max="3" step="0.05"></label>
              <label>Pan X <input data-field="pan-x" type="range" min="-100" max="100" step="1"></label>
              <label>Pan Y <input data-field="pan-y" type="range" min="-100" max="100" step="1"></label>
              <button type="button" data-action="reset-view">Reset view</button>
            </fieldset>
            <fieldset><legend>Crop in source pixels <span data-crop-dimensions></span></legend>
              <label>X <input data-field="x" type="number" min="0" step="1" inputmode="numeric"></label>
              <label>Y <input data-field="y" type="number" min="0" step="1" inputmode="numeric"></label>
              <label>Width <input data-field="width" type="number" min="1" step="1" inputmode="numeric"></label>
              <label>Height <input data-field="height" type="number" min="1" step="1" inputmode="numeric"></label>
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
              <small class="rd-editor-note" data-background-status>Optional server dependency. Click to generate a preview; the first run may download a model.</small>
              <select data-field="background-mode"><option value="transparent">Transparent</option><option value="solid">Solid color</option></select>
              <input data-field="background-color" type="color" aria-label="Background color">
            </fieldset>
            <div class="rd-editor-history"><button type="button" data-action="undo">Undo</button><button type="button" data-action="redo">Redo</button></div>
          </div>
        </div>
        <p class="rd-modal__error" role="alert" hidden></p>
        <footer><button type="button" class="rd-restore-original" data-action="restore-original"${isMaterializedEdit(options.item) ? "" : " hidden"}>Restore original</button><button type="button" data-action="cancel">Cancel</button><button type="button" class="rd-primary" data-action="apply">Apply</button></footer>
      </form>`;

    const image = dialog.querySelector<HTMLImageElement>("img");
    const stage = dialog.querySelector<HTMLElement>(".rd-editor-stage");
    const visual = dialog.querySelector<HTMLElement>(".rd-editor-visual");
    const maskCanvas = dialog.querySelector<HTMLCanvasElement>("canvas");
    const cropOverlay = dialog.querySelector<HTMLElement>(".rd-crop-overlay");
    // At most ~20 MiB of 512px RGBA mask snapshots, plus lightweight recipe references.
    const history = new LocalHistory(createInitialImageDraft(options.item), 20);
    let settled = false;
    let painting = false;
    let canvasReady = false;
    let interactionMode: "view" | "crop" | "mask" = "crop";
    let resolvedImageWidth = options.imageWidth;
    let resolvedImageHeight = options.imageHeight;
    let sourceWidth = Math.max(1, Math.round(resolvedImageWidth ?? 1024));
    let sourceHeight = Math.max(1, Math.round(resolvedImageHeight ?? 1024));
    const metadataController = new AbortController();
    let lastPoint: readonly [number, number] | undefined;
    let backgroundPreviewUrl: string | undefined;
    let backgroundPreviewLoading = false;
    let backgroundPreviewController: AbortController | undefined;
    let wheelMergeSequence = 0;
    let wheelMergeTimer: ReturnType<typeof setTimeout> | undefined;
    let spacePanActive = false;
    let cropDrag: {
      kind: "move" | "resize";
      handle: CropHandle | undefined;
      initialFrame: NormalizedCrop;
      start: readonly [number, number];
      initialDraft: ImageEditorDraft;
      draft: ImageEditorDraft;
    } | undefined;

    const isTextEntryTarget = (target: EventTarget | null): boolean =>
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target instanceof HTMLButtonElement ||
      (target instanceof HTMLElement && target.isContentEditable);

    const setSpacePanActive = (active: boolean): void => {
      spacePanActive = active;
      stage?.classList.toggle("is-space-pan-ready", active);
    };

    const onSpaceKeyDown = (event: KeyboardEvent): void => {
      if (event.code !== "Space" || isTextEntryTarget(event.target)) return;
      event.preventDefault();
      setSpacePanActive(true);
    };

    const onSpaceKeyUp = (event: KeyboardEvent): void => {
      if (event.code !== "Space") return;
      setSpacePanActive(false);
    };

    const onWindowBlur = (): void => setSpacePanActive(false);
    document.addEventListener("keydown", onSpaceKeyDown);
    document.addEventListener("keyup", onSpaceKeyUp);
    globalThis.addEventListener?.("blur", onWindowBlur);
    let panDrag: {
      start: readonly [number, number];
      initialDraft: ImageEditorDraft;
      draft: ImageEditorDraft;
    } | undefined;

    const getInput = (field: string): HTMLInputElement | HTMLSelectElement | null =>
      dialog.querySelector(`[data-field="${field}"]`);

    const initializeCanvas = (): void => {
      if (!maskCanvas || !image) return;
      const naturalWidth = Math.max(1, image.naturalWidth || 1024);
      const naturalHeight = Math.max(1, image.naturalHeight || 1024);
      sourceWidth = Math.max(1, Math.round(resolvedImageWidth ?? naturalWidth));
      sourceHeight = Math.max(1, Math.round(resolvedImageHeight ?? naturalHeight));
      const scale = Math.min(1, 512 / Math.max(naturalWidth, naturalHeight));
      maskCanvas.width = Math.max(1, Math.round(naturalWidth * scale));
      maskCanvas.height = Math.max(1, Math.round(naturalHeight * scale));
      if (stage) {
        const aspect = sourceWidth / sourceHeight;
        const viewportHeight = Math.max(360, globalThis.innerHeight || 900);
        const maxStageWidth = Math.max(1, Math.min(1024, viewportHeight * 0.65 * aspect));
        stage.style.aspectRatio = `${sourceWidth} / ${sourceHeight}`;
        stage.style.width = `min(100%, ${maxStageWidth}px)`;
      }
      const context = maskCanvas.getContext("2d");
      if (context) {
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
      }
      canvasReady = true;
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

    const render = (restoreCanvas = true): void => {
      const draft = panDrag?.draft ?? cropDrag?.draft ?? history.value;
      const crop = draft.crop;
      const cropFrame = draft.cropFrame;
      const pixelCrop = normalizedCropToPixels(crop, sourceWidth, sourceHeight);
      for (const field of ["x", "y", "width", "height"] as const) {
        const input = getInput(field);
        if (input instanceof HTMLInputElement) {
          input.value = String(pixelCrop[field]);
          input.disabled = interactionMode !== "crop";
          input.max = String(
            field === "x"
              ? sourceWidth - pixelCrop.width
              : field === "y"
                ? sourceHeight - pixelCrop.height
                : field === "width"
                  ? sourceWidth - pixelCrop.x
                  : sourceHeight - pixelCrop.y,
          );
        }
      }
      const cropDimensions = dialog.querySelector<HTMLElement>("[data-crop-dimensions]");
      if (cropDimensions) cropDimensions.textContent = `(${sourceWidth} × ${sourceHeight})`;
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
      const stageRect = stage?.getBoundingClientRect();
      const panBounds = viewportPanBounds(
        FULL_STAGE_FRAME,
        draft.zoom,
        Math.max(1, stageRect?.width ?? 1),
        Math.max(1, stageRect?.height ?? 1),
      );
      const panXInput = getInput("pan-x");
      const panYInput = getInput("pan-y");
      if (panXInput instanceof HTMLInputElement) {
        panXInput.min = String(Math.ceil(panBounds.minX));
        panXInput.max = String(Math.floor(panBounds.maxX));
      }
      if (panYInput instanceof HTMLInputElement) {
        panYInput.min = String(Math.ceil(panBounds.minY));
        panYInput.max = String(Math.floor(panBounds.maxY));
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
      dialog.querySelector<HTMLButtonElement>('[data-action="mode-view"]')?.setAttribute("aria-pressed", String(interactionMode === "view"));
      dialog.querySelector<HTMLButtonElement>('[data-action="mode-crop"]')?.setAttribute("aria-pressed", String(interactionMode === "crop"));
      dialog.querySelector<HTMLButtonElement>('[data-action="mode-mask"]')?.setAttribute("aria-pressed", String(interactionMode === "mask"));
      for (const control of dialog.querySelectorAll<HTMLInputElement | HTMLButtonElement>('[data-action="erase"], [data-action="restore"], [data-field="brush-size"], [data-field="brush-opacity"]')) {
        control.disabled = interactionMode !== "mask";
      }
      const removeBackground = dialog.querySelector<HTMLButtonElement>('[data-action="remove-background"]');
      if (removeBackground) {
        removeBackground.setAttribute("aria-pressed", String(draft.removeBackground));
        removeBackground.setAttribute("aria-busy", String(backgroundPreviewLoading));
        removeBackground.textContent = backgroundPreviewLoading
          ? "Cancel rembg preview"
          : draft.removeBackground && backgroundPreviewUrl
            ? "Background removed (previewed)"
            : "Remove background (rembg)";
      }
      const backgroundStatus = dialog.querySelector<HTMLElement>("[data-background-status]");
      if (backgroundStatus) {
        backgroundStatus.textContent = backgroundPreviewLoading
          ? "Generating a full-resolution foreground preview…"
          : draft.removeBackground && backgroundPreviewUrl
            ? "Preview ready. Apply will reuse this cached rembg result."
            : "Optional server dependency. Click to generate a preview; the first run may download a model.";
      }
      const transform = `translate(${draft.panX}px, ${draft.panY}px) scale(${draft.zoom}) scaleX(${draft.flipX ? -1 : 1}) scaleY(${draft.flipY ? -1 : 1})`;
      if (stage) {
        stage.dataset.interactionMode = interactionMode;
        stage.classList.toggle("is-panning", Boolean(panDrag));
        stage.classList.toggle("is-moving-crop", cropDrag?.kind === "move");
        stage.style.background = draft.backgroundMode === "solid" ? draft.backgroundColor : "repeating-conic-gradient(#666 0 25%, #888 0 50%) 0 / 18px 18px";
      }
      if (visual) visual.style.transform = transform;
      if (image) {
        const desiredSource = draft.removeBackground && backgroundPreviewUrl ? backgroundPreviewUrl : options.previewUrl;
        if (desiredSource && image.getAttribute("src") !== desiredSource) image.src = desiredSource;
        else if (!desiredSource && image.hasAttribute("src")) image.removeAttribute("src");
      }
      if (maskCanvas) {
        maskCanvas.setAttribute("aria-disabled", String(!canvasReady || interactionMode !== "mask"));
        if (restoreCanvas) restoreMask(draft);
      }
      if (cropOverlay) {
        cropOverlay.classList.toggle("is-inactive", interactionMode !== "crop");
        cropOverlay.style.left = `${cropFrame.x * 100}%`;
        cropOverlay.style.top = `${cropFrame.y * 100}%`;
        cropOverlay.style.width = `${cropFrame.width * 100}%`;
        cropOverlay.style.height = `${cropFrame.height * 100}%`;
        for (const handle of cropOverlay.querySelectorAll<HTMLButtonElement>("[data-crop-handle]")) {
          handle.disabled = !canvasReady || interactionMode !== "crop";
        }
      }
      const undo = dialog.querySelector<HTMLButtonElement>('[data-action="undo"]');
      const redo = dialog.querySelector<HTMLButtonElement>('[data-action="redo"]');
      const apply = dialog.querySelector<HTMLButtonElement>('[data-action="apply"]');
      if (undo) undo.disabled = !history.canUndo;
      if (redo) redo.disabled = !history.canRedo;
      if (apply) apply.disabled = draft.removeBackground && (!backgroundPreviewUrl || backgroundPreviewLoading);
    };

    const finish = (value: ImageEditorResult | null): void => {
      if (settled) return;
      settled = true;
      backgroundPreviewController?.abort();
      metadataController.abort();
      if (wheelMergeTimer !== undefined) clearTimeout(wheelMergeTimer);
      document.removeEventListener("keydown", onSpaceKeyDown);
      document.removeEventListener("keyup", onSpaceKeyUp);
      globalThis.removeEventListener?.("blur", onWindowBlur);
      options.signal?.removeEventListener("abort", onAbort);
      dialog.remove();
      resolve(value);
    };
    const onAbort = (): void => finish(null);

    const showError = (error: unknown): void => {
      const message = dialog.querySelector<HTMLElement>(".rd-modal__error");
      if (!message) return;
      message.hidden = false;
      message.textContent = error instanceof Error ? error.message : "The background preview could not be created.";
    };

    const clearError = (): void => {
      const message = dialog.querySelector<HTMLElement>(".rd-modal__error");
      if (message) message.hidden = true;
    };

    const cancelBackgroundPreview = (): void => {
      backgroundPreviewController?.abort();
      backgroundPreviewController = undefined;
      backgroundPreviewLoading = false;
    };

    const ensureBackgroundPreview = (): void => {
      if (
        settled ||
        !history.value.removeBackground ||
        backgroundPreviewUrl ||
        backgroundPreviewLoading ||
        !options.backgroundPreview
      ) return;
      clearError();
      const controller = new AbortController();
      backgroundPreviewController = controller;
      backgroundPreviewLoading = true;
      render(false);
      void options.backgroundPreview(controller.signal).then((url) => {
        if (settled || controller.signal.aborted || backgroundPreviewController !== controller) return;
        backgroundPreviewController = undefined;
        backgroundPreviewLoading = false;
        backgroundPreviewUrl = url;
        render(false);
      }).catch((error: unknown) => {
        if (settled || controller.signal.aborted || backgroundPreviewController !== controller) return;
        backgroundPreviewController = undefined;
        backgroundPreviewLoading = false;
        if (history.value.removeBackground && history.canUndo) history.undo();
        showError(error);
        render(false);
      });
    };

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

    const stagePoint = (event: PointerEvent): readonly [number, number] | undefined => {
      if (!stage) return undefined;
      const rect = stage.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return undefined;
      return [
        clamp((event.clientX - rect.left) / rect.width, 0, 1),
        clamp((event.clientY - rect.top) / rect.height, 0, 1),
      ];
    };

    const cropFromFrame = (
      draft: ImageEditorDraft,
      frame: NormalizedCrop = draft.cropFrame,
      viewportValues: Partial<Pick<ImageEditorDraft, "zoom" | "panX" | "panY">> = {},
    ): NormalizedCrop => {
      const rect = stage?.getBoundingClientRect();
      const width = Math.max(1, rect?.width ?? 1);
      const height = Math.max(1, rect?.height ?? 1);
      return unprojectCropFromViewport(frame, {
        zoom: viewportValues.zoom ?? draft.zoom,
        panX: (viewportValues.panX ?? draft.panX) / width,
        panY: (viewportValues.panY ?? draft.panY) / height,
        flipX: draft.flipX,
        flipY: draft.flipY,
      });
    };

    const frameFromCrop = (draft: ImageEditorDraft, crop: NormalizedCrop): NormalizedCrop => {
      const rect = stage?.getBoundingClientRect();
      const width = Math.max(1, rect?.width ?? 1);
      const height = Math.max(1, rect?.height ?? 1);
      return projectCropToViewport(crop, {
        zoom: draft.zoom,
        panX: draft.panX / width,
        panY: draft.panY / height,
        flipX: draft.flipX,
        flipY: draft.flipY,
      });
    };

    const withViewport = (
      draft: ImageEditorDraft,
      values: Partial<Pick<ImageEditorDraft, "zoom" | "panX" | "panY">>,
      frame: NormalizedCrop = draft.cropFrame,
    ): ImageEditorDraft => {
      const rect = stage?.getBoundingClientRect();
      const viewport = constrainCropViewport(
        FULL_STAGE_FRAME,
        {
          zoom: values.zoom ?? draft.zoom,
          panX: values.panX ?? draft.panX,
          panY: values.panY ?? draft.panY,
        },
        Math.max(1, rect?.width ?? 1),
        Math.max(1, rect?.height ?? 1),
      );
      const next = { ...draft, ...viewport, cropFrame: frame };
      return interactionMode === "crop"
        ? { ...next, crop: cropFromFrame(next, frame) }
        : next;
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
      if (!canvasReady || interactionMode !== "mask" || spacePanActive) return;
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

    const beginPan = (event: PointerEvent, captureTarget: HTMLElement, force = false): void => {
      if (!canvasReady || event.button !== 0 || (!force && interactionMode !== "view" && interactionMode !== "crop")) return;
      event.preventDefault();
      event.stopPropagation();
      panDrag = {
        start: [event.clientX, event.clientY],
        initialDraft: history.value,
        draft: history.value,
      };
      captureTarget.setPointerCapture?.(event.pointerId);
      render(false);
    };

    cropOverlay?.addEventListener("pointerdown", (event) => {
      if (!canvasReady || interactionMode !== "crop" || event.button !== 0) return;
      const handleElement = (event.target as Element).closest<HTMLElement>("[data-crop-handle]");
      const handle = handleElement?.dataset.cropHandle as CropHandle | undefined;
      if (spacePanActive) {
        beginPan(event, cropOverlay, true);
        return;
      }
      const start = stagePoint(event);
      if (!start) return;
      event.preventDefault();
      event.stopPropagation();
      cropDrag = {
        kind: handleElement && handle ? "resize" : "move",
        handle,
        initialFrame: history.value.cropFrame,
        start,
        initialDraft: history.value,
        draft: history.value,
      };
      (handleElement ?? cropOverlay).setPointerCapture?.(event.pointerId);
    });

    stage?.addEventListener("pointerdown", (event) => {
      if (interactionMode === "view" || interactionMode === "crop" || spacePanActive) {
        beginPan(event, stage, spacePanActive);
      }
    });

    stage?.addEventListener("pointermove", (event) => {
      if (panDrag) {
        const panX = panDrag.initialDraft.panX + event.clientX - panDrag.start[0];
        const panY = panDrag.initialDraft.panY + event.clientY - panDrag.start[1];
        panDrag.draft = withViewport(panDrag.initialDraft, { panX, panY });
        render(false);
        return;
      }
      if (!cropDrag) return;
      const point = stagePoint(event);
      if (!point) return;
      const deltaX = point[0] - cropDrag.start[0];
      const deltaY = point[1] - cropDrag.start[1];
      const frame = cropDrag.kind === "resize" && cropDrag.handle
        ? resizeNormalizedCrop(cropDrag.initialFrame, cropDrag.handle, deltaX, deltaY)
        : moveNormalizedCrop(cropDrag.initialFrame, deltaX, deltaY);
      cropDrag.draft = withViewport(cropDrag.initialDraft, {}, frame);
      render(false);
    });

    const stopPointerDrag = (commit: boolean): void => {
      const drag = panDrag ?? cropDrag;
      if (!drag) return;
      panDrag = undefined;
      cropDrag = undefined;
      if (commit && drag.draft !== drag.initialDraft) history.commit(drag.draft);
      render();
    };
    stage?.addEventListener("pointerup", () => stopPointerDrag(true));
    stage?.addEventListener("pointercancel", () => stopPointerDrag(false));

    stage?.addEventListener("wheel", (event) => {
      if (!canvasReady) return;
      const rect = stage.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      event.preventDefault();
      const draft = history.value;
      const viewport = {
        zoom: draft.zoom,
        panX: draft.panX / rect.width,
        panY: draft.panY / rect.height,
      };
      const delta = event.deltaMode === WheelEvent.DOM_DELTA_LINE
        ? event.deltaY * 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
          ? event.deltaY * rect.height
          : event.deltaY;
      const zoom = clamp(draft.zoom * Math.exp(-delta * 0.0015), 1, 3);
      if (zoom === draft.zoom) return;
      const anchorX = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const anchorY = clamp((event.clientY - rect.top) / rect.height, 0, 1);
      const ratio = zoom / draft.zoom;
      const panX = (anchorX - 0.5 - (anchorX - 0.5 - viewport.panX) * ratio) * rect.width;
      const panY = (anchorY - 0.5 - (anchorY - 0.5 - viewport.panY) * ratio) * rect.height;
      const next = withViewport(draft, { zoom, panX, panY });
      if (wheelMergeTimer === undefined) wheelMergeSequence += 1;
      else clearTimeout(wheelMergeTimer);
      wheelMergeTimer = setTimeout(() => {
        wheelMergeTimer = undefined;
      }, 250);
      history.commit(next, { mergeKey: `wheel-${interactionMode}-zoom-${wheelMergeSequence}` });
      render(false);
    }, { passive: false });

    dialog.addEventListener("click", (event) => {
      const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      const draft = history.value;
      if (action === "cancel") finish(null);
      else if (action === "restore-original") {
        const caption = dialog.querySelector<HTMLTextAreaElement>('textarea[data-field="caption"]')?.value.slice(0, 16_384) ?? options.item.caption;
        finish({ action: "restore-original", caption });
      } else if (action === "mode-view" || action === "mode-crop" || action === "mode-mask") {
        interactionMode = action === "mode-view" ? "view" : action === "mode-crop" ? "crop" : "mask";
        if (interactionMode === "crop") {
          const crop = pixelCropToNormalized(
            normalizedCropToPixels(cropFromFrame(draft), sourceWidth, sourceHeight),
            sourceWidth,
            sourceHeight,
          );
          if (
            crop.x !== draft.crop.x || crop.y !== draft.crop.y ||
            crop.width !== draft.crop.width || crop.height !== draft.crop.height
          ) history.commit({ ...draft, crop });
        }
        render(false);
      } else if (action === "undo") {
        history.undo();
        if (!history.value.removeBackground) cancelBackgroundPreview();
        render();
        if (history.value.removeBackground) ensureBackgroundPreview();
      } else if (action === "redo") {
        history.redo();
        if (!history.value.removeBackground) cancelBackgroundPreview();
        render();
        if (history.value.removeBackground) ensureBackgroundPreview();
      } else if (action === "flip-x") {
        history.commit({ ...draft, flipX: !draft.flipX });
        render();
      } else if (action === "flip-y") {
        history.commit({ ...draft, flipY: !draft.flipY });
        render();
      } else if (action === "remove-background") {
        if (draft.removeBackground) cancelBackgroundPreview();
        history.commit({ ...draft, removeBackground: !draft.removeBackground });
        render();
        if (!draft.removeBackground) ensureBackgroundPreview();
      } else if (action === "erase" || action === "restore") {
        history.commit({ ...draft, tool: action });
        render();
      } else if (action === "reset-view") {
        history.commit(withViewport(draft, { zoom: 1, panX: 0, panY: 0 }));
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
            finish({ action: "apply", edit, caption, ...(maskFile ? { maskFile } : {}) });
          } catch (error) {
            button.disabled = false;
            showError(error instanceof Error ? error : new Error("The mask could not be prepared."));
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
      if (target.dataset.field === "zoom") history.commit(withViewport(draft, { zoom: clamp(value, 1, 3) }));
      else if (target.dataset.field === "pan-x") history.commit(withViewport(draft, { panX: value }));
      else if (target.dataset.field === "pan-y") history.commit(withViewport(draft, { panY: value }));
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
        const pixelCrop = normalizedCropToPixels(draft.crop, sourceWidth, sourceHeight);
        const nextPixelCrop = updatePixelCrop(pixelCrop, field, number, sourceWidth, sourceHeight);
        const crop = pixelCropToNormalized(nextPixelCrop, sourceWidth, sourceHeight);
        history.commit({ ...draft, crop, cropFrame: frameFromCrop(draft, crop) });
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
    if (options.imageMetadata && (resolvedImageWidth === undefined || resolvedImageHeight === undefined)) {
      void options.imageMetadata(metadataController.signal).then((metadata) => {
        if (settled || metadataController.signal.aborted) return;
        if (metadata.width !== undefined) resolvedImageWidth = metadata.width;
        if (metadata.height !== undefined) resolvedImageHeight = metadata.height;
        sourceWidth = Math.max(1, Math.round(resolvedImageWidth ?? sourceWidth));
        sourceHeight = Math.max(1, Math.round(resolvedImageHeight ?? sourceHeight));
        render(false);
      }).catch(() => undefined);
    }
    if (history.value.removeBackground) ensureBackgroundPreview();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  });
}
