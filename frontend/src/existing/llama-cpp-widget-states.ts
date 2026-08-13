import type { ComfyAppLike, ComfyNode, ComfyWidget } from "../comfyui";

const NGRAM_PRESET_CLASS = "OllamaImageList_LlamaCppNGramSpeculativePreset";
const COMPACT_NGRAM_CONFIG_CLASS = "OllamaImageList_LlamaCppNGramSpeculativeConfig";
const COMPACT_MODEL_PROFILE_CLASS = "OllamaImageList_LlamaCppModelProfile";
const COMPACT_HARDWARE_PROFILE_CLASS = "OllamaImageList_LlamaCppHardwareRuntimeProfile";
const REASONING_CONFIG_CLASS = "OllamaImageList_LlamaCppReasoningConfig";
const NATIVE_SPECULATIVE_CONFIG_CLASS = "OllamaImageList_LlamaCppNativeSpeculativeConfig";
const GENERATE_CLASS = "OllamaImageList_LlamaCppGenerate";
const SPECULATIVE_GENERATE_CLASS = "OllamaImageList_LlamaCppSpeculativeGenerate";

const NGRAM_DETAIL_WIDGETS = ["ngram_size", "num_pred_tokens", "ngram_mode", "ngram_min_hits", "ngram_max_entries_per_key", "ngram_sync_check_tokens"];
const SAMPLING_WIDGETS = ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"];
const RUNTIME_WIDGETS = ["n_batch", "override_n_ubatch", "n_ubatch", "override_image_max_tokens", "image_max_tokens"];
const SPECULATIVE_DETAIL_WIDGETS = ["spec_n_max", "spec_n_min", "spec_p_min"];
const THINKING_DETAIL_WIDGETS = ["reasoning_strength", "reasoning_budget"];
const NATIVE_DRAFT_CUSTOM_WIDGETS = ["custom_spec_type", "custom_mtp_provider", "spec_n_max", "spec_n_min", "spec_p_min"];
const COMPACT_HARDWARE_CUSTOM_WIDGETS = ["n_batch", "n_ubatch", "gpu_layers", "main_gpu", "n_threads", "flash_attention", "use_mmap"];
const COMPACT_MODEL_CUSTOM_WIDGETS = ["custom_handler", "temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty"];
const SUPPORTED_CLASSES = new Set([
  NGRAM_PRESET_CLASS,
  COMPACT_NGRAM_CONFIG_CLASS,
  COMPACT_MODEL_PROFILE_CLASS,
  COMPACT_HARDWARE_PROFILE_CLASS,
  REASONING_CONFIG_CLASS,
  NATIVE_SPECULATIVE_CONFIG_CLASS,
  GENERATE_CLASS,
  SPECULATIVE_GENERATE_CLASS,
]);
const patchedTypes = new WeakSet<object>();

function getWidget(node: ComfyNode, name: string): ComfyWidget | undefined {
  return node.widgets?.find((widget) => widget.name === name);
}

function isInputConnected(node: ComfyNode, name: string): boolean {
  return node.inputs?.find((candidate) => candidate.name === name)?.link != null;
}

function setWidgetsDisabled(node: ComfyNode, names: readonly string[], disabled: boolean): void {
  let changed = false;
  for (const name of names) {
    const widget = getWidget(node, name);
    if (widget && widget.disabled !== disabled) {
      widget.disabled = disabled;
      changed = true;
    }
  }
  if (changed) node.setDirtyCanvas(true, true);
}

function updateNgramPresetWidgets(node: ComfyNode): void {
  setWidgetsDisabled(node, NGRAM_DETAIL_WIDGETS, getWidget(node, "speculative_mode")?.value !== "ngram");
}

function updateNativeSpeculativeConfigWidgets(node: ComfyNode): void {
  const preset = getWidget(node, "preset")?.value;
  setWidgetsDisabled(node, NATIVE_DRAFT_CUSTOM_WIDGETS, preset !== "Custom");
  setWidgetsDisabled(node, ["draft_model"], preset === "Off" || preset === "Qwen 3.5 Internal MTP");
}

function updateCompactModelProfileWidgets(node: ComfyNode): void {
  setWidgetsDisabled(node, COMPACT_MODEL_CUSTOM_WIDGETS, getWidget(node, "profile")?.value !== "Custom");
}

function updateCompactHardwareProfileWidgets(node: ComfyNode): void {
  setWidgetsDisabled(node, COMPACT_HARDWARE_CUSTOM_WIDGETS, getWidget(node, "profile")?.value !== "Custom");
}

function updateReasoningConfigWidgets(node: ComfyNode): void {
  setWidgetsDisabled(node, ["reasoning_effort", "max_reasoning_tokens"], getWidget(node, "reasoning_mode")?.value !== "on");
}

