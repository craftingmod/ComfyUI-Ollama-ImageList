import type { ComfyApiLike, ComfyAppLike, ComfyNode, ComfyWidget } from "../comfyui";

const NODE_CLASS = "OllamaImageList_Connectivity";
const MODELS_ROUTE = "/ollama_image_list/models";
const requestSequences = new WeakMap<ComfyNode, number>();
const patchedTypes = new WeakSet<object>();

function getWidget(node: ComfyNode, name: string): ComfyWidget | undefined {
  return node.widgets?.find((widget) => widget.name === name);
}

export function registerOllamaConnectivity(app: ComfyAppLike, api: ComfyApiLike): void {
  function showError(message: string): void {
    app.extensionManager.toast.add({
      severity: "error",
      summary: "Ollama model fetch failed",
      detail: message,
      life: 5_000,
    });
  }

  async function requestModels(url: string): Promise<string[]> {
    const response = await api.fetchApi(MODELS_ROUTE, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new Error(`ComfyUI returned HTTP ${response.status}.`);
    }
    if (typeof payload !== "object" || payload === null) {
      throw new Error("ComfyUI returned an invalid Ollama response.");
    }
    const record = payload as Record<string, unknown>;
    if (!response.ok) {
      throw new Error(typeof record.error === "string" ? record.error : `ComfyUI returned HTTP ${response.status}.`);
    }
    if (!Array.isArray(record.models) || record.models.some((value) => typeof value !== "string")) {
      throw new Error("ComfyUI returned an invalid Ollama model list.");
    }
    return record.models as string[];
  }

  function copySelectionToModel(node: ComfyNode, modelWidget: ComfyWidget, value: unknown): void {
    if (typeof value !== "string") return;
    modelWidget.value = value;
    modelWidget.callback?.(value);
    node.setDirtyCanvas(true, true);
  }

  async function refreshModels(node: ComfyNode, buttonWidget: ComfyWidget): Promise<void> {
    const urlWidget = getWidget(node, "url");
    const availableWidget = getWidget(node, "available_models");
    const modelWidget = getWidget(node, "model");
    if (!urlWidget || !availableWidget || !modelWidget) return;

    const sequence = (requestSequences.get(node) ?? 0) + 1;
    requestSequences.set(node, sequence);
    buttonWidget.name = "Fetching...";
    buttonWidget.disabled = true;
    node.setDirtyCanvas(true, true);

    try {
      const models = await requestModels(String(urlWidget.value ?? ""));
      if (requestSequences.get(node) !== sequence) return;
      availableWidget.options ??= {};
      availableWidget.options.values = models;
      const currentModel = String(modelWidget.value ?? "");
      if (currentModel) {
        availableWidget.value = currentModel;
      } else if (models[0]) {
        availableWidget.value = models[0];
        copySelectionToModel(node, modelWidget, models[0]);
      } else {
        availableWidget.value = "";
      }
      node.setDirtyCanvas(true, true);
    } catch (error) {
      if (requestSequences.get(node) === sequence) {
        showError(error instanceof Error ? error.message : "Unknown error.");
      }
    } finally {
      if (requestSequences.get(node) === sequence) {
        buttonWidget.name = "Fetch";
        buttonWidget.disabled = false;
        node.setDirtyCanvas(true, true);
      }
    }
  }

  app.registerExtension({
    name: "ComfyUI.OllamaImageList.Connectivity",
    beforeRegisterNodeDef(nodeType, nodeData) {
      if (nodeData.name !== NODE_CLASS || patchedTypes.has(nodeType)) return;
      patchedTypes.add(nodeType);
      const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function (...args: unknown[]): unknown {
        const result = originalOnNodeCreated?.apply(this, args);
        const availableWidget = getWidget(this, "available_models");
        const modelWidget = getWidget(this, "model");
        if (!availableWidget || !modelWidget) return result;

        const originalAvailableCallback = availableWidget.callback;
        availableWidget.callback = (value, ...callbackArgs) => {
          originalAvailableCallback?.call(availableWidget, value, ...callbackArgs);
          copySelectionToModel(this, modelWidget, value);
        };
        const fetchButton = this.addWidget("button", "Fetch", null, () => {
          void refreshModels(this, fetchButton);
        });
        fetchButton.serialize = false;
        setTimeout(() => void refreshModels(this, fetchButton), 0);
        return result;
      };
    },
  });
}
