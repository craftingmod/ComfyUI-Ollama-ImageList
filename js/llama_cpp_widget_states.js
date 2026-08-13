import { app } from "../../scripts/app.js";

const NGRAM_PRESET_CLASS = "OllamaImageList_LlamaCppNGramSpeculativePreset";
const COMPACT_NGRAM_CONFIG_CLASS = "OllamaImageList_LlamaCppNGramSpeculativeConfig";
const COMPACT_MODEL_PROFILE_CLASS = "OllamaImageList_LlamaCppModelProfile";
const COMPACT_HARDWARE_PROFILE_CLASS = "OllamaImageList_LlamaCppHardwareRuntimeProfile";
const REASONING_CONFIG_CLASS = "OllamaImageList_LlamaCppReasoningConfig";
const NATIVE_SPECULATIVE_CONFIG_CLASS = "OllamaImageList_LlamaCppNativeSpeculativeConfig";
const GENERATE_CLASS = "OllamaImageList_LlamaCppGenerate";
const SPECULATIVE_GENERATE_CLASS = "OllamaImageList_LlamaCppSpeculativeGenerate";

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
const SPECULATIVE_DETAIL_WIDGETS = ["spec_n_max", "spec_n_min", "spec_p_min"];
const THINKING_DETAIL_WIDGETS = ["reasoning_strength", "reasoning_budget"];
const NATIVE_DRAFT_CUSTOM_WIDGETS = [
    "custom_spec_type",
    "custom_mtp_provider",
    "spec_n_max",
    "spec_n_min",
    "spec_p_min",
];
const COMPACT_HARDWARE_CUSTOM_WIDGETS = [
    "n_batch",
    "n_ubatch",
    "gpu_layers",
    "main_gpu",
    "n_threads",
    "flash_attention",
    "use_mmap",
];
const COMPACT_MODEL_CUSTOM_WIDGETS = [
    "custom_handler",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "presence_penalty",
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

function updateNativeSpeculativeConfigWidgets(node) {
    const preset = getWidget(node, "preset")?.value;
    setWidgetsDisabled(node, NATIVE_DRAFT_CUSTOM_WIDGETS, preset !== "Custom");
    setWidgetsDisabled(
        node,
        ["draft_model"],
        preset === "Off" || preset === "Qwen 3.5 Internal MTP",
    );
}

function updateCompactModelProfileWidgets(node) {
    const profile = getWidget(node, "profile")?.value;
    setWidgetsDisabled(node, COMPACT_MODEL_CUSTOM_WIDGETS, profile !== "Custom");
}

function updateCompactHardwareProfileWidgets(node) {
    const profile = getWidget(node, "profile")?.value;
    setWidgetsDisabled(node, COMPACT_HARDWARE_CUSTOM_WIDGETS, profile !== "Custom");
}

function updateReasoningConfigWidgets(node) {
    const mode = getWidget(node, "reasoning_mode")?.value;
    setWidgetsDisabled(
        node,
        ["reasoning_effort", "max_reasoning_tokens"],
        mode !== "on",
    );
}

function updateGenerateWidgets(node) {
    setWidgetsDisabled(node, SAMPLING_WIDGETS, isInputConnected(node, "sampling"));
    setWidgetsDisabled(node, RUNTIME_WIDGETS, isInputConnected(node, "runtime"));
    setWidgetsDisabled(node, THINKING_DETAIL_WIDGETS, getWidget(node, "thinking")?.value !== true);
}

function updateSpeculativeGenerateWidgets(node) {
    const specType = getWidget(node, "spec_type");
    setWidgetsDisabled(node, SPECULATIVE_DETAIL_WIDGETS, specType?.value === "none");
    setWidgetsDisabled(node, ["mtp_provider"], specType?.value !== "draft-mtp");
    setWidgetsDisabled(node, THINKING_DETAIL_WIDGETS, getWidget(node, "thinking")?.value !== true);
}

function installThinkingCallback(node, updateWidgets) {
    const thinking = getWidget(node, "thinking");
    if (!thinking) {
        return;
    }
    const originalCallback = thinking.callback;
    thinking.callback = (value, ...args) => {
        const result = originalCallback?.call(thinking, value, ...args);
        updateWidgets(node);
        return result;
    };
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

function initializeNativeSpeculativeConfig(node) {
    const preset = getWidget(node, "preset");
    if (preset) {
        const originalCallback = preset.callback;
        preset.callback = (value, ...args) => {
            const result = originalCallback?.call(preset, value, ...args);
            updateNativeSpeculativeConfigWidgets(node);
            return result;
        };
    }
    setTimeout(() => updateNativeSpeculativeConfigWidgets(node), 0);
}

function initializeCompactModelProfile(node) {
    const profile = getWidget(node, "profile");
    if (profile) {
        const originalCallback = profile.callback;
        profile.callback = (value, ...args) => {
            const result = originalCallback?.call(profile, value, ...args);
            updateCompactModelProfileWidgets(node);
            return result;
        };
    }
    setTimeout(() => updateCompactModelProfileWidgets(node), 0);
}

function initializeCompactHardwareProfile(node) {
    const profile = getWidget(node, "profile");
    if (profile) {
        const originalCallback = profile.callback;
        profile.callback = (value, ...args) => {
            const result = originalCallback?.call(profile, value, ...args);
            updateCompactHardwareProfileWidgets(node);
            return result;
        };
    }
    setTimeout(() => updateCompactHardwareProfileWidgets(node), 0);
}

function initializeReasoningConfig(node) {
    const mode = getWidget(node, "reasoning_mode");
    if (mode) {
        const originalCallback = mode.callback;
        mode.callback = (value, ...args) => {
            const result = originalCallback?.call(mode, value, ...args);
            updateReasoningConfigWidgets(node);
            return result;
        };
    }
    setTimeout(() => updateReasoningConfigWidgets(node), 0);
}

function initializeGenerate(node) {
    installThinkingCallback(node, updateGenerateWidgets);
    const originalOnConnectionsChange = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = originalOnConnectionsChange?.apply(this, arguments);
        updateGenerateWidgets(this);
        return result;
    };

    // Existing workflow links are restored before this timer runs.
    setTimeout(() => updateGenerateWidgets(node), 0);
}

function initializeSpeculativeGenerate(node) {
    installThinkingCallback(node, updateSpeculativeGenerateWidgets);
    const specType = getWidget(node, "spec_type");
    if (specType) {
        const originalCallback = specType.callback;
        specType.callback = (value, ...args) => {
            const result = originalCallback?.call(specType, value, ...args);
            updateSpeculativeGenerateWidgets(node);
            return result;
        };
    }

    // Workflow widget values are restored before this timer runs.
    setTimeout(() => updateSpeculativeGenerateWidgets(node), 0);
}

app.registerExtension({
    name: "ComfyUI.OllamaImageList.LlamaCppWidgetStates",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (
            nodeData.name !== NGRAM_PRESET_CLASS &&
            nodeData.name !== COMPACT_NGRAM_CONFIG_CLASS &&
            nodeData.name !== COMPACT_MODEL_PROFILE_CLASS &&
            nodeData.name !== COMPACT_HARDWARE_PROFILE_CLASS &&
            nodeData.name !== REASONING_CONFIG_CLASS &&
            nodeData.name !== NATIVE_SPECULATIVE_CONFIG_CLASS &&
            nodeData.name !== GENERATE_CLASS &&
            nodeData.name !== SPECULATIVE_GENERATE_CLASS
        ) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            if (
                nodeData.name === NGRAM_PRESET_CLASS ||
                nodeData.name === COMPACT_NGRAM_CONFIG_CLASS
            ) {
                initializeNgramPreset(this);
            } else if (nodeData.name === COMPACT_MODEL_PROFILE_CLASS) {
                initializeCompactModelProfile(this);
            } else if (nodeData.name === COMPACT_HARDWARE_PROFILE_CLASS) {
                initializeCompactHardwareProfile(this);
            } else if (nodeData.name === REASONING_CONFIG_CLASS) {
                initializeReasoningConfig(this);
            } else if (nodeData.name === NATIVE_SPECULATIVE_CONFIG_CLASS) {
                initializeNativeSpeculativeConfig(this);
            } else if (nodeData.name === GENERATE_CLASS) {
                initializeGenerate(this);
            } else {
                initializeSpeculativeGenerate(this);
            }
            return result;
        };
    },
});
