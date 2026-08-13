import type { ComfyApiLike, ComfyAppLike, ComfyNode, ComfyWidget } from "../comfyui";
import { ReferenceDirectorApi } from "./api";
import { ReferenceDirectorController } from "./components/director";

export const REFERENCE_DIRECTOR_WIDGET_TYPE = "OLLAMA_REFERENCE_DIRECTOR";
const controllers = new WeakMap<ComfyNode, ReferenceDirectorController>();
const removalHooks = new WeakSet<ComfyNode>();

export function registerReferenceDirector(app: ComfyAppLike, api: ComfyApiLike): void {
  app.registerExtension({
    name: "ComfyUI.OllamaImageList.ReferenceDirector",
    getCustomWidgets() {
      return {
        [REFERENCE_DIRECTOR_WIDGET_TYPE]: (node, inputName, inputData) => {
          controllers.get(node)?.destroy();
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
          const widget = node.addDOMWidget(inputName, REFERENCE_DIRECTOR_WIDGET_TYPE, root, {
            serialize: true,
            hideOnZoom: false,
            getValue: () => controller.serialize(),
            setValue: (value) => controller.restore(value),
            getMinHeight: () => 360,
            getMaxHeight: () => 1_200,
          });
          widget.serialize = true;
          widget.serializeValue = () => controller.serialize();
          widget.beforeQueued = () => undefined;
          const originalWidgetRemove = widget.onRemove;
          widget.onRemove = () => {
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
