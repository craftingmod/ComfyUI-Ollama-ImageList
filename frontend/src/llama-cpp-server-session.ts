import type { ComfyApi, ComfyApp } from "@comfyorg/comfyui-frontend-types"

import type {
  ComfyNodeLike,
  ComfyWidget,
} from "./comfy-types.ts"
import { getWidget } from "./comfy-types.ts"
import { EXTENSION_NAMES, PROJECT_NAME } from "./constants.ts"

const NODE_CLASS = "OllamaImageList_LlamaCppConnectSession"
const MODELS_ROUTE = "/ollama_image_list/llama_cpp/models"
const requestSequence: unique symbol = Symbol("llamaCppModelsRequestSequence")

type ConnectSessionNode = ComfyNodeLike & {
  comfyClass?: string
  [requestSequence]?: number
}

function showError(app: ComfyApp, message: string): void {
  app.extensionManager.toast.add({
    severity: "error",
    summary: `${PROJECT_NAME} llama.cpp model fetch failed`,
    detail: message,
    life: 5000,
  })
}

function parseModels(payload: unknown): string[] {
  if (
    !payload ||
    typeof payload !== "object" ||
    !("models" in payload) ||
    !Array.isArray(payload.models) ||
    payload.models.some((model) => typeof model !== "string")
  ) {
    throw new Error("ComfyUI returned an invalid llama.cpp model list.")
  }
  return payload.models
}

async function requestModels(
  api: ComfyApi,
  url: string,
  apiKey: string,
): Promise<string[]> {
  const response = await api.fetchApi(MODELS_ROUTE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, api_key: apiKey }),
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
  node: ConnectSessionNode,
  modelWidget: ComfyWidget,
  value: unknown,
): void {
  if (typeof value !== "string") return
  modelWidget.value = value
  modelWidget.callback?.(value)
  node.setDirtyCanvas(true, true)
}

async function connect(
  app: ComfyApp,
  api: ComfyApi,
  node: ConnectSessionNode,
  connectWidget: ComfyWidget,
): Promise<void> {
  const urlWidget = getWidget(node, "url")
  const apiKeyWidget = getWidget(node, "api_key")
  const availableWidget = getWidget(node, "available_models")
  const modelWidget = getWidget(node, "model")
  if (!urlWidget || !availableWidget || !modelWidget) return

  const sequence = (node[requestSequence] ?? 0) + 1
  node[requestSequence] = sequence
  connectWidget.label = "Connecting..."
  connectWidget.disabled = true
  node.setDirtyCanvas(true, true)

  try {
    const models = await requestModels(
      api,
      String(urlWidget.value ?? ""),
      String(apiKeyWidget?.value ?? ""),
    )
    if (node[requestSequence] !== sequence) return
    availableWidget.options ??= {}
    availableWidget.options.values = models
    const currentModel = String(modelWidget.value ?? "")
    availableWidget.value = models.includes(currentModel) ? currentModel : ""
    node.setDirtyCanvas(true, true)
  } catch (error) {
    if (node[requestSequence] === sequence) {
      showError(app, error instanceof Error ? error.message : "Unknown error.")
    }
  } finally {
    if (node[requestSequence] === sequence) {
      connectWidget.label = "Connect"
      connectWidget.disabled = false
      node.setDirtyCanvas(true, true)
    }
  }
}

export function registerLlamaCppServerSession(app: ComfyApp, api: ComfyApi): void {
  app.registerExtension({
    name: EXTENSION_NAMES.LLAMA_CPP_SERVER_SESSION,

    nodeCreated(node) {
      const sessionNode = node as unknown as ConnectSessionNode
      if (sessionNode.comfyClass !== NODE_CLASS) return
      const availableWidget = getWidget(sessionNode, "available_models")
      const modelWidget = getWidget(sessionNode, "model")
      if (!availableWidget || !modelWidget) return

      const originalAvailableCallback = availableWidget.callback
      availableWidget.callback = (value, ...callbackArgs) => {
        originalAvailableCallback?.call(availableWidget, value, ...callbackArgs)
        copySelectionToModel(sessionNode, modelWidget, value)
      }

      const connectWidget = sessionNode.addWidget("button", "Connect", null, () => {
        void connect(app, api, sessionNode, connectWidget)
      })
      connectWidget.tooltip = "Fetch model IDs from the configured llama.cpp server."
      connectWidget.serialize = false
      const widgets = sessionNode.widgets
      const buttonIndex = widgets?.indexOf(connectWidget) ?? -1
      if (widgets && buttonIndex >= 0) {
        widgets.splice(buttonIndex, 1)
        widgets.unshift(connectWidget)
      }
    },
  })
}
