import { describe, expect, it } from "bun:test"

import type { ComfyNodeLike, ComfyWidget } from "../src/comfy-types.ts"
import {
  updateGenerateWidgets,
  updateNativeSpeculativeConfigWidgets,
  updateNgramPresetWidgets,
} from "../src/widget-state.ts"

function makeNode(
  widgets: ComfyWidget[],
  inputs: ComfyNodeLike["inputs"] = [],
  onComputedDisabledUpdate?: () => void,
): ComfyNodeLike {
  return {
    widgets,
    inputs,
    updateComputedDisabled: onComputedDisabledUpdate,
    setDirtyCanvas() {},
    addWidget() {
      throw new Error("not used")
    },
  }
}

describe("llama.cpp widget state", () => {
  it("enables N-gram details only for ngram mode", () => {
    const mode = { name: "speculative_mode", value: "off" }
    const detail = { name: "ngram_size", disabled: false }
    const node = makeNode([mode, detail])

    updateNgramPresetWidgets(node)
    expect(detail.disabled).toBeTrue()

    mode.value = "ngram"
    updateNgramPresetWidgets(node)
    expect(detail.disabled).toBeFalse()
  })

  it("disables overridden generate widgets while preserving thinking controls", () => {
    const temperature = { name: "temperature", disabled: false }
    const nBatch = { name: "n_batch", disabled: false }
    const reasoning = { name: "reasoning_strength", disabled: false }
    const thinking = { name: "thinking", value: false }
    const node = makeNode(
      [temperature, nBatch, reasoning, thinking],
      [
        { name: "sampling", link: 1 },
        { name: "runtime", link: null },
      ],
    )

    updateGenerateWidgets(node)
    expect(temperature.disabled).toBeTrue()
    expect(nBatch.disabled).toBeFalse()
    expect(reasoning.disabled).toBeTrue()
  })

  it("applies native speculative preset activation rules", () => {
    const preset = { name: "preset", value: "Off" }
    const widgets: ComfyWidget[] = [
      preset,
      { name: "draft_model", disabled: false },
      { name: "draft_n_max", disabled: false },
      { name: "custom_spec_type", disabled: false },
      { name: "custom_mtp_provider", disabled: false },
      { name: "draft_p_min", disabled: false },
      { name: "draft_n_gpu_layers", disabled: false },
      { name: "draft_backend_sampling", disabled: false },
    ]
    const node = makeNode(widgets)

    updateNativeSpeculativeConfigWidgets(node)
    for (const widget of widgets.slice(1)) expect(widget.disabled).toBeTrue()

    preset.value = "Internal MTP"
    updateNativeSpeculativeConfigWidgets(node)
    expect(widgets[1].disabled).toBeTrue()
    expect(widgets[2].disabled).toBeFalse()
    expect(widgets[3].disabled).toBeTrue()
    expect(widgets[4].disabled).toBeTrue()
    expect(widgets[5].disabled).toBeFalse()

    for (const value of ["External MTP", "DFlash", "DSpark", "Custom"]) {
      preset.value = value
      updateNativeSpeculativeConfigWidgets(node)
      expect(widgets[1].disabled).toBeFalse()
    }

    preset.value = "Custom"
    updateNativeSpeculativeConfigWidgets(node)
    expect(widgets[1].disabled).toBeFalse()
    expect(widgets[3].disabled).toBeFalse()
    expect(widgets[4].disabled).toBeFalse()
  })

  it("refreshes computed disabled state after changing widget state", () => {
    const mode = { name: "speculative_mode", value: "off" }
    const detail = { name: "ngram_size", disabled: false }
    let updates = 0
    const node = makeNode([mode, detail], [], () => {
      updates += 1
    })

    updateNgramPresetWidgets(node)

    expect(updates).toBe(1)
  })
})
