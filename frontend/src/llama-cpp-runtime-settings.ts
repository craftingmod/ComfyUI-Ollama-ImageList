import type { ComfyApi, ComfyApp } from "@comfyorg/comfyui-frontend-types"

import { PROJECT_NAME } from "./constants.ts"
import { getRuntimeMessages } from "./llama-cpp-runtime-messages.ts"

const RUNTIME_ROUTE = "/ollama_image_list/llama_cpp/runtime"
const COMFY_LOCALE_SETTING = "Comfy.Locale"
const AUTO_START_SETTING = "OllamaImageList.LlamaCpp.AutoStart"
const PATH_STATUS_SETTING = "OllamaImageList.LlamaCpp.PathStatus"
const EXECUTABLE_PATH_SETTING = "OllamaImageList.LlamaCpp.ExecutablePath"
const LLAMA_VERSION_SETTING = "OllamaImageList.LlamaCpp.Version"

type RuntimeStatus = {
  auto_start: boolean
  llama_available: boolean
  llama_executable: string | null
  llama_version: string | null
  running: boolean
  error: string | null
}

let syncingFromBackend = false
let settingChangeRevision = 0
let settingUpdateQueue: Promise<void> = Promise.resolve()
let latestStatus: RuntimeStatus | undefined

async function setSettingFromBackend(
  app: ComfyApp,
  id: string,
  value: unknown,
): Promise<void> {
  syncingFromBackend = true
  try {
    await app.extensionManager.setting.set(id, value)
  } finally {
    syncingFromBackend = false
  }
}

async function updatePathStatus(
  app: ComfyApp,
  status: RuntimeStatus,
): Promise<void> {
  latestStatus = status
  await app.extensionManager.setting.set(
    PATH_STATUS_SETTING,
    status.llama_available ? "available" : "unavailable",
  )
  await app.extensionManager.setting.set(
    EXECUTABLE_PATH_SETTING,
    status.llama_executable ?? "—",
  )
  await app.extensionManager.setting.set(
    LLAMA_VERSION_SETTING,
    status.llama_version ?? "—",
  )
}

function showStartWarning(app: ComfyApp, status: RuntimeStatus): void {
  if (status.auto_start && !status.running) {
    const messages = getRuntimeMessages(
      app.extensionManager.setting.get<string>(COMFY_LOCALE_SETTING),
    )
    app.extensionManager.toast.add({
      severity: "warn",
      summary: messages.startFailureSummary(PROJECT_NAME),
      detail: status.error ?? messages.startFailureFallback,
      life: 7000,
    })
  }
}

async function requestStatus(
  api: ComfyApi,
  autoStart?: boolean,
): Promise<RuntimeStatus> {
  const response = await api.fetchApi(
    RUNTIME_ROUTE,
    autoStart === undefined
      ? { method: "GET" }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auto_start: autoStart }),
        },
  )
  const payload: unknown = await response.json()
  if (
    !response.ok ||
    !payload ||
    typeof payload !== "object" ||
    !("auto_start" in payload) ||
    typeof payload.auto_start !== "boolean" ||
    !("llama_available" in payload) ||
    typeof payload.llama_available !== "boolean" ||
    !("llama_executable" in payload) ||
    (typeof payload.llama_executable !== "string" &&
      payload.llama_executable !== null) ||
    !("llama_version" in payload) ||
    (typeof payload.llama_version !== "string" &&
      payload.llama_version !== null) ||
    !("running" in payload) ||
    typeof payload.running !== "boolean" ||
    !("error" in payload) ||
    (typeof payload.error !== "string" && payload.error !== null)
  ) {
    const detail =
      payload && typeof payload === "object" && "error" in payload
        ? String(payload.error)
        : `ComfyUI returned HTTP ${response.status}.`
    throw new Error(detail)
  }
  return payload as RuntimeStatus
}

