import { describe, expect, test } from "bun:test";

import {
  applyMaskBrush,
  initialImageEditorRecipe,
  openImageEditor,
  updateNormalizedCrop,
} from "../src/reference-director/editors/image-editor";
import type { ImageItem } from "../src/reference-director/types";

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
      caption: "",
      visualEnabled: true,
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
      caption: "",
      visualEnabled: true,
    };
    const result = openImageEditor({ item, previewUrl: "/loading.webp" });
    const canvas = document.querySelector<HTMLCanvasElement>(".rd-image-editor canvas");
    const image = document.querySelector<HTMLImageElement>(".rd-image-editor img");
    expect(canvas?.getAttribute("aria-disabled")).toBe("true");
    image?.dispatchEvent(new Event("load"));
    expect(canvas?.getAttribute("aria-disabled")).toBe("false");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="cancel"]')?.click();
    expect(await result).toBeNull();
  });

  test("keeps crop dimensions non-zero when an edge is moved to its limit", () => {
    const crop = { x: 0.2, y: 0.1, width: 0.5, height: 0.6 };
    expect(updateNormalizedCrop(crop, "x", 1)).toEqual({ ...crop, x: 0.5 });
    expect(updateNormalizedCrop(crop, "y", 1)).toEqual({ ...crop, y: 0.4 });
    expect(updateNormalizedCrop({ ...crop, x: 0.99 }, "width", 0)).toMatchObject({ width: 0.01 });
    expect(updateNormalizedCrop({ ...crop, y: 0.99 }, "height", 0)).toMatchObject({ height: 0.01 });
  });

  test("adds optional rembg removal to the applied edit recipe", async () => {
    const item: ImageItem = {
      id: "foreground",
      kind: "image",
      source: { path: "reference_director/sources/foreground.png", mime: "image/png", sha256: "b".repeat(64) },
      caption: "",
      visualEnabled: true,
    };
    const resultPromise = openImageEditor({ item });
    const removeButton = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="remove-background"]');
    removeButton?.click();
    expect(removeButton?.getAttribute("aria-pressed")).toBe("true");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    expect(await resultPromise).toMatchObject({ edit: { removeBackground: true, revision: 1 } });
  });
});
