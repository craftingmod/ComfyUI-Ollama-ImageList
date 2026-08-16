import type { ComfyNodeLike } from "./comfy-types.ts"
import { getWidget } from "./comfy-types.ts"

export const NGRAM_DETAIL_WIDGETS = [
  "ngram_size",
  "num_pred_tokens",
  "ngram_mode",
  "ngram_min_hits",
  "ngram_max_entries_per_key",
  "ngram_sync_check_tokens",
]
export const SAMPLING_WIDGETS = ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"]
export const RUNTIME_WIDGETS = [
  "n_batch",
  "override_n_ubatch",
  "n_ubatch",
  "override_image_max_tokens",
  "image_max_tokens",
]
export const SPECULATIVE_DETAIL_WIDGETS = ["spec_n_max", "spec_n_min", "spec_p_min"]
export const THINKING_DETAIL_WIDGETS = ["reasoning_strength", "reasoning_budget"]
export const NATIVE_DRAFT_CUSTOM_WIDGETS = [
  "custom_spec_type",
  "custom_mtp_provider",
  "spec_n_max",
  "spec_n_min",
  "spec_p_min",
]
export const COMPACT_HARDWARE_CUSTOM_WIDGETS = [
  "n_batch",
  "n_ubatch",
  "gpu_layers",
  "main_gpu",
  "n_threads",
  "flash_attention",
  "use_mmap",
]
export const COMPACT_MODEL_CUSTOM_WIDGETS = [
  "custom_handler",
  "temperature",
  "top_p",
  "top_k",
  "min_p",
  "repeat_penalty",
  "presence_penalty",
]

export function isInputConnected(node: ComfyNodeLike, name: string): boolean {
  return node.inputs?.find((candidate) => candidate.name === name)?.link != null
}

export function setWidgetsDisabled(
  node: ComfyNodeLike,
  names: readonly string[],
  disabled: boolean,
): void {
  let changed = false
  for (const name of names) {
    const widget = getWidget(node, name)
    if (widget && widget.disabled !== disabled) {
      widget.disabled = disabled
      changed = true
    }
  }
  if (changed) node.setDirtyCanvas(true, true)
}

export function updateNgramPresetWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    NGRAM_DETAIL_WIDGETS,
    getWidget(node, "speculative_mode")?.value !== "ngram",
  )
}

export function updateNativeSpeculativeConfigWidgets(node: ComfyNodeLike): void {
  const preset = getWidget(node, "preset")?.value
  setWidgetsDisabled(node, NATIVE_DRAFT_CUSTOM_WIDGETS, preset !== "Custom")
  setWidgetsDisabled(node, ["draft_model"], preset === "Off" || preset === "Qwen 3.5 Internal MTP")
}

export function updateCompactModelProfileWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    COMPACT_MODEL_CUSTOM_WIDGETS,
    getWidget(node, "profile")?.value !== "Custom",
  )
}

export function updateCompactHardwareProfileWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    COMPACT_HARDWARE_CUSTOM_WIDGETS,
    getWidget(node, "profile")?.value !== "Custom",
  )
}

export function updateReasoningConfigWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    ["reasoning_effort", "max_reasoning_tokens"],
    getWidget(node, "reasoning_mode")?.value !== "on",
  )
}

export function updateGenerateWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(node, SAMPLING_WIDGETS, isInputConnected(node, "sampling"))
  setWidgetsDisabled(node, RUNTIME_WIDGETS, isInputConnected(node, "runtime"))
  setWidgetsDisabled(node, THINKING_DETAIL_WIDGETS, getWidget(node, "thinking")?.value !== true)
}

export function updateSpeculativeGenerateWidgets(node: ComfyNodeLike): void {
  const specType = getWidget(node, "spec_type")?.value
  setWidgetsDisabled(node, SPECULATIVE_DETAIL_WIDGETS, specType === "none")
  setWidgetsDisabled(node, ["mtp_provider"], specType !== "draft-mtp")
  setWidgetsDisabled(node, THINKING_DETAIL_WIDGETS, getWidget(node, "thinking")?.value !== true)
}
