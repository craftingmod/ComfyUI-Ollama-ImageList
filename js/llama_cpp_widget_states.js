import { app } from "../../scripts/app.js";

const NGRAM_PRESET_CLASS = "OllamaImageList_LlamaCppNGramSpeculativePreset";
const GENERATE_CLASS = "OllamaImageList_LlamaCppGenerate";

const NGRAM_DETAIL_WIDGETS = [
    "ngram_size",
    "num_pred_tokens",
    "ngram_mode",
    "ngram_min_hits",
    "ngram_max_entries_per_key",
    "ngram_sync_check_tokens",
];
const SAMPLING_WIDGETS = ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"];
const RUNTIME_WIDGETS = [
    "n_batch",
    "override_n_ubatch",
    "n_ubatch",
    "override_image_max_tokens",
    "image_max_tokens",
];

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function isInputConnected(node, name) {
    const input = node.inputs?.find((candidate) => candidate.name === name);
    return input?.link != null;
}

function setWidgetsDisabled(node, names, disabled) {
    let changed = false;
    for (const name of names) {
        const widget = getWidget(node, name);
        if (widget && widget.disabled !== disabled) {
            widget.disabled = disabled;
            changed = true;
        }
    }
    if (changed) {
        node.setDirtyCanvas(true, true);
    }
}

function updateNgramPresetWidgets(node) {
    const mode = getWidget(node, "speculative_mode");
    setWidgetsDisabled(node, NGRAM_DETAIL_WIDGETS, mode?.value !== "ngram");
}

function updateGenerateWidgets(node) {
    setWidgetsDisabled(node, SAMPLING_WIDGETS, isInputConnected(node, "sampling"));
    setWidgetsDisabled(node, RUNTIME_WIDGETS, isInputConnected(node, "runtime"));
}

function initializeNgramPreset(node) {
    const mode = getWidget(node, "speculative_mode");
    if (mode) {
        const originalCallback = mode.callback;
        mode.callback = (value, ...args) => {
            const result = originalCallback?.call(mode, value, ...args);
            updateNgramPresetWidgets(node);
            return result;
        };
    }

    // Workflow widget values are restored before this timer runs.
    setTimeout(() => updateNgramPresetWidgets(node), 0);
}

function initializeGenerate(node) {
    const originalOnConnectionsChange = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = originalOnConnectionsChange?.apply(this, arguments);
        updateGenerateWidgets(this);
        return result;
    };

    // Existing workflow links are restored before this timer runs.
    setTimeout(() => updateGenerateWidgets(node), 0);
}

app.registerExtension({
    name: "ComfyUI.OllamaImageList.LlamaCppWidgetStates",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NGRAM_PRESET_CLASS && nodeData.name !== GENERATE_CLASS) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            if (nodeData.name === NGRAM_PRESET_CLASS) {
                initializeNgramPreset(this);
            } else {
                initializeGenerate(this);
            }
            return result;
        };
    },
});
