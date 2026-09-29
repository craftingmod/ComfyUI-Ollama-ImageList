import type {
  ComfyNodeLike,
  ComfyWidget,
} from "./comfy-types.ts"
import type { ComfyApp } from "@comfyorg/comfyui-frontend-types"
import { getWidget } from "./comfy-types.ts"
import { EXTENSION_NAMES } from "./constants.ts"

const CREATE_QUESTION_CLASS = "OllamaImageList_LlamaCppCreateQuestion"
const MAX_ANSWERS = 26
const originalWidgetTypes = new WeakMap<ComfyWidget, string | undefined>()
const originalComputeSizes = new WeakMap<ComfyWidget, ComfyWidget["computeSize"]>()

function setWidgetVisibility(widget: ComfyWidget, hidden: boolean): void {
  if (!originalWidgetTypes.has(widget)) {
    originalWidgetTypes.set(widget, widget.type)
    originalComputeSizes.set(widget, widget.computeSize)
  }
  widget.type = hidden ? "hidden" : originalWidgetTypes.get(widget)
  widget.computeSize = hidden
    ? () => [0, -4]
    : originalComputeSizes.get(widget)
}

export function updateQuestionAnswerWidgets(node: ComfyNodeLike): void {
  const rawCount = getWidget(node, "inputcount")?.value
  const count =
    typeof rawCount === "number" && Number.isInteger(rawCount)
      ? Math.max(2, Math.min(MAX_ANSWERS, rawCount))
      : 2
  let changed = false
  for (let index = 1; index <= MAX_ANSWERS; index += 1) {
    const widget = getWidget(node, `answer_${index}`)
    if (!widget) continue
    const hidden = index > count
    if ((widget.type === "hidden") !== hidden) {
      setWidgetVisibility(widget, hidden)
      changed = true
    }
  }
  if (changed) node.setDirtyCanvas(true, true)
}

export function registerLlamaCppDecision(app: ComfyApp): void {
  app.registerExtension({
    name: EXTENSION_NAMES.LLAMA_CPP_DECISION,

    nodeCreated(node) {
      const questionNode = node as unknown as ComfyNodeLike & { comfyClass?: string }
      if (questionNode.comfyClass !== CREATE_QUESTION_CLASS) return
      if (getWidget(questionNode, "Update inputs")) return

      const updateButton = questionNode.addWidget(
        "button",
        "Update inputs",
        null,
        () => updateQuestionAnswerWidgets(questionNode),
      )
      updateButton.tooltip = "Apply inputcount to the visible answer widgets."
      updateButton.serialize = false
      const widgets = questionNode.widgets
      const buttonIndex = widgets?.indexOf(updateButton) ?? -1
      const inputCountIndex = widgets?.findIndex((widget) => widget.name === "inputcount") ?? -1
      if (widgets && buttonIndex >= 0 && inputCountIndex >= 0) {
        widgets.splice(buttonIndex, 1)
        widgets.splice(inputCountIndex + 1, 0, updateButton)
      }
      setTimeout(() => updateQuestionAnswerWidgets(questionNode), 0)
    },
  })
}