export function registerLlamaCppRuntimeSettings(
  app: ComfyApp,
  api: ComfyApi,
): void {
  app.registerExtension({
    name: "ollama-image-list.llama-cpp-runtime-settings",
    settings: [
      {
        id: AUTO_START_SETTING as any,
        category: [PROJECT_NAME, "llama.cpp"],
        name: "Internal llama.cpp runtime activation",
        tooltip:
          "When enabled, starts the PATH llama executable on 127.0.0.1:8080 now and on each ComfyUI startup.",
        type: "boolean",
        defaultValue: false,
        sortOrder: 10,
        async onChange(value, oldValue) {
          if (
            syncingFromBackend ||
            oldValue === undefined ||
            typeof value !== "boolean"
          )
            return
          const revision = ++settingChangeRevision
          try {
            const update = settingUpdateQueue.then(() =>
              requestStatus(api, value),
            )
            settingUpdateQueue = update.then(
              () => undefined,
              () => undefined,
            )
            const status = await update
            if (revision !== settingChangeRevision) return
            await updatePathStatus(app, status)
            showStartWarning(app, status)
          } catch (error) {
            if (revision !== settingChangeRevision) return
            const messages = getRuntimeMessages(
              app.extensionManager.setting.get<string>(COMFY_LOCALE_SETTING),
            )
            app.extensionManager.toast.add({
              severity: "error",
              summary: messages.saveFailureSummary(PROJECT_NAME),
              detail:
                error instanceof Error
                  ? error.message
                  : messages.unknownError,
              life: 5000,
            })
            if (typeof oldValue === "boolean") {
              try {
                await setSettingFromBackend(app, AUTO_START_SETTING, oldValue)
              } catch {
                // The original setting write has already been reported above.
              }
            }
          }
        },
      },
      {
        id: PATH_STATUS_SETTING as any,
        category: [PROJECT_NAME, "llama.cpp"],
        name: "PATH availability",
        tooltip: "Whether the llama executable is available on ComfyUI's PATH.",
        type: "text",
        attrs: { readonly: true, style: { width: "20rem" } },
        defaultValue: getRuntimeMessages(
          app.extensionManager.setting.get<string>(COMFY_LOCALE_SETTING),
        ).checking,
        sortOrder: 0,
        telemetry: { trackChanges: false },
      },
      {
        id: EXECUTABLE_PATH_SETTING as any,
        category: [PROJECT_NAME, "llama.cpp"],
        name: "llama executable path",
        tooltip: "The resolved executable path when llama is available.",
        type: "text",
        attrs: { readonly: true, style: { width: "32rem" } },
        defaultValue: "—",
        sortOrder: -10,
        telemetry: { trackChanges: false },
      },
      {
        id: LLAMA_VERSION_SETTING as any,
        category: [PROJECT_NAME, "llama.cpp"],
        name: "llama version",
        tooltip: "The version reported by llama --version.",
        type: "text",
        attrs: { readonly: true, style: { width: "32rem" } },
        defaultValue: "—",
        sortOrder: -20,
        telemetry: { trackChanges: false },
      },
    ],
    async setup() {
      app.ui.settings.addEventListener(
        `${COMFY_LOCALE_SETTING}.change`,
        () => {
          if (latestStatus) {
            void updatePathStatus(app, latestStatus).catch(() => undefined)
          }
        },
      )
      try {
        const revision = settingChangeRevision
        const status = await requestStatus(api)
        if (revision !== settingChangeRevision) return
        if (
          app.extensionManager.setting.get<boolean>(AUTO_START_SETTING) !==
          status.auto_start
        ) {
          await setSettingFromBackend(app, AUTO_START_SETTING, status.auto_start)
        }
        await updatePathStatus(app, status)
        showStartWarning(app, status)
      } catch {
        const messages = getRuntimeMessages(
          app.extensionManager.setting.get<string>(COMFY_LOCALE_SETTING),
        )
        await app.extensionManager.setting.set(
          PATH_STATUS_SETTING,
          messages.statusLoadFailure,
        )
      }
    },
  })
}
