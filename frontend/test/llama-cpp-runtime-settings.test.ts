import { describe, expect, it } from "bun:test"

import type { ComfyApi, ComfyApp } from "@comfyorg/comfyui-frontend-types"

import { registerLlamaCppRuntimeSettings } from "../src/llama-cpp-runtime-settings.ts"

const AUTO_START_SETTING = "OllamaImageList.LlamaCpp.AutoStart"
const RESTART_SETTING = "OllamaImageList.LlamaCpp.Restart"
const DOWNLOAD_SETTING = "OllamaImageList.LlamaCpp.Download"
const SERVICE_STATE_SETTING = "OllamaImageList.LlamaCpp.ServiceState"
const RESTART_ROUTE = "/ollama_image_list/llama_cpp/runtime/restart"
const RUNTIME_ROUTE = "/ollama_image_list/llama_cpp/runtime"
const DOWNLOAD_ROUTE = `${RUNTIME_ROUTE}/download`

function runtimeStatus(overrides: Record<string, unknown> = {}) {
  return {
    auto_start: true,
    state: "running",
    ctx_size: 16384,
    port: 18582,
    active_port: 18582,
    model_dir: "C:/models/LLM",
    model_dirs: ["C:/models/LLM"],
    default_model_dir: "C:/models/LLM",
    llama_available: true,
    llama_source: "path",
    llama_executable: "C:/llama/llama.exe",
    llama_version: "test",
    running: true,
    error: null,
    download_state: "idle",
    download_target: "Windows x64 CPU",
    download_supported: false,
    download_support_error: null,
    download_bytes_received: 0,
    download_bytes_total: null,
    download_error: null,
    ...overrides,
  }
}

function response(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as unknown as Response
}

function setupRuntime(
  fetchApi: (route: string, options?: RequestInit) => Promise<Response>,
  autoStart = true,
) {
  const values = new Map<string, unknown>([
    ["Comfy.Locale", "en"],
    [AUTO_START_SETTING, autoStart],
    ["OllamaImageList.LlamaCpp.ModelDir", "C:/models/LLM"],
  ])
  const toasts: Array<Record<string, unknown>> = []
  let extension:
    | {
        settings?: Array<{ id: string; type: unknown }>
        setup?: () => Promise<void>
      }
    | undefined
  const app = {
    registerExtension: (value: typeof extension) => {
      extension = value
    },
    extensionManager: {
      setting: {
        get: <T>(id: string) => values.get(id) as T,
        set: async (id: string, value: unknown) => {
          values.set(id, value)
        },
      },
      toast: { add: (toast: Record<string, unknown>) => toasts.push(toast) },
    },
    ui: { settings: { settingsParamLookup: {}, addEventListener: () => undefined } },
  } as unknown as ComfyApp

  registerLlamaCppRuntimeSettings(app, { fetchApi } as unknown as ComfyApi)
  const restartSetting = extension?.settings?.find(({ id }) => id === RESTART_SETTING)
  const downloadSetting = extension?.settings?.find(({ id }) => id === DOWNLOAD_SETTING)
  const render = restartSetting?.type as (
    name: string,
    setter: (value: unknown) => void,
    value: unknown,
  ) => HTMLElement
  const button = render("Restart", () => undefined, null) as HTMLButtonElement
  const renderDownloadSetting = downloadSetting?.type as () => HTMLElement
  return {
    button,
    renderDownload() {
      const control = renderDownloadSetting()
      return {
        root: control,
        button: control.querySelector("button") as HTMLButtonElement,
        message: control.querySelector("[role=status]") as HTMLElement,
      }
    },
    toasts,
    values,
  }
}

