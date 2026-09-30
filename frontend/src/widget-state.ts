import type { ComfyNodeLike } from "./comfy-types.ts"
import { getWidget } from "./comfy-types.ts"

export const NGRAM_DETAIL_WIDGETS = [
  "ngram_size",
  "num_pred_tokens",
  "ngram_mode",
  "ngram_min_hits",
  "ngram_max_entries_per_key",
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
export const NATIVE_DRAFT_MODEL_PRESETS = ["External MTP", "DFlash", "DSpark", "Custom"]
export const NATIVE_DRAFT_GENERAL_WIDGETS = [
  "draft_n_max",
  "draft_p_min",
  "draft_n_gpu_layers",
  "draft_backend_sampling",
]
export const COMPACT_HARDWARE_WIDGETS = [
  "n_batch",
  "n_ubatch",
  "gpu_layers",
  "main_gpu",
  "n_threads",
  "flash_attention",
  "use_mmap",
]
export const COMPACT_MODEL_CUSTOM_WIDGETS = [
  "temperature",
  "top_p",
  "top_k",
  "min_p",
  "repeat_penalty",
  "presence_penalty",
]
export const PREFILL_CUSTOM_WIDGETS = [
  "n_batch",
  "n_ubatch",
  "image_min_tokens",
  "image_max_tokens",
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
  if (changed) {
    node.updateComputedDisabled?.()
    node.setDirtyCanvas(true, true)
  }
}

export function updateNgramPresetWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    NGRAM_DETAIL_WIDGETS,
    getWidget(node, "speculative_mode")?.value !== "ngram",
  )
}

export function updateNativeSpeculativeConfigWidgets(node: ComfyNodeLike): void {
  const presetValue = getWidget(node, "preset")?.value
  const preset = typeof presetValue === "string" ? presetValue : "Off"
  const isOff = preset === "Off"
  setWidgetsDisabled(node, ["draft_model"], isOff || !NATIVE_DRAFT_MODEL_PRESETS.includes(preset))
  setWidgetsDisabled(
    node,
    ["custom_spec_type", "custom_mtp_provider"],
    isOff || preset !== "Custom",
  )
  setWidgetsDisabled(node, NATIVE_DRAFT_GENERAL_WIDGETS, isOff)
}

export function updateCompactModelProfileWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    COMPACT_MODEL_CUSTOM_WIDGETS,
    getWidget(node, "profile")?.value !== "Custom",
  )
}

export function updatePrefillProfileWidgets(node: ComfyNodeLike): void {
  setWidgetsDisabled(
    node,
    PREFILL_CUSTOM_WIDGETS,
    getWidget(node, "profile")?.value !== "Custom",
  )
}

export function updateCompactHardwareProfileWidgets(node: ComfyNodeLike): void {
  const profile = getWidget(node, "profile")
  if (profile) profile.value = "Custom"
  setWidgetsDisabled(node, ["profile"], true)
  setWidgetsDisabled(node, COMPACT_HARDWARE_WIDGETS, false)
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
