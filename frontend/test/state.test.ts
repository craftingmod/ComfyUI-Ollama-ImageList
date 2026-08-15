import { describe, expect, test } from "bun:test";

import { executionFingerprintSource, projectDirectorExecution } from "../src/reference-director/execution";
import { LocalHistory, canRedo, canUndo, commitHistory, createHistory, redoHistory, undoHistory } from "../src/reference-director/history";
import { directorReducer } from "../src/reference-director/reducer";
import { deserializeDirectorState, serializeDirectorState } from "../src/reference-director/serialization";
import { createEmptyDirectorState, createMediaItem, type MediaSource } from "../src/reference-director/types";
import { validateDirectorState } from "../src/reference-director/validation";

const source = (name: string, mime: string): MediaSource => ({
  path: `reference_director/sources/${name}`,
  mime,
  sha256: "a".repeat(64),
  size: 128,
});

describe("Reference Director state", () => {
  test("adds each media kind to the correct independent order", () => {
    let state = createEmptyDirectorState();
    state = directorReducer(state, { type: "add", item: createMediaItem("image", source("i.webp", "image/webp"), "i") });
    state = directorReducer(state, { type: "add", item: createMediaItem("audio", source("a.wav", "audio/wav"), "a") });
    state = directorReducer(state, { type: "add", item: createMediaItem("video", source("v.mp4", "video/mp4"), "v") });

    expect(state.imageOrder).toEqual(["i"]);
    expect(state.videoOrder).toEqual(["v"]);
    expect(state.audioOrder).toEqual(["a", "v"]);

    const withoutVideo = directorReducer(state, { type: "remove", id: "v" });
    expect(withoutVideo.videoOrder).toEqual([]);
    expect(withoutVideo.audioOrder).toEqual(["a"]);
  });

  test("reorders, moves, toggles and removes without mutating previous state", () => {
    const first = createMediaItem("image", source("a.png", "image/png"), "a");
    const second = createMediaItem("image", source("b.png", "image/png"), "b");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: first });
    state = directorReducer(state, { type: "add", item: second });
    const previous = state;
    state = directorReducer(state, { type: "move", channel: "image", id: "a", delta: 1 });
    state = directorReducer(state, { type: "toggle", channel: "image", id: "a" });
    state = directorReducer(state, { type: "remove", id: "b" });

    expect(previous.imageOrder).toEqual(["a", "b"]);
    expect(state.imageOrder).toEqual(["a"]);
    expect(state.items.a?.kind === "image" && state.items.a.imageEnabled).toBe(false);
    expect(state.items.b).toBeUndefined();
  });

  test("clears every media channel while preserving UI preferences", () => {
    const image = createMediaItem("image", source("a.png", "image/png"), "a");
    const video = createMediaItem("video", source("v.mp4", "video/mp4"), "v");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    state = directorReducer(state, { type: "add", item: video });
    state = directorReducer(state, { type: "set-ui", values: { gridColumns: 5 } });

    const cleared = directorReducer(state, { type: "clear" });
    expect(cleared.items).toEqual({});
    expect(cleared.imageOrder).toEqual([]);
    expect(cleared.videoOrder).toEqual([]);
    expect(cleared.audioOrder).toEqual([]);
    expect(cleared.ui.gridColumns).toBe(5);
    expect(directorReducer(cleared, { type: "clear" })).toBe(cleared);
  });

  test("keeps a video audio caption override separate from its visual caption", () => {
    const video = createMediaItem("video", source("v.mp4", "video/mp4"), "v");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: video });
    state = directorReducer(state, { type: "set-caption", id: "v", channel: "video", caption: "visual" });
    state = directorReducer(state, { type: "set-caption", id: "v", channel: "audio", caption: "spoken" });
    expect(state.items.v).toMatchObject({ caption: "visual", audioCaptionOverride: "spoken" });
  });

  test("defaults every video out of the separate audio output", () => {
    const video = createMediaItem("video", source("v.mp4", "video/mp4"), "video");
    expect(video.kind === "video" && video.audioEnabled).toBe(false);
  });
});