describe("llama.cpp runtime restart setting", () => {
  it("coalesces repeated clicks and reflects successful status", async () => {
    let resolveResponse!: (value: Response) => void
    const pendingResponse = new Promise<Response>((resolve) => {
      resolveResponse = resolve
    })
    const calls: Array<[string, RequestInit | undefined]> = []
    const runtime = setupRuntime(async (route, options) => {
      calls.push([route, options])
      return pendingResponse
    })

    runtime.button.click()
    runtime.button.click()
    await Promise.resolve()

    expect(calls).toHaveLength(1)
    expect(calls[0]?.[0]).toBe(RESTART_ROUTE)
    expect(calls[0]?.[1]?.method).toBe("POST")
    expect(runtime.button.disabled).toBe(true)

    resolveResponse(response(runtimeStatus()))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(runtime.values.get(SERVICE_STATE_SETTING)).toBe("running")
    expect(runtime.toasts.at(-1)?.severity).toBe("success")
    expect(runtime.button.disabled).toBe(false)
    expect(runtime.values.has(RESTART_SETTING)).toBe(false)
  })

  it("shows failed status and explains when activation is off", async () => {
    const calls: string[] = []
    const failed = setupRuntime(async (route) => {
      calls.push(route)
      return response(
        runtimeStatus({
          state: "failed",
          active_port: null,
          running: false,
          error: "supervisor shutdown timed out",
        }),
      )
    })
    failed.button.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(failed.values.get(SERVICE_STATE_SETTING)).toBe("failed")
    expect(failed.toasts.at(-1)?.severity).toBe("warn")
    expect(failed.toasts.at(-1)?.detail).toBe("supervisor shutdown timed out")

    const disabled = setupRuntime(async (route) => {
      calls.push(route)
      return response(runtimeStatus())
    }, false)
    disabled.button.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(calls).toEqual([RESTART_ROUTE])
    expect(disabled.toasts.at(-1)?.severity).toBe("info")
    expect(disabled.toasts.at(-1)?.summary).toContain("Turn on")
  })

  it("downloads once, shows byte progress, and reflects the installed runtime", async () => {
    let statusReads = 0
    const calls: Array<[string, RequestInit | undefined]> = []
    const runtime = setupRuntime(async (route, options) => {
      calls.push([route, options])
      if (route === DOWNLOAD_ROUTE) return response({})
      statusReads += 1
      return response(
        runtimeStatus(
          statusReads === 1
            ? {
                llama_available: false,
                llama_source: null,
                llama_executable: null,
                llama_version: null,
                running: false,
                download_supported: true,
              }
            : statusReads === 2
              ? {
                  llama_available: false,
                  llama_source: null,
                  llama_executable: null,
                  llama_version: null,
                  running: false,
                  download_supported: true,
                  download_state: "downloading",
                  download_bytes_received: 512,
                  download_bytes_total: 1024,
                }
              : statusReads === 3
                ? {
                    llama_source: "internal",
                    llama_executable: "C:/ComfyUI/user/__llama_cpp/artifacts/llama.exe",
                    llama_version: "b11146",
                    download_state: "installed",
                  }
                : {
                    llama_source: "path",
                    llama_executable: "D:/external/llama.exe",
                    llama_version: "external",
                    download_state: "idle",
                  },
        ),
      )
    })
    const download = runtime.renderDownload()
    await new Promise((resolve) => setTimeout(resolve, 0))

    download.button.click()
    download.button.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(calls.filter(([route]) => route === DOWNLOAD_ROUTE)).toHaveLength(1)
    expect(calls[1]?.[1]?.method).toBe("POST")
    expect(download.button.disabled).toBe(true)
    expect(download.message.textContent).toContain("512 B / 1.0 KB")

    await new Promise((resolve) => setTimeout(resolve, 1100))

    // @TODO edit
    // expect(runtime.values.get("OllamaImageList.LlamaCpp.PathStatus")).toBe(
    //   "Not found on PATH (internal install available)",
    // )
    expect(runtime.values.get("OllamaImageList.LlamaCpp.Version")).toBe("b11146")
    expect(download.message.textContent).toContain("Installed")
    expect(download.button.disabled).toBe(true)

    const reopened = runtime.renderDownload()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(calls.filter(([route]) => route === RUNTIME_ROUTE)).toHaveLength(4)
    expect(runtime.values.get("OllamaImageList.LlamaCpp.PathStatus")).toBe("Available on PATH")
    expect(runtime.values.get("OllamaImageList.LlamaCpp.Version")).toBe("external")
    expect(reopened.button.disabled).toBe(true)
  })

  it("shows backend errors and leaves a supported download retryable", async () => {
    const runtime = setupRuntime(async (route) => {
      if (route === DOWNLOAD_ROUTE) {
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: "asset download failed" }),
        } as unknown as Response
      }
      return response(
        runtimeStatus({
          llama_available: false,
          llama_source: null,
          llama_executable: null,
          llama_version: null,
          running: false,
          download_supported: true,
        }),
      )
    })
    const download = runtime.renderDownload()
    await new Promise((resolve) => setTimeout(resolve, 0))

    download.button.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(download.message.textContent).toContain("asset download failed")
    expect(download.button.disabled).toBe(false)
  })

  it("does not retry when the server reports an installed runtime", async () => {
    const calls: string[] = []
    const runtime = setupRuntime(async (route) => {
      calls.push(route)
      return response(
        runtimeStatus({
          llama_available: false,
          llama_source: null,
          llama_executable: null,
          llama_version: null,
          running: false,
          download_state: "installed",
          download_supported: true,
        }),
      )
    })
    const download = runtime.renderDownload()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(download.button.disabled).toBe(true)
    expect(download.message.textContent).toContain("Installed")
    download.button.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(calls).toEqual([RUNTIME_ROUTE])
  })

  it("disables downloads on unsupported platforms and shows the reason", async () => {
    const runtime = setupRuntime(async () =>
      response(
        runtimeStatus({
          llama_available: false,
          llama_source: null,
          llama_executable: null,
          llama_version: null,
          running: false,
          download_supported: false,
          download_support_error: "Linux arm64 ROCm is not supported.",
        }),
      ),
    )
    const download = runtime.renderDownload()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(download.button.disabled).toBe(true)
    expect(download.message.textContent).toContain("Linux arm64 ROCm is not supported.")
  })
})
