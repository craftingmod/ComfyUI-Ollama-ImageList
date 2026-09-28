import { describe, expect, it } from "bun:test"
import type { ComfyApi, ComfyApp } from "@comfyorg/comfyui-frontend-types"

import { registerLlamaCppRuntimeSettings } from "../src/llama-cpp-runtime-settings.ts"

const AUTO_START_SETTING = "OllamaImageList.LlamaCpp.AutoStart"
const RESTART_SETTING = "OllamaImageList.LlamaCpp.Restart"
const SERVICE_STATE_SETTING = "OllamaImageList.LlamaCpp.ServiceState"
const RESTART_ROUTE = "/ollama_image_list/llama_cpp/runtime/restart"

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
    llama_executable: "C:/llama/llama.exe",
    llama_version: "test",
    running: true,
    error: null,
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
  let extension: { settings?: Array<{ id: string; type: unknown }> } | undefined
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
  const restartSetting = extension?.settings?.find(
    ({ id }) => id === RESTART_SETTING,
  )
  const render = restartSetting?.type as (
    name: string,
    setter: (value: unknown) => void,
    value: unknown,
  ) => HTMLElement
  const button = render("Restart", () => undefined, null) as HTMLButtonElement
  return { button, toasts, values }
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
})