describe("validation and serialization", () => {
  test("validates only the current state schema and repairs missing orders", () => {
    const result = validateDirectorState({
      version: 1,
      items: {
        video: {
          id: "video",
          kind: "video",
          source: source("v.mp4", "video/mp4"),
          caption: "clip",
          videoEnabled: false,
          audioEnabled: true,
          audioCaptionOverride: "voice",
        },
      },
      imageOrder: [],
      videoOrder: [],
      audioOrder: [],
      ui: {
        cardAspectRatio: "3 / 4",
        gridColumns: 99,
        previewMaxPixels: 1_750_000,
        previewFit: "cover",
        waveformPeaks: 999,
      },
    });
    expect(result.state.imageOrder).toEqual([]);
    expect(result.state.videoOrder).toEqual(["video"]);
    expect(result.state.audioOrder).toEqual(["video"]);
    expect(result.state.ui.waveformPeaks).toBe(999);
    expect(result.state.ui.cardAspectRatio).toBe("3 / 4");
    expect(result.state.ui.previewFit).toBe("cover");
    expect(result.state.ui.gridColumns).toBe(8);
    expect(result.state.ui.previewMaxPixels).toBe(1_750_000);
    expect(validateDirectorState({ version: 0 }).state).toEqual(createEmptyDirectorState());
  });

  test("falls back safely for malformed JSON and unsupported versions", () => {
    expect(deserializeDirectorState("{").state).toEqual(createEmptyDirectorState());
    expect(validateDirectorState({ version: 20 }).state).toEqual(createEmptyDirectorState());
  });

  test("defaults a restored video with no explicit audio toggle out of derived AUDIO", () => {
    const result = validateDirectorState({
      version: 1,
      items: {
        video: {
          id: "video",
          kind: "video",
          source: source("v.mp4", "video/mp4"),
          caption: "",
        },
      },
      imageOrder: [],
      videoOrder: ["video"],
      audioOrder: ["video"],
    });
    expect(result.state.items.video).toMatchObject({ videoEnabled: true, audioEnabled: false });
  });

  test("rejects oversized workflow state before parsing JSON", () => {
    const restored = deserializeDirectorState(" ".repeat(1_000_001));
    expect(restored.state).toEqual(createEmptyDirectorState());
    expect(restored.issues).toContain("State JSON exceeded the 1,000,000-character limit.");
  });

  test("serializes deterministically and stores no runtime data", () => {
    let state = createEmptyDirectorState();
    state = directorReducer(state, { type: "add", item: createMediaItem("audio", source("a.wav", "audio/wav"), "z") });
    state = directorReducer(state, { type: "add", item: createMediaItem("image", source("i.png", "image/png"), "a") });
    const serialized = serializeDirectorState(state);
    expect(serialized.indexOf('"a"')).toBeLessThan(serialized.indexOf('"z"'));
    expect(serialized).not.toContain("blob:");
    expect(deserializeDirectorState(serialized).state).toEqual(state);
    expect(deserializeDirectorState(serialized).state.items.a?.sourceFilename).toBe("i.png");
  });

  test("keeps a portable content-addressed mask in state and execution", () => {
    const image = createMediaItem("image", source("i.png", "image/png"), "i");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    const before = executionFingerprintSource(state);
    state = directorReducer(state, {
      type: "apply-image-edit",
      id: "i",
      edit: {
        mask: source("mask.png", "image/png"),
        maskMode: "keep",
        revision: 1,
      },
    });
    const restored = deserializeDirectorState(serializeDirectorState(state)).state;
    expect(restored.items.i?.kind === "image" && restored.items.i.edit?.mask?.path).toBe(
      "reference_director/sources/mask.png",
    );
    expect(projectDirectorExecution(restored).images[0]?.edit?.maskMode).toBe("keep");
    expect(executionFingerprintSource(restored)).not.toBe(before);
  });

  test("preserves the immutable original source and restores it after workflow serialization", () => {
    const original = source("original.png", "image/png");
    const image = createMediaItem("image", original, "i");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    state = directorReducer(state, {
      type: "apply-image-edit",
      id: "i",
      source: { ...source("edited.png", "image/png"), sha256: "e".repeat(64), revision: 1 },
      edit: { crop: { x: 0.1, y: 0.2, width: 0.7, height: 0.6 }, revision: 1 },
      caption: "edited",
    });
    state = deserializeDirectorState(serializeDirectorState(state)).state;
    expect(state.items.i).toMatchObject({ originalSource: original, imageEnabled: true });

    state = directorReducer(state, { type: "toggle", channel: "image", id: "i" });
    state = directorReducer(state, { type: "restore-image-original", id: "i", caption: "restored" });
    expect(state.items.i).toMatchObject({
      source: original,
      originalSource: original,
      caption: "restored",
      imageEnabled: false,
    });
    expect(state.items.i).not.toHaveProperty("edit");
    expect(state.imageOrder).toEqual(["i"]);
  });
});

