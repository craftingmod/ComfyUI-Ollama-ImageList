import type { ComfyApp } from "@comfyorg/comfyui-frontend-types"

import type { ComfyNodeDefinitionLike, ComfyNodeLike, ComfyNodeTypeLike } from "./comfy-types.ts"
import { getWidget } from "./comfy-types.ts"
import { EXTENSION_NAMES } from "./constants.ts"
import {
  updateCompactHardwareProfileWidgets,
  updateCompactModelProfileWidgets,
  updateGenerateWidgets,
  updateNativeSpeculativeConfigWidgets,
  updateNgramPresetWidgets,
  updateReasoningConfigWidgets,
  updateSpeculativeGenerateWidgets,
} from "./widget-state.ts"

const NGRAM_PRESET_CLASS = "OllamaImageList_LlamaCppNGramSpeculativePreset"
const COMPACT_NGRAM_CONFIG_CLASS = "OllamaImageList_LlamaCppNGramSpeculativeConfig"
const COMPACT_MODEL_PROFILE_CLASS = "OllamaImageList_LlamaCppModelProfile"
const COMPACT_HARDWARE_PROFILE_CLASS = "OllamaImageList_LlamaCppHardwareRuntimeProfile"
const REASONING_CONFIG_CLASS = "OllamaImageList_LlamaCppReasoningConfig"
const NATIVE_SPECULATIVE_CONFIG_CLASS = "OllamaImageList_LlamaCppNativeSpeculativeConfig"
const GENERATE_CLASS = "OllamaImageList_LlamaCppGenerate"
const SPECULATIVE_GENERATE_CLASS = "OllamaImageList_LlamaCppSpeculativeGenerate"

const HANDLED_CLASSES = new Set([
  NGRAM_PRESET_CLASS,
  COMPACT_NGRAM_CONFIG_CLASS,
  COMPACT_MODEL_PROFILE_CLASS,
  COMPACT_HARDWARE_PROFILE_CLASS,
  REASONING_CONFIG_CLASS,
  NATIVE_SPECULATIVE_CONFIG_CLASS,
  GENERATE_CLASS,
  SPECULATIVE_GENERATE_CLASS,
])

type WidgetUpdater = (node: ComfyNodeLike) => void

function installWidgetCallback(
  node: ComfyNodeLike,
  widgetName: string,
  updater: WidgetUpdater,
): void {
  const widget = getWidget(node, widgetName)
  if (!widget) return
  const originalCallback = widget.callback
  widget.callback = (value, ...args) => {
    const result = originalCallback?.call(widget, value, ...args)
    updater(node)
    return result
  }
}

function initializeDeferred(node: ComfyNodeLike, widgetName: string, updater: WidgetUpdater): void {
  installWidgetCallback(node, widgetName, updater)
  setTimeout(() => updater(node), 0)
}

function installThinkingCallback(node: ComfyNodeLike, updater: WidgetUpdater): void {
  installWidgetCallback(node, "thinking", updater)
}

function initializeGenerate(node: ComfyNodeLike): void {
  installThinkingCallback(node, updateGenerateWidgets)
  const originalOnConnectionsChange = node.onConnectionsChange
  node.onConnectionsChange = function (...args: unknown[]) {
    const result = originalOnConnectionsChange?.apply(this, args)
    updateGenerateWidgets(this)
    return result
  }
  setTimeout(() => updateGenerateWidgets(node), 0)
}

function initializeSpeculativeGenerate(node: ComfyNodeLike): void {
  installThinkingCallback(node, updateSpeculativeGenerateWidgets)
  installWidgetCallback(node, "spec_type", updateSpeculativeGenerateWidgets)
  setTimeout(() => updateSpeculativeGenerateWidgets(node), 0)
}

function initializeNode(node: ComfyNodeLike, className: string): void {
  if (className === NGRAM_PRESET_CLASS || className === COMPACT_NGRAM_CONFIG_CLASS) {
    initializeDeferred(node, "speculative_mode", updateNgramPresetWidgets)
  } else if (className === COMPACT_MODEL_PROFILE_CLASS) {
    initializeDeferred(node, "profile", updateCompactModelProfileWidgets)
  } else if (className === COMPACT_HARDWARE_PROFILE_CLASS) {
    initializeDeferred(node, "profile", updateCompactHardwareProfileWidgets)
  } else if (className === REASONING_CONFIG_CLASS) {
    initializeDeferred(node, "reasoning_mode", updateReasoningConfigWidgets)
  } else if (className === NATIVE_SPECULATIVE_CONFIG_CLASS) {
    initializeDeferred(node, "preset", updateNativeSpeculativeConfigWidgets)
  } else if (className === GENERATE_CLASS) {
    initializeGenerate(node)
  } else {
    initializeSpeculativeGenerate(node)
  }
}

export function registerLlamaCppWidgetStates(app: ComfyApp): void {
  app.registerExtension({
    name: EXTENSION_NAMES.LLAMA_CPP_WIDGET_STATES,

    beforeRegisterNodeDef(nodeType, nodeData) {
      const definition = nodeData as unknown as ComfyNodeDefinitionLike
      if (!HANDLED_CLASSES.has(definition.name)) return

      const typedNodeType = nodeType as unknown as ComfyNodeTypeLike
      const originalOnNodeCreated = typedNodeType.prototype.onNodeCreated
      typedNodeType.prototype.onNodeCreated = function (...args: unknown[]) {
        const node = this as ComfyNodeLike
        const result = originalOnNodeCreated?.apply(node, args)
        initializeNode(node, definition.name)
        return result
      }
    },
  })
}
