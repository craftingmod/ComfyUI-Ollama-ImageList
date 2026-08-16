import type { ComfyApi, ComfyApp } from "@comfyorg/comfyui-frontend-types"

import type {
  ComfyNodeDefinitionLike,
  ComfyNodeLike,
  ComfyNodeTypeLike,
  ComfyWidget,
} from "./comfy-types.ts"
import { getWidget } from "./comfy-types.ts"
import { EXTENSION_NAMES, PROJECT_NAME } from "./constants.ts"

const NODE_CLASS = "OllamaImageList_Connectivity"
const MODELS_ROUTE = "/ollama_image_list/models"
const requestSequence: unique symbol = Symbol("ollamaModelsRequestSequence")

type ConnectivityNode = ComfyNodeLike & { [requestSequence]?: number }

function showError(app: ComfyApp, message: string): void {
  app.extensionManager.toast.add({
    severity: "error",
    summary: `${PROJECT_NAME} model fetch failed`,
    detail: message,
    life: 5000,
  })
}

export function parseModels(payload: unknown): string[] {
  if (!payload || typeof payload !== "object" || !("models" in payload)) {
    throw new Error("ComfyUI returned an invalid Ollama model list.")
  }
  const models = payload.models
  if (!Array.isArray(models) || models.some((value) => typeof value !== "string")) {
    throw new Error("ComfyUI returned an invalid Ollama model list.")
  }
  return models
}

async function requestModels(api: ComfyApi, url: string): Promise<string[]> {
  const response = await api.fetchApi(MODELS_ROUTE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new Error(`ComfyUI returned HTTP ${response.status}.`)
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "error" in payload
        ? String(payload.error)
        : `ComfyUI returned HTTP ${response.status}.`
    throw new Error(detail)
  }
  return parseModels(payload)
}

function copySelectionToModel(
  node: ConnectivityNode,
  modelWidget: ComfyWidget,
  value: unknown,
): void {
  if (typeof value !== "string") return
  modelWidget.value = value
  modelWidget.callback?.(value)
  node.setDirtyCanvas(true, true)
}

async function refreshModels(
  app: ComfyApp,
  api: ComfyApi,
  node: ConnectivityNode,
  buttonWidget: ComfyWidget,
): Promise<void> {
  const urlWidget = getWidget(node, "url")
  const availableWidget = getWidget(node, "available_models")
  const modelWidget = getWidget(node, "model")
  if (!urlWidget || !availableWidget || !modelWidget) return

  const sequence = (node[requestSequence] ?? 0) + 1
  node[requestSequence] = sequence
  buttonWidget.name = "Fetching..."
  buttonWidget.disabled = true
  node.setDirtyCanvas(true, true)

  try {
    const models = await requestModels(api, String(urlWidget.value ?? ""))
    if (node[requestSequence] !== sequence) return

    availableWidget.options ??= {}
    availableWidget.options.values = models

    const currentModel = String(modelWidget.value ?? "")
    if (currentModel) {
      availableWidget.value = currentModel
    } else if (models.length > 0) {
      availableWidget.value = models[0]
      copySelectionToModel(node, modelWidget, models[0])
    } else {
      availableWidget.value = ""
    }
    node.setDirtyCanvas(true, true)
  } catch (error) {
    if (node[requestSequence] === sequence) {
      showError(app, error instanceof Error ? error.message : "Unknown error.")
    }
  } finally {
    if (node[requestSequence] === sequence) {
      buttonWidget.name = "Fetch"
      buttonWidget.disabled = false
      node.setDirtyCanvas(true, true)
    }
  }
}

export function registerOllamaConnectivity(app: ComfyApp, api: ComfyApi): void {
  app.registerExtension({
    name: EXTENSION_NAMES.CONNECTIVITY,

    beforeRegisterNodeDef(nodeType, nodeData) {
      const definition = nodeData as unknown as ComfyNodeDefinitionLike
      if (definition.name !== NODE_CLASS) return

      const typedNodeType = nodeType as unknown as ComfyNodeTypeLike
      const originalOnNodeCreated = typedNodeType.prototype.onNodeCreated
      typedNodeType.prototype.onNodeCreated = function (...args: unknown[]) {
        const node = this as ConnectivityNode
        const result = originalOnNodeCreated?.apply(node, args)
        const availableWidget = getWidget(node, "available_models")
        const modelWidget = getWidget(node, "model")
        if (!availableWidget || !modelWidget) return result

        const originalAvailableCallback = availableWidget.callback
        availableWidget.callback = (value, ...callbackArgs) => {
          originalAvailableCallback?.call(availableWidget, value, ...callbackArgs)
          copySelectionToModel(node, modelWidget, value)
        }

        const fetchButton = node.addWidget("button", "Fetch", null, () => {
          void refreshModels(app, api, node, fetchButton)
        })
        fetchButton.serialize = false

        setTimeout(() => void refreshModels(app, api, node, fetchButton), 0)
        return result
      }
    },
  })
}
