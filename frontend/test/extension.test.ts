import { describe, expect, test } from "bun:test";

import type { ComfyApiLike, ComfyAppLike, ComfyExtension, ComfyNode, ComfyWidget, DomWidgetOptions } from "../src/comfyui";
import { registerReferenceDirector, REFERENCE_DIRECTOR_WIDGET_TYPE } from "../src/reference-director/extension";
import { createMediaItem, createEmptyDirectorState } from "../src/reference-director/types";
import { directorReducer } from "../src/reference-director/reducer";
import { serializeDirectorState } from "../src/reference-director/serialization";

describe("Reference Director custom widget", () => {
  test("exposes getValue/setValue so workflow restoration replaces controller state", () => {
    let extension: ComfyExtension | undefined;
    const app: ComfyAppLike = {
      extensionManager: { toast: { add: () => undefined } },
      registerExtension(candidate) {
        extension = candidate;
      },
    };
    const api: ComfyApiLike = { fetchApi: async () => new Response("{}") };
    registerReferenceDirector(app, api);
    const factory = extension?.getCustomWidgets?.()[REFERENCE_DIRECTOR_WIDGET_TYPE];
    expect(factory).toBeDefined();

    let domOptions: DomWidgetOptions | undefined;
    let valueSetCount = 0;
    let removeReceiver: ComfyWidget | undefined;
    const widget = { name: "director_state" } as ComfyWidget;
    widget.onRemove = function (this: ComfyWidget) {
      removeReceiver = this;
    };
    Object.defineProperty(widget, "value", {
      get: () => domOptions?.getValue?.() ?? "",
      set: (value: unknown) => {
        valueSetCount += 1;
        domOptions?.setValue?.(value);
      },
    });
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget(_name, _type, _element, options) {
        domOptions = options;
        return widget;
      },
      setDirtyCanvas: () => undefined,
    };
    factory?.(node, "director_state", ["STRING", { default: serializeDirectorState(createEmptyDirectorState()) }], app);

    const item = createMediaItem(
      "image",
      { path: "reference_director/sources/a.png", mime: "image/png", sha256: "a".repeat(64) },
      "restored",
    );
    const restored = directorReducer(createEmptyDirectorState(), { type: "add", item });
    expect(valueSetCount).toBe(0);
    widget.value = serializeDirectorState(restored);
    expect(valueSetCount).toBe(1);
    expect(JSON.parse(String(domOptions?.getValue?.())).visualOrder).toEqual(["restored"]);
    expect(String(widget.value)).toContain("restored");
    widget.onRemove?.();
    expect(removeReceiver).toBe(widget);
  });
});
