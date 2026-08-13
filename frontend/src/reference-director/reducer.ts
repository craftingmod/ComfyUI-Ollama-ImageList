import {
  isAudioItem,
  isVisualItem,
  type DirectorState,
  type DirectorUiPreferences,
  type ImageEditRecipe,
  type MediaItem,
  type TimeRange,
} from "./types";
import { validateDirectorState } from "./validation";

export type DirectorChannel = "visual" | "audio";

export type DirectorAction =
  | { type: "replace"; state: DirectorState }
  | { type: "add"; item: MediaItem }
  | { type: "remove"; id: string }
  | { type: "set-caption"; id: string; caption: string; channel?: DirectorChannel }
  | { type: "toggle"; id: string; channel: DirectorChannel }
  | { type: "reorder"; channel: DirectorChannel; id: string; toIndex: number }
  | { type: "move"; channel: DirectorChannel; id: string; delta: -1 | 1 }
  | { type: "apply-image-edit"; id: string; edit: ImageEditRecipe; source?: MediaItem["source"] }
  | { type: "apply-time-range"; id: string; crop?: TimeRange }
  | { type: "set-ui"; values: Partial<DirectorUiPreferences> };

function replaceItem(state: DirectorState, item: MediaItem): DirectorState {
  return { ...state, items: { ...state.items, [item.id]: item } };
}

function moveInOrder(order: string[], id: string, toIndex: number): string[] {
  const fromIndex = order.indexOf(id);
  if (fromIndex < 0) return order;
  const next = order.filter((candidate) => candidate !== id);
  const bounded = Math.max(0, Math.min(next.length, toIndex));
  next.splice(bounded, 0, id);
  return next.every((candidate, index) => candidate === order[index]) ? order : next;
}

export function directorReducer(state: DirectorState, action: DirectorAction): DirectorState {
  switch (action.type) {
    case "replace":
      return validateDirectorState(action.state).state;
    case "add": {
      if (state.items[action.item.id]) return state;
      return {
        ...state,
        items: { ...state.items, [action.item.id]: action.item },
        visualOrder: isVisualItem(action.item) ? [...state.visualOrder, action.item.id] : state.visualOrder,
        audioOrder: isAudioItem(action.item) ? [...state.audioOrder, action.item.id] : state.audioOrder,
      };
    }
    case "remove": {
      if (!state.items[action.id]) return state;
      const items = { ...state.items };
      delete items[action.id];
      return {
        ...state,
        items,
        visualOrder: state.visualOrder.filter((id) => id !== action.id),
        audioOrder: state.audioOrder.filter((id) => id !== action.id),
      };
    }
    case "set-caption": {
      const item = state.items[action.id];
      if (!item) return state;
      const caption = action.caption.slice(0, 16_384);
      if (item.kind === "video" && action.channel === "audio") {
        return replaceItem(state, { ...item, audioCaptionOverride: caption });
      }
      return replaceItem(state, { ...item, caption });
    }
    case "toggle": {
      const item = state.items[action.id];
      if (!item) return state;
      if (action.channel === "visual" && isVisualItem(item)) {
        return replaceItem(state, { ...item, visualEnabled: !item.visualEnabled });
      }
      if (action.channel === "audio" && isAudioItem(item)) {
        return replaceItem(state, { ...item, audioEnabled: !item.audioEnabled });
      }
      return state;
    }
    case "reorder": {
      const key = action.channel === "visual" ? "visualOrder" : "audioOrder";
      const next = moveInOrder(state[key], action.id, action.toIndex);
      return next === state[key] ? state : { ...state, [key]: next };
    }
    case "move": {
      const order = action.channel === "visual" ? state.visualOrder : state.audioOrder;
      const index = order.indexOf(action.id);
      if (index < 0) return state;
      const target = Math.max(0, Math.min(order.length - 1, index + action.delta));
      if (target === index) return state;
      return directorReducer(state, {
        type: "reorder",
        channel: action.channel,
        id: action.id,
        toIndex: target,
      });
    }
    case "apply-image-edit": {
      const item = state.items[action.id];
      if (!item || item.kind !== "image") return state;
      return replaceItem(state, {
        ...item,
        ...(action.source ? { source: action.source } : {}),
        edit: action.edit,
      });
    }
    case "apply-time-range": {
      const item = state.items[action.id];
      if (!item || item.kind === "image") return state;
      if (action.crop) return replaceItem(state, { ...item, crop: action.crop });
      const { crop: _discarded, ...withoutCrop } = item;
      return replaceItem(state, withoutCrop);
    }
    case "set-ui":
      return { ...state, ui: { ...state.ui, ...action.values } };
  }
}
