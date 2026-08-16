import { describe, expect, it } from "bun:test"

import type { ComfyNodeLike, ComfyWidget } from "../src/comfy-types.ts"
import {
  updateGenerateWidgets,
  updateNativeSpeculativeConfigWidgets,
  updateNgramPresetWidgets,
} from "../src/widget-state.ts"

function makeNode(widgets: ComfyWidget[], inputs: ComfyNodeLike["inputs"] = []): ComfyNodeLike {
  return {
    widgets,
    inputs,
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

  it("disables draft selection for the internal MTP preset", () => {
    const preset = { name: "preset", value: "Qwen 3.5 Internal MTP" }
    const draft = { name: "draft_model", disabled: false }
    const customType = { name: "custom_spec_type", disabled: false }
    const node = makeNode([preset, draft, customType])

    updateNativeSpeculativeConfigWidgets(node)
    expect(draft.disabled).toBeTrue()
    expect(customType.disabled).toBeTrue()
  })
})
