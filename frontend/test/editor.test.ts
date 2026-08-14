import { describe, expect, test } from "bun:test";

import {
  applyMaskBrush,
  initialImageEditorRecipe,
  openImageEditor,
  updateNormalizedCrop,
} from "../src/reference-director/editors/image-editor";
import { AudioPreviewPlayer } from "../src/reference-director/audio-preview-player";
import { openTrimEditor } from "../src/reference-director/editors/trim-editor";
import type { ImageItem } from "../src/reference-director/types";

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
      caption: "",
      imageEnabled: true,
    };
    const result = openImageEditor({ item, previewUrl: "/loading.webp" });
    const canvas = document.querySelector<HTMLCanvasElement>(".rd-image-editor canvas");
    const image = document.querySelector<HTMLImageElement>(".rd-image-editor img");
    expect(document.querySelector(".rd-image-editor .rd-modal__filename")?.textContent).toBe("File: loading.png");
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
      imageEnabled: true,
    };
    const resultPromise = openImageEditor({ item });
    const caption = document.querySelector<HTMLTextAreaElement>('.rd-image-editor textarea[data-field="caption"]');
    if (caption) caption.value = "foreground subject";
    const removeButton = document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="remove-background"]');
    removeButton?.click();
    expect(removeButton?.getAttribute("aria-pressed")).toBe("true");
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    expect(await resultPromise).toMatchObject({ caption: "foreground subject", edit: { removeBackground: true, revision: 1 } });
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
