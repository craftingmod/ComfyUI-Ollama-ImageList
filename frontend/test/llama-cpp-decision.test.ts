import { describe, expect, it } from "bun:test"
import type { ComfyApp } from "@comfyorg/comfyui-frontend-types"

import type { ComfyNodeLike, ComfyWidget } from "../src/comfy-types.ts"
import {
  registerLlamaCppDecision,
  updateQuestionAnswerWidgets,
} from "../src/llama-cpp-decision.ts"

function makeQuestionNode(count: number): ComfyNodeLike & { comfyClass: string } {
  const widgets: ComfyWidget[] = [
    { name: "question", type: "customtext", value: "Pick one" },
    { name: "inputcount", type: "number", value: count },
    ...Array.from({ length: 26 }, (_, index) => ({
      name: `answer_${index + 1}`,
      type: "text",
      value: `answer ${index + 1}`,
    })),
  ]
  return {
    comfyClass: "OllamaImageList_LlamaCppCreateQuestion",
    widgets,
    setDirtyCanvas() {},
    addWidget(type, name, value, callback) {
      const widget: ComfyWidget = { name, type, value, callback }
      widgets.push(widget)
      return widget
    },
  }
}

describe("llama.cpp decision question widgets", () => {
  it("hides unused answers and restores their values when the count grows", () => {
    const node = makeQuestionNode(3)
    updateQuestionAnswerWidgets(node)
    expect(node.widgets?.[4].type).toBe("text")
    expect(node.widgets?.[5].type).toBe("hidden")

    const count = node.widgets?.find((widget) => widget.name === "inputcount")
    if (count) count.value = 2
    updateQuestionAnswerWidgets(node)
    expect(node.widgets?.[4].type).toBe("hidden")
    expect(node.widgets?.[4].value).toBe("answer 3")
    expect(node.widgets?.[4].serialize).not.toBe(false)

    if (count) count.value = 3
    updateQuestionAnswerWidgets(node)
    expect(node.widgets?.[4].type).toBe("text")
    expect(node.widgets?.[4].value).toBe("answer 3")
  })

  it("adds one non-serialized update button after inputcount", () => {
    let extension:
      | { nodeCreated?: (node: ComfyNodeLike) => void }
      | undefined
    const app = {
      registerExtension(value: typeof extension) {
        extension = value
      },
    } as unknown as ComfyApp
    registerLlamaCppDecision(app)
    const node = makeQuestionNode(2)

    extension?.nodeCreated?.(node)
    const button = node.widgets?.find((widget) => widget.name === "Update inputs")

    expect(button?.type).toBe("button")
    expect(button?.serialize).toBe(false)
    expect(node.widgets?.indexOf(button as ComfyWidget)).toBe(2)
  })
})
