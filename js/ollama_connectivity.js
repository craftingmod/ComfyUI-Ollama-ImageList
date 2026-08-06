import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_CLASS = "OllamaImageList_Connectivity";
const MODELS_ROUTE = "/ollama_image_list/models";
const requestSequence = Symbol("ollamaModelsRequestSequence");

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function showError(message) {
    app.extensionManager.toast.add({
        severity: "error",
        summary: "Ollama model fetch failed",
        detail: message,
        life: 5000,
    });
}

async function requestModels(url) {
    const response = await api.fetchApi(MODELS_ROUTE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
    });

    let payload = {};
    try {
        payload = await response.json();
    } catch {
        throw new Error(`ComfyUI returned HTTP ${response.status}.`);
    }

    if (!response.ok) {
        throw new Error(payload.error || `ComfyUI returned HTTP ${response.status}.`);
    }
    if (!Array.isArray(payload.models) || payload.models.some((value) => typeof value !== "string")) {
        throw new Error("ComfyUI returned an invalid Ollama model list.");
    }
    return payload.models;
}

function copySelectionToModel(node, modelWidget, value) {
    if (typeof value !== "string") {
        return;
    }
    modelWidget.value = value;
    modelWidget.callback?.(value);
    node.setDirtyCanvas(true, true);
}

async function refreshModels(node, buttonWidget) {
    const urlWidget = getWidget(node, "url");
    const availableWidget = getWidget(node, "available_models");
    const modelWidget = getWidget(node, "model");
    if (!urlWidget || !availableWidget || !modelWidget) {
        return;
    }

    const sequence = (node[requestSequence] ?? 0) + 1;
    node[requestSequence] = sequence;
    buttonWidget.name = "Fetching...";
    buttonWidget.disabled = true;
    node.setDirtyCanvas(true, true);

    try {
        const models = await requestModels(String(urlWidget.value ?? ""));
        if (node[requestSequence] !== sequence) {
            return;
        }

        availableWidget.options ??= {};
        availableWidget.options.values = models;

        const currentModel = String(modelWidget.value ?? "");
        if (currentModel) {
            availableWidget.value = currentModel;
        } else if (models.length > 0) {
            availableWidget.value = models[0];
            copySelectionToModel(node, modelWidget, models[0]);
        } else {
            availableWidget.value = "";
        }
        node.setDirtyCanvas(true, true);
    } catch (error) {
        if (node[requestSequence] === sequence) {
            const message = error instanceof Error ? error.message : "Unknown error.";
            showError(message);
        }
    } finally {
        if (node[requestSequence] === sequence) {
            buttonWidget.name = "Fetch";
            buttonWidget.disabled = false;
            node.setDirtyCanvas(true, true);
        }
    }
}

app.registerExtension({
    name: "ComfyUI.OllamaImageList.Connectivity",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            const availableWidget = getWidget(this, "available_models");
            const modelWidget = getWidget(this, "model");
            if (!availableWidget || !modelWidget) {
                return result;
            }

            const originalAvailableCallback = availableWidget.callback;
            availableWidget.callback = (value, ...args) => {
                originalAvailableCallback?.call(availableWidget, value, ...args);
                copySelectionToModel(this, modelWidget, value);
            };

            const fetchButton = this.addWidget("button", "Fetch", null, () => {
                void refreshModels(this, fetchButton);
            });
            fetchButton.serialize = false;

            // Workflow widget values are restored before this timer runs.
            setTimeout(() => {
                void refreshModels(this, fetchButton);
            }, 0);

            return result;
        };
    },
});