function updateGenerateWidgets(node: ComfyNode): void {
  setWidgetsDisabled(node, SAMPLING_WIDGETS, isInputConnected(node, "sampling"));
  setWidgetsDisabled(node, RUNTIME_WIDGETS, isInputConnected(node, "runtime"));
  setWidgetsDisabled(node, THINKING_DETAIL_WIDGETS, getWidget(node, "thinking")?.value !== true);
}

function updateSpeculativeGenerateWidgets(node: ComfyNode): void {
  const specType = getWidget(node, "spec_type")?.value;
  setWidgetsDisabled(node, SPECULATIVE_DETAIL_WIDGETS, specType === "none");
  setWidgetsDisabled(node, ["mtp_provider"], specType !== "draft-mtp");
  setWidgetsDisabled(node, THINKING_DETAIL_WIDGETS, getWidget(node, "thinking")?.value !== true);
}

function installCallback(node: ComfyNode, name: string, update: (node: ComfyNode) => void): void {
  const widget = getWidget(node, name);
  if (!widget) return;
  const originalCallback = widget.callback;
  widget.callback = (value, ...args) => {
    const result = originalCallback?.call(widget, value, ...args);
    update(node);
    return result;
  };
}

function initializeOnNextTurn(node: ComfyNode, update: (node: ComfyNode) => void): void {
  setTimeout(() => update(node), 0);
}

function initializeNgramPreset(node: ComfyNode): void {
  installCallback(node, "speculative_mode", updateNgramPresetWidgets);
  initializeOnNextTurn(node, updateNgramPresetWidgets);
}

function initializeNativeSpeculativeConfig(node: ComfyNode): void {
  installCallback(node, "preset", updateNativeSpeculativeConfigWidgets);
  initializeOnNextTurn(node, updateNativeSpeculativeConfigWidgets);
}

function initializeCompactModelProfile(node: ComfyNode): void {
  installCallback(node, "profile", updateCompactModelProfileWidgets);
  initializeOnNextTurn(node, updateCompactModelProfileWidgets);
}

function initializeCompactHardwareProfile(node: ComfyNode): void {
  installCallback(node, "profile", updateCompactHardwareProfileWidgets);
  initializeOnNextTurn(node, updateCompactHardwareProfileWidgets);
}

function initializeReasoningConfig(node: ComfyNode): void {
  installCallback(node, "reasoning_mode", updateReasoningConfigWidgets);
  initializeOnNextTurn(node, updateReasoningConfigWidgets);
}

function initializeGenerate(node: ComfyNode): void {
  installCallback(node, "thinking", updateGenerateWidgets);
  const originalOnConnectionsChange = node.onConnectionsChange;
  node.onConnectionsChange = function (...args: unknown[]): unknown {
    const result = originalOnConnectionsChange?.apply(this, args);
    updateGenerateWidgets(this);
    return result;
  };
  initializeOnNextTurn(node, updateGenerateWidgets);
}

function initializeSpeculativeGenerate(node: ComfyNode): void {
  installCallback(node, "thinking", updateSpeculativeGenerateWidgets);
  installCallback(node, "spec_type", updateSpeculativeGenerateWidgets);
  initializeOnNextTurn(node, updateSpeculativeGenerateWidgets);
}

export function registerLlamaCppWidgetStates(app: ComfyAppLike): void {
  app.registerExtension({
    name: "ComfyUI.OllamaImageList.LlamaCppWidgetStates",
    beforeRegisterNodeDef(nodeType, nodeData) {
      if (!SUPPORTED_CLASSES.has(nodeData.name) || patchedTypes.has(nodeType)) return;
      patchedTypes.add(nodeType);
      const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function (...args: unknown[]): unknown {
        const result = originalOnNodeCreated?.apply(this, args);
        switch (nodeData.name) {
          case NGRAM_PRESET_CLASS:
          case COMPACT_NGRAM_CONFIG_CLASS:
            initializeNgramPreset(this);
            break;
          case COMPACT_MODEL_PROFILE_CLASS:
            initializeCompactModelProfile(this);
            break;
          case COMPACT_HARDWARE_PROFILE_CLASS:
            initializeCompactHardwareProfile(this);
            break;
          case REASONING_CONFIG_CLASS:
            initializeReasoningConfig(this);
            break;
          case NATIVE_SPECULATIVE_CONFIG_CLASS:
            initializeNativeSpeculativeConfig(this);
            break;
          case GENERATE_CLASS:
            initializeGenerate(this);
            break;
          default:
            initializeSpeculativeGenerate(this);
        }
        return result;
      };
    },
  });
}
