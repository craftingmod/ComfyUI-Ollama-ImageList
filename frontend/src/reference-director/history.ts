export interface HistoryState<T> {
  past: T[];
  present: T;
  future: T[];
  mergeKey?: string;
}

export function createHistory<T>(initial: T): HistoryState<T> {
  return { past: [], present: initial, future: [] };
}

export function commitHistory<T>(
  history: HistoryState<T>,
  next: T,
  options: { mergeKey?: string; limit?: number } = {},
): HistoryState<T> {
  if (Object.is(history.present, next)) return history;
  const shouldMerge = options.mergeKey !== undefined && options.mergeKey === history.mergeKey;
  const past = shouldMerge ? history.past : [...history.past, history.present];
  const limit = Math.max(1, options.limit ?? 100);
  const boundedPast = past.length > limit ? past.slice(past.length - limit) : past;
  return {
    past: boundedPast,
    present: next,
    future: [],
    ...(options.mergeKey ? { mergeKey: options.mergeKey } : {}),
  };
}

export function undoHistory<T>(history: HistoryState<T>): HistoryState<T> {
  const present = history.past[history.past.length - 1];
  if (present === undefined) return history;
  return {
    past: history.past.slice(0, -1),
    present,
    future: [history.present, ...history.future],
  };
}

export function redoHistory<T>(history: HistoryState<T>): HistoryState<T> {
  const [present, ...future] = history.future;
  if (present === undefined) return history;
  return { past: [...history.past, history.present], present, future };
}

export function canUndo<T>(history: HistoryState<T>): boolean {
  return history.past.length > 0;
}

export function canRedo<T>(history: HistoryState<T>): boolean {
  return history.future.length > 0;
}

export class LocalHistory<T> {
  #history: HistoryState<T>;
  #limit: number;

  constructor(initial: T, limit = 100) {
    this.#history = createHistory(initial);
    this.#limit = Math.max(1, limit);
  }

  get value(): T {
    return this.#history.present;
  }

  get canUndo(): boolean {
    return canUndo(this.#history);
  }

  get canRedo(): boolean {
    return canRedo(this.#history);
  }

  commit(value: T, options: { mergeKey?: string } = {}): T {
    this.#history = commitHistory(this.#history, value, { limit: this.#limit, ...options });
    return value;
  }

  replace(value: T): T {
    this.#history = { ...this.#history, present: value };
    return value;
  }

  undo(): T {
    this.#history = undoHistory(this.#history);
    return this.value;
  }

  redo(): T {
    this.#history = redoHistory(this.#history);
    return this.value;
  }
}