describe("history and execution projection", () => {
  test("supports bounded undo/redo and caption merge keys", () => {
    let history = createHistory(0);
    history = commitHistory(history, 1, { mergeKey: "caption" });
    history = commitHistory(history, 2, { mergeKey: "caption" });
    expect(history.past).toEqual([0]);
    expect(canUndo(history)).toBe(true);
    history = undoHistory(history);
    expect(history.present).toBe(0);
    expect(canRedo(history)).toBe(true);
    history = redoHistory(history);
    expect(history.present).toBe(2);
  });

  test("bounds editor-local snapshot history", () => {
    const history = new LocalHistory(0, 20);
    for (let value = 1; value <= 30; value += 1) history.commit(value);
    for (let count = 0; count < 25; count += 1) history.undo();
    expect(history.value).toBe(10);
  });

  test("replaces transient state without creating an undo entry", () => {
    const history = new LocalHistory(0);
    history.replace(1);
    expect(history.value).toBe(1);
    expect(history.canUndo).toBe(false);
    history.commit(2);
    history.replace(3);
    expect(history.undo()).toBe(1);
  });

  test("maps video sound to a derived audio id and excludes UI from fingerprint", () => {
    const video = createMediaItem("video", source("v.mp4", "video/mp4"), "v");
    if (video.kind !== "video") throw new Error("Expected a video test item.");
    video.audioEnabled = true;
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: video });
    state = directorReducer(state, { type: "set-caption", id: "v", channel: "audio", caption: "voice" });
    const projection = projectDirectorExecution(state);
    expect(projection.audios[0]).toMatchObject({ id: "v:audio", kind: "audio", derivedFrom: "v", caption: "voice" });
    const fingerprint = executionFingerprintSource(state);
    state = directorReducer(state, { type: "set-ui", values: { cardAspectRatio: "1 / 1", previewMaxPixels: 200_000 } });
    expect(executionFingerprintSource(state)).toBe(fingerprint);
  });

  test("drops API-only source revisions from the backend execution projection", () => {
    const image = createMediaItem("image", { ...source("i.png", "image/png"), revision: 2 }, "i");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    state = directorReducer(state, {
      type: "apply-image-edit",
      id: "i",
      edit: { mask: { ...source("mask.png", "image/png"), revision: 3 }, maskMode: "keep", revision: 2 },
    });
    const projection = projectDirectorExecution(state);
    expect(projection.images[0]?.source).not.toHaveProperty("revision");
    expect(projection.images[0]?.edit?.mask).not.toHaveProperty("revision");
    expect(projection.images[0]?.edit?.revision).toBe(2);
  });

  test("clamps captions to the backend contract", () => {
    const image = createMediaItem("image", source("i.png", "image/png"), "i");
    let state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    state = directorReducer(state, { type: "set-caption", id: "i", caption: "x".repeat(20_000) });
    expect(state.items.i?.caption).toHaveLength(16_384);
  });
});
