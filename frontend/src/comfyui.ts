export interface ComfyWidget {
  name: string;
  value: unknown;
  callback?: (value: unknown, ...args: unknown[]) => unknown;
  options?: Record<string, unknown> & { values?: string[] };
  disabled?: boolean;
  serialize?: boolean;
  serializeValue?: (node: ComfyNode, index: number) => unknown | Promise<unknown>;
  beforeQueued?: () => void | Promise<void>;
  onRemove?: () => void;
}

export interface ComfyNodeInput {
  name: string;
  link?: unknown;
}

export interface ComfyGraphLike {
  beforeChange?(node?: ComfyNode): void;
  afterChange?(node?: ComfyNode | null): void;
}

export interface DomWidgetOptions {
  serialize?: boolean;
  hideOnZoom?: boolean;
  getValue?: () => unknown;
  setValue?: (value: unknown) => void;
  getMinHeight?: () => number;
  getMaxHeight?: () => number;
  onDraw?: (widget: ComfyWidget) => void;
}

export interface ComfyNode {
  id?: string | number;
  comfyClass?: string;
  type?: string;
  widgets?: ComfyWidget[];
  inputs?: ComfyNodeInput[];
  properties?: Record<string, unknown>;
  size?: [number, number];
  graph?: ComfyGraphLike | null;
  addWidget(
    type: string,
    name: string,
    value: unknown,
    callback: (...args: unknown[]) => unknown,
    options?: Record<string, unknown>,
  ): ComfyWidget;
  addDOMWidget(
    name: string,
    type: string,
    element: HTMLElement,
    options?: DomWidgetOptions,
  ): ComfyWidget;
  setDirtyCanvas(foreground?: boolean, background?: boolean): void;
  setSize?(size: [number, number]): void;
  onNodeCreated?: (...args: unknown[]) => unknown;
  onConnectionsChange?: (...args: unknown[]) => unknown;
  onRemoved?: (...args: unknown[]) => unknown;
}

export interface ComfyNodeConstructor {
  prototype: ComfyNode;
}

export interface ComfyNodeData {
  name: string;
}

export interface ComfyCustomWidgetInput {
  [key: string]: unknown;
}

export interface CustomWidgetResult {
  widget: ComfyWidget;
}

export type CustomWidgetFactory = (
  node: ComfyNode,
  inputName: string,
  inputData: unknown,
  app: ComfyAppLike,
) => CustomWidgetResult;

export interface ComfyExtension {
  name: string;
  beforeRegisterNodeDef?: (
    nodeType: ComfyNodeConstructor,
    nodeData: ComfyNodeData,
    app: ComfyAppLike,
  ) => void | Promise<void>;
  getCustomWidgets?: () => Record<string, CustomWidgetFactory>;
}

export interface ComfyAppLike {
  canvas?: {
    emitBeforeChange?(): void;
    emitAfterChange?(): void;
  };
  extensionManager: {
    toast: {
      add(options: {
        severity: "error" | "warn" | "info" | "success";
        summary: string;
        detail: string;
        life?: number;
      }): void;
    };
  };
  registerExtension(extension: ComfyExtension): void;
}

export interface ComfyApiLike {
  fetchApi(route: string, init?: RequestInit): Promise<Response>;
  apiURL?(route: string): string;
}
