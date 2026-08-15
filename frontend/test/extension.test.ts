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
    const cardAspect: ComfyWidget = { name: "card_aspect", value: "4 / 3" };
    const previewFit: ComfyWidget = { name: "preview_fit", value: "contain" };
    const waveformPairs: ComfyWidget = { name: "waveform_pairs", value: 300 };
    const limitImagePixels: ComfyWidget = { name: "limit_image_pixels", value: false };
    const maxImagePixels: ComfyWidget = { name: "max_image_pixels", value: 2 };
    const compositeAlpha: ComfyWidget = { name: "composite_alpha", value: false };
    const alphaBackground: ComfyWidget = { name: "alpha_background", value: "#000000" };
    const directorWidget: ComfyWidget = { name: "director_state", value: "" };
    const node: ComfyNode = {
      widgets: [
        directorWidget,
        limitImagePixels,
        maxImagePixels,
        compositeAlpha,
        alphaBackground,
        gridColumns,
        previewPixels,
        showCaptions,
        cardAspect,
        previewFit,
        waveformPairs,
      ],
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
    cardAspect.callback?.("9 / 16");
    previewFit.callback?.("cover");
    waveformPairs.callback?.(750);
    serialized = JSON.parse(String(domOptions?.getValue?.()));
    expect(serialized.ui.cardAspectRatio).toBe("9 / 16");
    expect(serialized.ui.previewFit).toBe("cover");
    expect(serialized.ui.waveformPeaks).toBe(750);
    expect(cardAspect.value).toBe("9 / 16");
    expect(previewFit.value).toBe("cover");
    expect(waveformPairs.value).toBe(750);
    expect(directorRoot?.style.getPropertyValue("--rd-preview-fit")).toBe("cover");
    expect(directorRoot?.querySelector(".rd-settings")).toBeNull();
    const restored = createEmptyDirectorState();
    restored.ui.gridColumns = 2;
    restored.ui.previewMaxPixels = 4_000_000;
    restored.ui.cardAspectRatio = "1 / 1";
    restored.ui.previewFit = "contain";
    restored.ui.waveformPeaks = 450;
    gridColumns.value = 8;
    previewPixels.value = 16;
    showCaptions.value = true;
    cardAspect.value = "16 / 9";
    previewFit.value = "cover";
    waveformPairs.value = 1000;
    limitImagePixels.value = true;
    maxImagePixels.value = 6;
    compositeAlpha.value = true;
    alphaBackground.value = "#123456";
    domOptions?.setValue?.(serializeDirectorState(restored));
    expect(gridColumns.value).toBe(2);
    expect(previewPixels.value).toBe(4);
    expect(showCaptions.value).toBe(false);
    expect(cardAspect.value).toBe("1 / 1");
    expect(previewFit.value).toBe("contain");
    expect(waveformPairs.value).toBe(450);
    expect(limitImagePixels.value).toBe(true);
    expect(maxImagePixels.value).toBe(6);
    expect(compositeAlpha.value).toBe(true);
    expect(alphaBackground.value).toBe("#123456");
    gridColumns.value = 7;
    previewPixels.value = 12;
    showCaptions.value = true;
    cardAspect.value = "16 / 9";
    previewFit.value = "cover";
    waveformPairs.value = 1000;
    limitImagePixels.value = false;
    maxImagePixels.value = 3.5;
    compositeAlpha.value = false;
    alphaBackground.value = "#abcdef";
    directorWidget.beforeQueued?.();
    expect(gridColumns.value).toBe(2);
    expect(previewPixels.value).toBe(4);
    expect(showCaptions.value).toBe(false);
    expect(cardAspect.value).toBe("1 / 1");
    expect(previewFit.value).toBe("contain");
    expect(waveformPairs.value).toBe(450);
    expect(limitImagePixels.value).toBe(false);
    expect(maxImagePixels.value).toBe(3.5);
    expect(compositeAlpha.value).toBe(false);
    expect(alphaBackground.value).toBe("#abcdef");
    directorWidget.onRemove?.();
  });
});
