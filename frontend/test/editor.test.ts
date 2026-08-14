import { describe, expect, test } from "bun:test";

import {
  applyMaskBrush,
  constrainCropViewport,
  initialImageEditorRecipe,
  isCropHandleVisible,
  isNormalizedCropFullyVisible,
  isNormalizedCropViewportFilling,
  moveNormalizedCrop,
  normalizedCropToPixels,
  openImageEditor,
  pixelCropToNormalized,
  projectCropToViewport,
  resolveImageEditorPointerIntent,
  resizeNormalizedCrop,
  unprojectCropFromViewport,
  updatePixelCrop,
  viewportPanBounds,
} from "../src/reference-director/editors/image-editor";
import { AudioPreviewPlayer } from "../src/reference-director/audio-preview-player";
import { openTrimEditor } from "../src/reference-director/editors/trim-editor";
import type { ImageItem } from "../src/reference-director/types";

function activateCropMode(): void {
  document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="mode-crop"]')?.click();
}

describe("audio preview timing", () => {
  test("uses elapsed RAF time for 30fps snapshots while checking the trim end every frame", async () => {
    const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
    let nextFrameId = 1;
    const frames = new Map<number, FrameRequestCallback>();
    globalThis.requestAnimationFrame = (callback): number => {
      const id = nextFrameId;
      nextFrameId += 1;
      frames.set(id, callback);
      return id;
    };
    globalThis.cancelAnimationFrame = (id): void => {
      frames.delete(id);
    };
    const runFrame = (timestamp: number): void => {
      const callbacks = [...frames.values()];
      frames.clear();
      for (const callback of callbacks) callback(timestamp);
    };
    const audio = document.createElement("audio");
    Object.defineProperties(audio, {
      load: { configurable: true, value: () => undefined },
      play: { configurable: true, value: async () => undefined },
      pause: { configurable: true, value: () => undefined },
    });
    const player = new AudioPreviewPlayer(audio);
    const snapshots: string[] = [];
    const unsubscribe = player.subscribe((snapshot) => snapshots.push(snapshot.status));
    try {
      await player.play("timing", "/timing.wav", { start: 0, end: 1 });
      const baseline = snapshots.length;
      runFrame(0);
      for (const timestamp of [6.95, 13.9, 20.85, 27.8]) {
        audio.currentTime = timestamp / 100;
        runFrame(timestamp);
      }
      expect(snapshots).toHaveLength(baseline);
      audio.currentTime = 0.35;
      runFrame(34.75);
      expect(snapshots).toHaveLength(baseline + 1);
      expect(snapshots[snapshots.length - 1]).toBe("playing");

      // Boundary detection is evaluated on the next display RAF, not delayed
      // until another 30fps visual snapshot is due.
      audio.currentTime = 1;
      runFrame(41.7);
      expect(snapshots[snapshots.length - 1]).toBe("idle");
      expect(audio.currentTime).toBe(0);
      expect(frames.size).toBe(0);
    } finally {
      unsubscribe();
      player.destroy();
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });
});

describe("image editor revision semantics", () => {
  test("does not reapply crop and flip after the source was materialized", () => {
    const item: ImageItem = {
      id: "edited",
      kind: "image",
      source: {
        path: "reference_director/edits/abc.png",
        mime: "image/png",
        sha256: "a".repeat(64),
      },
      originalSource: {
        path: "reference_director/sources/original.png",
        mime: "image/png",
        sha256: "b".repeat(64),
      },
      caption: "",
      imageEnabled: true,
      edit: {
        crop: { x: 0.2, y: 0.1, width: 0.5, height: 0.6 },
        flipX: true,
        background: { mode: "solid", color: "#ff0000" },
        revision: 2,
      },
    };
    expect(initialImageEditorRecipe(item)).toEqual({
      crop: { x: 0, y: 0, width: 1, height: 1 },
      flipX: false,
      flipY: false,
      background: { mode: "transparent", color: "#ffffff" },
      revision: 3,
    });
  });

  test("erase and restore brushes produce immutable grayscale keep-mask snapshots", () => {
    const white = new Uint8ClampedArray(4 * 5 * 5).fill(255);
    const erased = applyMaskBrush(white, 5, 5, 2, 2, 1.1, 1, "erase");
    const center = (2 * 5 + 2) * 4;
    expect(white[center]).toBe(255);
    expect(erased[center]).toBe(0);
    const restored = applyMaskBrush(erased, 5, 5, 2, 2, 1.1, 0.5, "restore");
    expect(restored[center]).toBeGreaterThan(120);
    expect(restored[center]).toBeLessThan(140);
    expect(restored[center + 3]).toBe(255);
  });

  test("keeps mask painting disabled until the proxy dimensions are loaded", async () => {
    const item: ImageItem = {
      id: "loading",
      kind: "image",
      source: { path: "reference_director/sources/loading.png", mime: "image/png", sha256: "a".repeat(64) },
      originalSource: { path: "reference_director/sources/loading.png", mime: "image/png", sha256: "a".repeat(64) },
      caption: "",
      imageEnabled: true,
    };
    const result = openImageEditor({ item, previewUrl: "/loading.webp" });
    const canvas = document.querySelector<HTMLCanvasElement>(".rd-image-editor canvas");
    const image = document.querySelector<HTMLImageElement>(".rd-image-editor img");
    const caption = document.querySelector<HTMLElement>(".rd-image-editor .rd-modal__caption");
    expect(document.querySelector(".rd-image-editor .rd-modal__filename")?.textContent).toBe("File: loading.png");
    expect(caption?.parentElement?.classList.contains("rd-editor-media-column")).toBe(true);
    expect(caption?.previousElementSibling?.classList.contains("rd-editor-preview")).toBe(true);
    expect(canvas?.getAttribute("aria-disabled")).toBe("true");
    image?.dispatchEvent(new Event("load"));
    expect(canvas?.getAttribute("aria-disabled")).toBe("true");
    expect(document.querySelector('[data-action="mode-view"]')?.getAttribute("aria-pressed")).toBe("true");
    document.querySelector<HTMLButtonElement>('[data-action="mode-mask"]')?.click();
    expect(canvas?.getAttribute("aria-disabled")).toBe("false");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await result).toBeNull();
  });

  test("converts normalized crops to clamped source-pixel integer controls", () => {
    const normalized = { x: 0.25, y: 0.1, width: 0.5, height: 0.6 };
    expect(normalizedCropToPixels(normalized, 4000, 3000)).toEqual({
      x: 1000,
      y: 300,
      width: 2000,
      height: 1800,
    });
    expect(updatePixelCrop({ x: 1000, y: 300, width: 2000, height: 1800 }, "width", 5000.4, 4000, 3000)).toEqual({
      x: 1000,
      y: 300,
      width: 3000,
      height: 1800,
    });
    expect(pixelCropToNormalized({ x: 1000, y: 300, width: 2000, height: 1800 }, 4000, 3000)).toEqual(normalized);
  });

  test("resizes a normalized crop from each corner without crossing its opposite edge", () => {
    const crop = { x: 0.2, y: 0.1, width: 0.5, height: 0.6 };
    const northWest = resizeNormalizedCrop(crop, "north-west", 0.1, 0.2);
    expect(northWest.x).toBeCloseTo(0.3);
    expect(northWest.y).toBeCloseTo(0.3);
    expect(northWest.width).toBeCloseTo(0.4);
    expect(northWest.height).toBeCloseTo(0.4);
    const southEast = resizeNormalizedCrop(crop, "south-east", 0.2, 0.2);
    expect(southEast.width).toBeCloseTo(0.7);
    expect(southEast.height).toBeCloseTo(0.8);
    const northEast = resizeNormalizedCrop(crop, "north-east", 1, -1);
    expect(northEast).toMatchObject({ x: 0.2, y: 0 });
    expect(northEast.width).toBeCloseTo(0.8);
    expect(northEast.height).toBeCloseTo(0.7);
    const southWest = resizeNormalizedCrop(crop, "south-west", 1, 1);
    expect(southWest.width).toBeCloseTo(0.01);
    expect(southWest.height).toBeCloseTo(0.9);
  });

  test("round-trips crop coordinates through a zoomed, panned, and flipped viewport", () => {
    const crop = { x: 0.2, y: 0.1, width: 0.5, height: 0.6 };
    const viewport = { zoom: 1.75, panX: 0.08, panY: -0.04, flipX: true, flipY: false };
    const projected = projectCropToViewport(crop, viewport);
    const restored = unprojectCropFromViewport(projected, viewport);
    expect(restored.x).toBeCloseTo(crop.x);
    expect(restored.y).toBeCloseTo(crop.y);
    expect(restored.width).toBeCloseTo(crop.width);
    expect(restored.height).toBeCloseTo(crop.height);
  });

  test("moves a crop frame without changing its size and clamps it to the stage", () => {
    const crop = { x: 0.2, y: 0.3, width: 0.5, height: 0.4 };
    const moved = moveNormalizedCrop(crop, 0.1, -0.2);
    expect(moved.x).toBeCloseTo(0.3);
    expect(moved.y).toBeCloseTo(0.1);
    expect(moved.width).toBe(0.5);
    expect(moved.height).toBe(0.4);
    expect(moveNormalizedCrop(crop, 10, 10)).toEqual({ x: 0.5, y: 0.6, width: 0.5, height: 0.4 });
  });

  test("detects fully visible crops and only the corners inside the viewport", () => {
    const visible = { x: 0.1, y: 0.2, width: 0.6, height: 0.5 };
    expect(isNormalizedCropFullyVisible(visible)).toBe(true);
    expect(["north-west", "north-east", "south-west", "south-east"].every((handle) =>
      isCropHandleVisible(visible, handle as "north-west" | "north-east" | "south-west" | "south-east"))).toBe(true);

    const clipped = { x: -0.1, y: 0, width: 1, height: 1 };
    expect(isNormalizedCropFullyVisible(clipped)).toBe(false);
    expect(isCropHandleVisible(clipped, "north-west")).toBe(false);
    expect(isCropHandleVisible(clipped, "south-west")).toBe(false);
    expect(isCropHandleVisible(clipped, "north-east")).toBe(true);
    expect(isCropHandleVisible(clipped, "south-east")).toBe(true);
    expect(isNormalizedCropViewportFilling({ x: 0, y: 0, width: 1, height: 1 })).toBe(true);
    expect(isNormalizedCropViewportFilling(visible)).toBe(false);
  });

  test("resolves pointer gestures from one explicit interaction policy", () => {
    const cases = [
      [{ interactionMode: "crop", cropSelection: "focused", surface: "crop-body", ctrlKey: false, viewportFilling: false }, "move-crop"],
      [{ interactionMode: "crop", cropSelection: "focused", surface: "crop-body", ctrlKey: false, viewportFilling: true }, "pan"],
      [{ interactionMode: "crop", cropSelection: "clipped", surface: "crop-body", ctrlKey: false, viewportFilling: false }, "pending-pan"],
      [{ interactionMode: "crop", cropSelection: "unfocused", surface: "crop-body", ctrlKey: false, viewportFilling: false }, "pending-select"],
      [{ interactionMode: "crop", cropSelection: "focused", surface: "stage", ctrlKey: false, viewportFilling: false }, "unfocus-and-pan"],
      [{ interactionMode: "crop", cropSelection: "focused", surface: "crop-handle", ctrlKey: false, viewportFilling: false }, "resize-crop"],
      [{ interactionMode: "mask", cropSelection: "focused", surface: "mask", ctrlKey: false, viewportFilling: false }, "paint-mask"],
      [{ interactionMode: "mask", cropSelection: "focused", surface: "mask", ctrlKey: true, viewportFilling: false }, "pan"],
      [{ interactionMode: "crop", cropSelection: "focused", surface: "crop-handle", ctrlKey: true, viewportFilling: false }, "pan"],
    ] as const;
    for (const [context, expected] of cases) {
      expect(resolveImageEditorPointerIntent(context)).toBe(expected);
    }
  });

  test("constrains pan so a zoomed image always covers the crop viewport", () => {
    expect(viewportPanBounds({ x: 0, y: 0, width: 1, height: 1 }, 1, 100, 80)).toEqual({
      minX: 0,
      maxX: 0,
      minY: 0,
      maxY: 0,
    });
    expect(viewportPanBounds({ x: 0, y: 0, width: 1, height: 1 }, 2, 100, 80)).toEqual({
      minX: -50,
      maxX: 50,
      minY: -40,
      maxY: 40,
    });
    const constrained = constrainCropViewport(
      { x: 0, y: 0, width: 1, height: 1 },
      { zoom: 0.1, panX: 1000, panY: -1000 },
      100,
      100,
    );
    expect(constrained.zoom).toBe(1);
    expect(constrained.panX).toBe(0);
    expect(constrained.panY).toBe(0);
  });

  test("zooms the image with the wheel while keeping the crop box fixed", async () => {
    const item: ImageItem = {
      id: "wheel-crop-zoom",
      kind: "image",
      source: { path: "reference_director/sources/wheel.png", mime: "image/png", sha256: "b".repeat(64) },
      originalSource: { path: "reference_director/sources/wheel.png", mime: "image/png", sha256: "b".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const overlay = document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay");
    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    activateCropMode();
    stage?.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: 50, clientY: 50, deltaY: -100 }));
    const firstZoom = zoom?.valueAsNumber ?? 1;
    expect(firstZoom).toBeGreaterThan(1);
    expect(parseFloat(overlay?.style.left ?? "NaN")).toBeCloseTo(20);
    expect(parseFloat(overlay?.style.top ?? "NaN")).toBeCloseTo(20);
    expect(parseFloat(overlay?.style.width ?? "NaN")).toBeCloseTo(50);
    expect(parseFloat(overlay?.style.height ?? "NaN")).toBeCloseTo(50);
    const cropWidth = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="width"]');
    expect(Number(cropWidth?.value)).toBeLessThan(50);

    stage?.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: 50, clientY: 50, deltaY: -100 }));
    expect(zoom?.valueAsNumber).toBeGreaterThan(firstZoom);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="undo"]')?.click();
    expect(zoom?.valueAsNumber).toBe(1);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="width"]')?.valueAsNumber).toBe(50);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await resultPromise).toBeNull();
  });

  test("keeps crop state and its fixed frame unchanged while View or Mask changes the viewport", async () => {
    const item: ImageItem = {
      id: "viewport-modes",
      kind: "image",
      source: { path: "reference_director/sources/modes.png", mime: "image/png", sha256: "c".repeat(64) },
      originalSource: { path: "reference_director/sources/modes.png", mime: "image/png", sha256: "c".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const overlay = document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay");
    const width = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="width"]');
    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    expect(zoom?.min).toBe("1");

    expect(document.querySelector('[data-action="mode-view"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(width?.disabled).toBe(true);
    expect(overlay?.classList.contains("is-inactive")).toBe(true);
    if (zoom) {
      zoom.value = "2";
      zoom.dispatchEvent(new Event("input", { bubbles: true }));
    }
    expect(Number(width?.value)).toBe(50);
    expect(overlay?.style.left).toBe("20%");
    expect(overlay?.style.width).toBe("50%");

    stage?.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: 50, clientY: 50, deltaY: 10000 }));
    expect(Number(zoom?.value)).toBe(1);
    expect(Number(width?.value)).toBe(50);
    expect(overlay?.style.width).toBe("50%");

    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="mode-mask"]')?.click();
    expect(document.querySelector(".rd-image-editor canvas")?.getAttribute("aria-disabled")).toBe("false");
    stage?.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: 50, clientY: 50, deltaY: -100 }));
    expect(Number(zoom?.value)).toBeGreaterThan(1);
    expect(Number(width?.value)).toBe(50);
    expect(overlay?.style.left).toBe("20%");
    expect(overlay?.style.width).toBe("50%");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await resultPromise).toBeNull();
  });

  test("keeps View viewport changes out of history and restores Interaction mode with undo and redo", async () => {
    const item: ImageItem = {
      id: "interaction-history",
      kind: "image",
      source: { path: "reference_director/sources/history.png", mime: "image/png", sha256: "9".repeat(64) },
      originalSource: { path: "reference_director/sources/history.png", mime: "image/png", sha256: "9".repeat(64) },
      caption: "",
      imageEnabled: true,
    };
    const resultPromise = openImageEditor({ item, imageWidth: 160, imageHeight: 90 });
    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    const undo = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="undo"]');
    const redo = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="redo"]');
    const mode = (name: "view" | "crop" | "mask"): HTMLButtonElement | null =>
      document.querySelector<HTMLButtonElement>(`.rd-image-editor [data-action="mode-${name}"]`);

    expect(undo?.disabled).toBe(true);
    if (zoom) {
      zoom.value = "2";
      zoom.dispatchEvent(new Event("input", { bubbles: true }));
    }
    expect(zoom?.valueAsNumber).toBe(2);
    expect(undo?.disabled).toBe(true);

    mode("crop")?.click();
    mode("mask")?.click();
    expect(mode("mask")?.getAttribute("aria-pressed")).toBe("true");
    undo?.click();
    expect(mode("crop")?.getAttribute("aria-pressed")).toBe("true");
    undo?.click();
    expect(mode("view")?.getAttribute("aria-pressed")).toBe("true");
    expect(zoom?.valueAsNumber).toBe(2);
    redo?.click();
    expect(mode("crop")?.getAttribute("aria-pressed")).toBe("true");
    redo?.click();
    expect(mode("mask")?.getAttribute("aria-pressed")).toBe("true");

    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await resultPromise).toBeNull();
  });

  test("moves the crop frame when dragging inside it", async () => {
    const item: ImageItem = {
      id: "crop-move",
      kind: "image",
      source: { path: "reference_director/sources/move.png", mime: "image/png", sha256: "a".repeat(64) },
      originalSource: { path: "reference_director/sources/move.png", mime: "image/png", sha256: "a".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const overlay = document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay");
    activateCropMode();
    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 30, clientY: 30 }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: 45, clientY: 40 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 45, clientY: 40 }));
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-x"]')?.value)).toBe(0);
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-y"]')?.value)).toBe(0);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="x"]')?.valueAsNumber).toBe(35);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="y"]')?.valueAsNumber).toBe(30);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="width"]')?.valueAsNumber).toBe(50);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="height"]')?.valueAsNumber).toBe(50);
    expect(overlay?.style.left).toBe("35%");
    expect(parseFloat(overlay?.style.top ?? "NaN")).toBeCloseTo(30);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    const result = await resultPromise;
    if (result?.action !== "apply") throw new Error("Expected an applied image edit.");
    expect(result.edit.crop?.x).toBeCloseTo(0.35);
    expect(result.edit.crop?.y).toBeCloseTo(0.3);
    expect(result.edit.crop?.width).toBeCloseTo(0.5);
    expect(result.edit.crop?.height).toBeCloseTo(0.5);
  });

  test("pans the image instead of moving a focused crop that fills the viewport", async () => {
    const item: ImageItem = {
      id: "viewport-fill-pan",
      kind: "image",
      source: { path: "reference_director/sources/full.png", mime: "image/png", sha256: "1".repeat(64) },
      originalSource: { path: "reference_director/sources/full.png", mime: "image/png", sha256: "1".repeat(64) },
      caption: "",
      imageEnabled: true,
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    if (zoom) {
      zoom.value = "2";
      zoom.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const overlay = document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay");
    activateCropMode();
    expect(stage?.classList.contains("is-viewport-fill-crop")).toBe(true);
    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 30, clientY: 30 }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: 45, clientY: 40 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 45, clientY: 40 }));
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-x"]')?.value)).toBe(15);
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-y"]')?.value)).toBe(10);
    expect(overlay?.style.left).toBe("0%");
    expect(overlay?.style.top).toBe("0%");
    expect(overlay?.style.width).toBe("100%");
    expect([...document.querySelectorAll<HTMLButtonElement>(".rd-image-editor [data-crop-handle]")].every((handle) => !handle.hidden)).toBe(true);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    const result = await resultPromise;
    if (result?.action !== "apply") throw new Error("Expected an applied image edit.");
    expect(result.edit.crop?.x).toBeCloseTo(0.175);
    expect(result.edit.crop?.y).toBeCloseTo(0.2);
    expect(result.edit.crop?.width).toBeCloseTo(0.5);
    expect(result.edit.crop?.height).toBeCloseTo(0.5);
  });

  test("pans from outside the crop frame and clamps at the stage bounds", async () => {
    const item: ImageItem = {
      id: "bounded-pan",
      kind: "image",
      source: { path: "reference_director/sources/bounds.png", mime: "image/png", sha256: "d".repeat(64) },
      originalSource: { path: "reference_director/sources/bounds.png", mime: "image/png", sha256: "d".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    if (zoom) {
      zoom.value = "2";
      zoom.dispatchEvent(new Event("input", { bubbles: true }));
    }
    activateCropMode();
    stage?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 5, clientY: 5 }));
    stage?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: 1000, clientY: 1000 }));
    stage?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 1000, clientY: 1000 }));
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-x"]')?.value)).toBe(50);
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-y"]')?.value)).toBe(50);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="x"]')?.valueAsNumber).toBe(35);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="y"]')?.valueAsNumber).toBe(35);
    expect(document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay")?.dataset.cropFocused).toBe("false");
    expect([...document.querySelectorAll<HTMLButtonElement>(".rd-image-editor [data-crop-handle]")].every((handle) => handle.hidden)).toBe(true);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await resultPromise).toBeNull();
  });

  test("preserves the crop and exposes only visible handles when a refocused frame is clipped", async () => {
    const item: ImageItem = {
      id: "crop-focus",
      kind: "image",
      source: { path: "reference_director/sources/focus.png", mime: "image/png", sha256: "f".repeat(64) },
      originalSource: { path: "reference_director/sources/focus.png", mime: "image/png", sha256: "f".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const overlay = document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay");
    const handles = [...document.querySelectorAll<HTMLButtonElement>(".rd-image-editor [data-crop-handle]")];
    const cropX = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="x"]');
    const cropY = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="y"]');
    const cropWidth = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="width"]');
    activateCropMode();

    stage?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 5, clientY: 5 }));
    stage?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 5, clientY: 5 }));
    expect(overlay?.dataset.cropFocused).toBe("false");
    expect(handles.every((handle) => handle.hidden && handle.disabled)).toBe(true);

    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    if (zoom) {
      zoom.value = "2";
      zoom.dispatchEvent(new Event("input", { bubbles: true }));
    }
    expect(cropX?.valueAsNumber).toBe(20);
    expect(cropY?.valueAsNumber).toBe(20);
    expect(cropWidth?.valueAsNumber).toBe(50);
    expect(parseFloat(overlay?.style.left ?? "NaN")).toBeCloseTo(-10);
    expect(parseFloat(overlay?.style.width ?? "NaN")).toBeCloseTo(100);

    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 2, clientX: 30, clientY: 30 }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 2, clientX: 45, clientY: 40 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 2, clientX: 45, clientY: 40 }));
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-x"]')?.value)).toBe(15);
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-y"]')?.value)).toBe(10);
    expect(cropX?.valueAsNumber).toBe(20);
    expect(cropY?.valueAsNumber).toBe(20);
    expect(cropWidth?.valueAsNumber).toBe(50);
    expect(parseFloat(overlay?.style.left ?? "NaN")).toBeCloseTo(5);
    expect(parseFloat(overlay?.style.top ?? "NaN")).toBeCloseTo(0);
    expect(overlay?.dataset.cropFocused).toBe("false");

    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 3, clientX: 30, clientY: 30 }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 3, clientX: 32, clientY: 32 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 3, clientX: 32, clientY: 32 }));
    expect(overlay?.dataset.cropFocused).toBe("true");
    expect(overlay?.dataset.cropFocusMode).toBe("resize-only");
    expect(handles.filter((handle) => !handle.hidden).map((handle) => handle.dataset.cropHandle)).toEqual([
      "north-west",
      "south-west",
    ]);

    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 4, clientX: 30, clientY: 30 }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 4, clientX: 20, clientY: 25 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 4, clientX: 20, clientY: 25 }));
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-x"]')?.value)).toBe(5);
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-y"]')?.value)).toBe(5);
    expect(cropX?.valueAsNumber).toBe(20);
    expect(cropY?.valueAsNumber).toBe(20);
    expect(cropWidth?.valueAsNumber).toBe(50);
    expect(overlay?.dataset.cropFocusMode).toBe("resize-only");
    expect(handles.filter((handle) => !handle.hidden).map((handle) => handle.dataset.cropHandle)).toEqual(["south-east"]);

    const southEast = handles.find((handle) => handle.dataset.cropHandle === "south-east");
    southEast?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 5, clientX: 95, clientY: 95 }));
    southEast?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 5, clientX: 85, clientY: 85 }));
    southEast?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 5, clientX: 85, clientY: 85 }));
    expect(cropWidth?.valueAsNumber).toBe(45);

    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 6, clientX: 30, clientY: 30 }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 6, clientX: 35, clientY: 35 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 6, clientX: 35, clientY: 35 }));
    expect(overlay?.dataset.cropFocusMode).toBe("focused");
    expect(handles.every((handle) => !handle.hidden && !handle.disabled)).toBe(true);
    expect(cropWidth?.valueAsNumber).toBe(45);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    const result = await resultPromise;
    if (result?.action !== "apply") throw new Error("Expected an applied image edit.");
    expect(result.edit.crop?.x).toBeCloseTo(0.2);
    expect(result.edit.crop?.y).toBeCloseTo(0.2);
    expect(result.edit.crop?.width).toBeCloseTo(0.45);
    expect(result.edit.crop?.height).toBeCloseTo(0.45);
  });

  test("uses Ctrl-drag to pan from inside the crop frame", async () => {
    const item: ImageItem = {
      id: "ctrl-pan",
      kind: "image",
      source: { path: "reference_director/sources/ctrl.png", mime: "image/png", sha256: "e".repeat(64) },
      originalSource: { path: "reference_director/sources/ctrl.png", mime: "image/png", sha256: "e".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const zoom = document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="zoom"]');
    if (zoom) {
      zoom.value = "2";
      zoom.dispatchEvent(new Event("input", { bubbles: true }));
    }
    activateCropMode();
    const overlay = document.querySelector<HTMLElement>(".rd-image-editor .rd-crop-overlay");
    overlay?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 30, clientY: 30, ctrlKey: true }));
    overlay?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: 45, clientY: 40 }));
    overlay?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 45, clientY: 40 }));
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-x"]')?.value)).toBe(15);
    expect(Number(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="pan-y"]')?.value)).toBe(10);
    expect(overlay?.style.left).toBe("20%");
    expect(overlay?.style.top).toBe("20%");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await resultPromise).toBeNull();
  });

  test("commits a four-corner crop drag to the applied edit", async () => {
    const item: ImageItem = {
      id: "crop-handles",
      kind: "image",
      source: { path: "reference_director/sources/crop.png", mime: "image/png", sha256: "c".repeat(64) },
      originalSource: { path: "reference_director/sources/crop.png", mime: "image/png", sha256: "c".repeat(64) },
      caption: "",
      imageEnabled: true,
      edit: { crop: { x: 0.2, y: 0.2, width: 0.5, height: 0.5 } },
    };
    const resultPromise = openImageEditor({ item, imageWidth: 100, imageHeight: 100 });
    const stage = document.querySelector<HTMLElement>(".rd-image-editor .rd-editor-stage");
    Object.defineProperty(stage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const handle = document.querySelector<HTMLElement>('.rd-image-editor [data-crop-handle="south-east"]');
    activateCropMode();
    handle?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1, clientX: 70, clientY: 70 }));
    handle?.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: 90, clientY: 80 }));
    handle?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: 90, clientY: 80 }));
    expect(document.querySelectorAll(".rd-image-editor [data-crop-handle]")).toHaveLength(4);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="width"]')?.valueAsNumber).toBe(70);
    expect(document.querySelector<HTMLInputElement>('.rd-image-editor [data-field="height"]')?.valueAsNumber).toBe(60);
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    const result = await resultPromise;
    expect(result?.action).toBe("apply");
    if (result?.action !== "apply") throw new Error("Expected an applied image edit.");
    expect(result.edit.crop?.width).toBeCloseTo(0.7);
    expect(result.edit.crop?.height).toBeCloseTo(0.6);
  });

  test("adds optional rembg removal to the applied edit recipe", async () => {
    const item: ImageItem = {
      id: "foreground",
      kind: "image",
      source: { path: "reference_director/sources/foreground.png", mime: "image/png", sha256: "b".repeat(64) },
      originalSource: { path: "reference_director/sources/foreground.png", mime: "image/png", sha256: "b".repeat(64) },
      caption: "",
      imageEnabled: true,
    };
    let resolvePreview: ((url: string) => void) | undefined;
    const resultPromise = openImageEditor({
      item,
      backgroundPreview: () => new Promise((resolve) => {
        resolvePreview = resolve;
      }),
    });
    const caption = document.querySelector<HTMLTextAreaElement>('.rd-image-editor textarea[data-field="caption"]');
    if (caption) caption.value = "foreground subject";
    const removeButton = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="remove-background"]');
    removeButton?.click();
    expect(removeButton?.getAttribute("aria-pressed")).toBe("true");
    const apply = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]');
    expect(apply?.disabled).toBe(true);
    resolvePreview?.("/foreground-without-background.png");
    await Promise.resolve();
    await Promise.resolve();
    expect(document.querySelector<HTMLImageElement>(".rd-image-editor img")?.getAttribute("src")).toBe("/foreground-without-background.png");
    expect(apply?.disabled).toBe(false);
    apply?.click();
    expect(await resultPromise).toMatchObject({ caption: "foreground subject", edit: { removeBackground: true, revision: 1 } });
  });

  test("restores the original preview when rembg preview generation fails", async () => {
    const item: ImageItem = {
      id: "missing-rembg",
      kind: "image",
      source: { path: "reference_director/sources/original.png", mime: "image/png", sha256: "d".repeat(64) },
      originalSource: { path: "reference_director/sources/original.png", mime: "image/png", sha256: "d".repeat(64) },
      caption: "",
      imageEnabled: true,
    };
    const resultPromise = openImageEditor({
      item,
      previewUrl: "/original.webp",
      backgroundPreview: async () => {
        throw new Error("Install the optional rembg dependency.");
      },
    });
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="remove-background"]')?.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="remove-background"]')?.getAttribute("aria-pressed")).toBe("false");
    expect(document.querySelector<HTMLImageElement>(".rd-image-editor img")?.getAttribute("src")).toBe("/original.webp");
    expect(document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.disabled).toBe(false);
    expect(document.querySelector(".rd-image-editor .rd-modal__error")?.textContent).toContain("optional rembg");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await resultPromise).toBeNull();
  });

  test("returns a restore-original action for materialized image edits", async () => {
    const item: ImageItem = {
      id: "restore-original",
      kind: "image",
      source: { path: "reference_director/edits/edited.png", mime: "image/png", sha256: "e".repeat(64) },
      originalSource: { path: "reference_director/sources/original.png", mime: "image/png", sha256: "f".repeat(64) },
      caption: "before",
      imageEnabled: false,
      edit: { crop: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }, revision: 2 },
    };
    const resultPromise = openImageEditor({ item });
    const caption = document.querySelector<HTMLTextAreaElement>('.rd-image-editor [data-field="caption"]');
    if (caption) caption.value = "restored caption";
    const restore = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="restore-original"]');
    expect(restore?.hidden).toBe(false);
    restore?.click();
    expect(await resultPromise).toEqual({ action: "restore-original", caption: "restored caption" });
  });
});

