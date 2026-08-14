import type { ComfyApiLike, ComfyAppLike, ComfyNode, ComfyWidget } from "../comfyui";
import { ReferenceDirectorApi } from "./api";
import { ReferenceDirectorController } from "./components/director";

export const REFERENCE_DIRECTOR_WIDGET_TYPE = "OLLAMA_REFERENCE_DIRECTOR";
const controllers = new WeakMap<ComfyNode, ReferenceDirectorController>();
const removalHooks = new WeakSet<ComfyNode>();
const displayProxies = new WeakMap<ComfyNode, NativeDisplayProxy>();

interface NativeDisplayProxy {
  syncFromState(): void;
  dispose(): void;
}

export function registerReferenceDirector(app: ComfyAppLike, api: ComfyApiLike): void {
  app.registerExtension({
    name: "ComfyUI.OllamaImageList.ReferenceDirector",
    getCustomWidgets() {
      return {
        [REFERENCE_DIRECTOR_WIDGET_TYPE]: (node, inputName, inputData) => {
          controllers.get(node)?.destroy();
          displayProxies.get(node)?.dispose();
          displayProxies.delete(node);
          const root = document.createElement("div");
          root.className = "reference-director";
          root.dataset.input = inputName;
          root.addEventListener("pointerdown", (event) => event.stopPropagation());
          root.addEventListener("wheel", (event) => event.stopPropagation());

          const initial = initialValue(inputData);
          const controller = new ReferenceDirectorController(
            root,
            node,
            new ReferenceDirectorApi(api),
            initial,
            {
              beforeChange: () => app.canvas?.emitBeforeChange?.(),
              afterChange: () => app.canvas?.emitAfterChange?.(),
            },
          );
          let displayProxy: NativeDisplayProxy | undefined;
          let removed = false;
          const widget = node.addDOMWidget(inputName, REFERENCE_DIRECTOR_WIDGET_TYPE, root, {
            serialize: true,
            hideOnZoom: false,
            getValue: () => controller.serialize(),
            setValue: (value) => {
              controller.restore(value);
              displayProxy?.syncFromState();
            },
            getMinHeight: () => 360,
            getMaxHeight: () => 1_200,
          });
          widget.serialize = true;
          widget.serializeValue = () => controller.serialize();
          widget.beforeQueued = () => displayProxy?.syncFromState();
          const bindingTimer = globalThis.setTimeout(() => {
            if (removed) return;
            displayProxy = bindNativeDisplayProxies(node, controller);
            if (displayProxy) displayProxies.set(node, displayProxy);
          }, 0);
          const originalWidgetRemove = widget.onRemove;
          widget.onRemove = () => {
            removed = true;
            globalThis.clearTimeout(bindingTimer);
            displayProxy?.dispose();
            displayProxies.delete(node);
            controller.destroy();
            originalWidgetRemove?.call(widget);
          };
          controllers.set(node, controller);

          if (!removalHooks.has(node)) {
            removalHooks.add(node);
            const originalRemoved = node.onRemoved;
            node.onRemoved = function (...args: unknown[]): unknown {
              controllers.get(this)?.destroy();
              controllers.delete(this);
              displayProxies.get(this)?.dispose();
              displayProxies.delete(this);
              return originalRemoved?.apply(this, args);
            };
          }
          const [width = 560, height = 500] = node.size ?? [];
          if (width < 520 || height < 460) node.setSize?.([Math.max(width, 560), Math.max(height, 500)]);
          return { widget };
        },
      };
    },
  });
}

function bindNativeDisplayProxies(
  node: ComfyNode,
  controller: ReferenceDirectorController,
): NativeDisplayProxy | undefined {
  const gridColumns = node.widgets?.find((widget) => widget.name === "grid_columns");
  const previewPixels = node.widgets?.find((widget) => widget.name === "preview_pixels");
  const showCaptions = node.widgets?.find((widget) => widget.name === "show_captions");
  if (!gridColumns || !previewPixels || !showCaptions) return undefined;

  const originalGridCallback = gridColumns.callback;
  const originalPreviewCallback = previewPixels.callback;
  const originalShowCaptionsCallback = showCaptions.callback;
  const syncFromState = (): void => {
    const values = controller.displayState;
    gridColumns.value = values.gridColumns;
    previewPixels.value = values.previewPixels;
    showCaptions.value = values.showCaptions;
  };
  const gridCallback: NonNullable<ComfyWidget["callback"]> = (value, ...args) => {
    const result = originalGridCallback?.call(gridColumns, value, ...args);
    controller.writeDisplayProxy({
      gridColumns: typeof value === "number" ? value : Number(value),
    });
    syncFromState();
    return result;
  };
  const previewCallback: NonNullable<ComfyWidget["callback"]> = (value, ...args) => {
    const result = originalPreviewCallback?.call(previewPixels, value, ...args);
    controller.writeDisplayProxy({
      previewPixels: typeof value === "number" ? value : Number(value),
    });
    syncFromState();
    return result;
  };
  const showCaptionsCallback: NonNullable<ComfyWidget["callback"]> = (value, ...args) => {
    const result = originalShowCaptionsCallback?.call(showCaptions, value, ...args);
    controller.writeDisplayProxy({ showCaptions: Boolean(value) });
    syncFromState();
    return result;
  };
  gridColumns.callback = gridCallback;
  previewPixels.callback = previewCallback;
  showCaptions.callback = showCaptionsCallback;
  syncFromState();
  return {
    syncFromState,
    dispose() {
      if (gridColumns.callback === gridCallback) {
        if (originalGridCallback) gridColumns.callback = originalGridCallback;
        else delete gridColumns.callback;
      }
      if (previewPixels.callback === previewCallback) {
        if (originalPreviewCallback) previewPixels.callback = originalPreviewCallback;
        else delete previewPixels.callback;
      }
      if (showCaptions.callback === showCaptionsCallback) {
        if (originalShowCaptionsCallback) showCaptions.callback = originalShowCaptionsCallback;
        else delete showCaptions.callback;
      }
    },
  };
}

function initialValue(inputData: unknown): unknown {
  if (!Array.isArray(inputData)) return undefined;
  const options = inputData[1];
  if (typeof options !== "object" || options === null) return undefined;
  const record = options as Record<string, unknown>;
  return record.default ?? record.defaultValue;
}

export function getReferenceDirectorController(node: ComfyNode): ReferenceDirectorController | undefined {
  return controllers.get(node);
}

export type ReferenceDirectorWidget = ComfyWidget;
