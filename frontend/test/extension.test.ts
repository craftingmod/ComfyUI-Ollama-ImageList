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
    expect(JSON.parse(String(domOptions?.getValue?.())).imageOrder).toEqual(["restored"]);
    expect(String(widget.value)).toContain("restored");
    widget.onRemove?.();
    expect(removeReceiver).toBe(widget);
  });

  test("uses native advanced widgets as write-only proxies for Director state", async () => {
    let extension: ComfyExtension | undefined;
    const app: ComfyAppLike = {
      extensionManager: { toast: { add: () => undefined } },
      registerExtension(candidate) {
        extension = candidate;
      },
    };
    registerReferenceDirector(app, { fetchApi: async () => new Response("{}") });
    const factory = extension?.getCustomWidgets?.()[REFERENCE_DIRECTOR_WIDGET_TYPE];
    let domOptions: DomWidgetOptions | undefined;
    let directorRoot: HTMLElement | undefined;
    const gridColumns: ComfyWidget = { name: "grid_columns", value: 3 };
    const previewPixels: ComfyWidget = { name: "preview_pixels", value: 1 };
    const showCaptions: ComfyWidget = { name: "show_captions", value: true };
    const directorWidget: ComfyWidget = { name: "director_state", value: "" };
    const node: ComfyNode = {
      widgets: [directorWidget, gridColumns, previewPixels, showCaptions],
      properties: {},
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget(_name, _type, element, options) {
        directorRoot = element;
        domOptions = options;
        return directorWidget;
      },
      setDirtyCanvas: () => undefined,
    };
    factory?.(node, "director_state", ["STRING", { default: serializeDirectorState(createEmptyDirectorState()) }], app);
    await new Promise((resolve) => setTimeout(resolve, 0));

    previewPixels.value = 16;
    gridColumns.callback?.(5);
    let serialized = JSON.parse(String(domOptions?.getValue?.()));
    expect(serialized.ui.gridColumns).toBe(5);
    expect(serialized.ui.previewMaxPixels).toBe(1_000_000);
    expect(previewPixels.value).toBe(1);
    previewPixels.callback?.(2.5);
    serialized = JSON.parse(String(domOptions?.getValue?.()));
    expect(serialized.ui.gridColumns).toBe(5);
    expect(serialized.ui.previewMaxPixels).toBe(2_500_000);
    expect(gridColumns.value).toBe(5);
    expect(previewPixels.value).toBe(2.5);
    expect(directorRoot?.style.getPropertyValue("--rd-grid-columns")).toBe("5");
    showCaptions.callback?.(false);
    expect(showCaptions.value).toBe(false);
    expect((node.properties?.referenceDirector as Record<string, unknown>).showCaptions).toBe(false);
    expect(directorRoot?.querySelector("textarea[data-field='caption']")).toBeNull();
    const restored = createEmptyDirectorState();
    restored.ui.gridColumns = 2;
    restored.ui.previewMaxPixels = 4_000_000;
    gridColumns.value = 8;
    previewPixels.value = 16;
    showCaptions.value = true;
    domOptions?.setValue?.(serializeDirectorState(restored));
    expect(gridColumns.value).toBe(2);
    expect(previewPixels.value).toBe(4);
    expect(showCaptions.value).toBe(false);
    gridColumns.value = 7;
    previewPixels.value = 12;
    showCaptions.value = true;
    directorWidget.beforeQueued?.();
    expect(gridColumns.value).toBe(2);
    expect(previewPixels.value).toBe(4);
    expect(showCaptions.value).toBe(false);
    directorWidget.onRemove?.();
  });
});
