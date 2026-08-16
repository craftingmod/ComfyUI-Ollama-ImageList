export type ComfyWidget = {
  name: string
  value?: unknown
  disabled?: boolean
  serialize?: boolean
  options?: { values?: string[]; [key: string]: unknown }
  callback?: (value: unknown, ...args: unknown[]) => unknown
}

export type ComfyInput = {
  name: string
  link?: number | null
}

export type ComfyNodeLike = {
  widgets?: ComfyWidget[]
  inputs?: ComfyInput[]
  onConnectionsChange?: (this: ComfyNodeLike, ...args: unknown[]) => unknown
  setDirtyCanvas(foreground?: boolean, background?: boolean): void
  addWidget(type: string, name: string, value: unknown, callback: () => void): ComfyWidget
}

export type ComfyNodeTypeLike = {
  prototype: {
    onNodeCreated?: (this: ComfyNodeLike, ...args: unknown[]) => unknown
  }
}

export type ComfyNodeDefinitionLike = {
  name: string
}

export function getWidget(node: ComfyNodeLike, name: string): ComfyWidget | undefined {
  return node.widgets?.find((widget) => widget.name === name)
}