describe("trim editor details", () => {
  test("shows the source filename inside the detail dialog", async () => {
    const result = openTrimEditor({ kind: "audio", filename: "voice take.wav", duration: 2, caption: "voice" });
    expect(document.querySelector(".rd-trim-editor .rd-modal__filename")?.textContent).toBe("File: voice take.wav");
    document.querySelector<HTMLButtonElement>('.rd-trim-editor [data-action="cancel"]')?.click();
    expect(await result).toBeNull();
  });

  test("edits a dual-ended trim range and previews the draft selection", async () => {
    const audio = document.createElement("audio");
    let playCalls = 0;
    let pauseCalls = 0;
    Object.defineProperties(audio, {
      load: { configurable: true, value: () => undefined },
      play: { configurable: true, value: async () => { playCalls += 1; } },
      pause: { configurable: true, value: () => { pauseCalls += 1; } },
    });
    const player = new AudioPreviewPlayer(audio);
    const result = openTrimEditor({
      kind: "audio",
      filename: "selection.wav",
      duration: 6,
      caption: "selection",
      crop: { start: 1, end: 5 },
      playback: { player, owner: "editor:selection", url: "/audio-preview", enabled: true },
    });
    const startSlider = document.querySelector<HTMLInputElement>('.rd-trim-editor [data-field="range-start"]');
    const endSlider = document.querySelector<HTMLInputElement>('.rd-trim-editor [data-field="range-end"]');
    expect(startSlider?.value).toBe("1");
    expect(endSlider?.value).toBe("5");
    if (startSlider) {
      startSlider.value = "2";
      startSlider.dispatchEvent(new Event("input", { bubbles: true }));
      startSlider.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const seek = document.querySelector<HTMLInputElement>('.rd-trim-editor [data-field="seek"]');
    expect(seek?.min).toBe("2");
    expect(seek?.max).toBe("5");
    if (seek) {
      seek.value = "2.5";
      seek.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const playbackToggle = document.querySelector<HTMLButtonElement>('.rd-trim-editor [data-action="playback-toggle"]');
    playbackToggle?.click();
    await Promise.resolve();
    expect(playCalls).toBe(1);
    expect(audio.currentTime).toBe(2.5);
    const playhead = document.querySelector<HTMLElement>(".rd-trim-editor .rd-trim-playhead");
    expect(playhead?.hidden).toBe(false);
    if (seek) {
      seek.value = "3";
      seek.dispatchEvent(new Event("input", { bubbles: true }));
    }
    expect(playhead?.style.left).toBe("50%");
    expect(playbackToggle?.textContent).toContain("Pause");
    playbackToggle?.click();
    expect(pauseCalls).toBeGreaterThan(0);
    expect(playbackToggle?.textContent).toContain("Resume");
    if (seek) {
      seek.value = "4";
      seek.dispatchEvent(new Event("input", { bubbles: true }));
    }
    expect(audio.currentTime).toBe(4);
    expect(playbackToggle?.textContent).toContain("Resume");
    playbackToggle?.click();
    await Promise.resolve();
    expect(playCalls).toBe(2);
    document.querySelector<HTMLButtonElement>('.rd-trim-editor [data-action="stop"]')?.click();
    expect(seek?.value).toBe("2");
    expect(playhead?.hidden).toBe(true);
    document.querySelector<HTMLButtonElement>('.rd-trim-editor [data-action="apply"]')?.click();
    expect(await result).toMatchObject({ crop: { start: 2, end: 5 }, caption: "selection" });
    player.destroy();
  });

  test("keeps playback unavailable for a silent video while retaining trim controls", async () => {
    const player = new AudioPreviewPlayer(document.createElement("audio"));
    const result = openTrimEditor({
      kind: "video",
      filename: "silent.mp4",
      duration: 3,
      caption: "",
      playback: { player, owner: "editor:silent", url: "/silent", enabled: false },
    });
    expect(document.querySelector<HTMLButtonElement>('.rd-trim-editor [data-action="playback-toggle"]')?.disabled).toBe(true);
    expect(document.querySelector<HTMLInputElement>('.rd-trim-editor [data-field="seek"]')?.disabled).toBe(true);
    expect(document.querySelectorAll('.rd-trim-editor input[type="range"]')).toHaveLength(3);
    document.querySelector<HTMLButtonElement>('.rd-trim-editor [data-action="cancel"]')?.click();
    expect(await result).toBeNull();
    player.destroy();
  });
});
