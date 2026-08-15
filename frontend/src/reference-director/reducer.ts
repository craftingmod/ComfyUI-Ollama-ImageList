import {
  isAudioItem,
  type DirectorState,
  type DirectorUiPreferences,
  type ImageEditRecipe,
  type MediaItem,
  type TimeRange,
} from "./types";
import { validateDirectorState } from "./validation";

export type DirectorChannel = "image" | "video" | "audio";

export type DirectorAction =
  | { type: "replace"; state: DirectorState }
  | { type: "add"; item: MediaItem }
  | { type: "clear" }
  | { type: "remove"; id: string }
  | { type: "set-caption"; id: string; caption: string; channel?: DirectorChannel }
  | { type: "toggle"; id: string; channel: DirectorChannel }
  | { type: "reorder"; channel: DirectorChannel; id: string; toIndex: number }
  | { type: "move"; channel: DirectorChannel; id: string; delta: -1 | 1 }
  | { type: "apply-image-edit"; id: string; edit: ImageEditRecipe; source?: MediaItem["source"]; caption?: string }
  | { type: "restore-image-original"; id: string; caption?: string }
  | { type: "apply-time-range"; id: string; crop?: TimeRange; caption?: string; channel?: DirectorChannel }
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
        imageOrder: action.item.kind === "image" ? [...state.imageOrder, action.item.id] : state.imageOrder,
        videoOrder: action.item.kind === "video" ? [...state.videoOrder, action.item.id] : state.videoOrder,
        audioOrder: isAudioItem(action.item) ? [...state.audioOrder, action.item.id] : state.audioOrder,
      };
    }
    case "clear":
      return Object.keys(state.items).length === 0
        ? state
        : { ...state, items: {}, imageOrder: [], videoOrder: [], audioOrder: [] };
    case "remove": {
      if (!state.items[action.id]) return state;
      const items = { ...state.items };
      delete items[action.id];
      return {
        ...state,
        items,
        imageOrder: state.imageOrder.filter((id) => id !== action.id),
        videoOrder: state.videoOrder.filter((id) => id !== action.id),
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
      if (action.channel === "image" && item.kind === "image") {
        return replaceItem(state, { ...item, imageEnabled: !item.imageEnabled });
      }
      if (action.channel === "video" && item.kind === "video") {
        return replaceItem(state, { ...item, videoEnabled: !item.videoEnabled });
      }
      if (action.channel === "audio" && isAudioItem(item)) {
        return replaceItem(state, { ...item, audioEnabled: !item.audioEnabled });
      }
      return state;
    }
    case "reorder": {
      const key = action.channel === "image" ? "imageOrder" : action.channel === "video" ? "videoOrder" : "audioOrder";
      const next = moveInOrder(state[key], action.id, action.toIndex);
      return next === state[key] ? state : { ...state, [key]: next };
    }
    case "move": {
      const order = action.channel === "image" ? state.imageOrder : action.channel === "video" ? state.videoOrder : state.audioOrder;
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
      const edited = replaceItem(state, {
        ...item,
        ...(action.source ? { source: action.source } : {}),
        edit: action.edit,
      });
      return action.caption === undefined
        ? edited
        : directorReducer(edited, { type: "set-caption", id: action.id, caption: action.caption });
    }
    case "restore-image-original": {
      const item = state.items[action.id];
      if (!item || item.kind !== "image") return state;
      const { edit: _discarded, ...withoutEdit } = item;
      return replaceItem(state, {
        ...withoutEdit,
        source: item.originalSource,
        caption: action.caption === undefined ? item.caption : action.caption.slice(0, 16_384),
      });
    }
    case "apply-time-range": {
      const item = state.items[action.id];
      if (!item || item.kind === "image") return state;
      if (action.crop) {
        const trimmed = replaceItem(state, { ...item, crop: action.crop });
        return action.caption === undefined
          ? trimmed
          : directorReducer(trimmed, {
            type: "set-caption",
            id: action.id,
            caption: action.caption,
            ...(action.channel ? { channel: action.channel } : {}),
          });
      }
      const { crop: _discarded, ...withoutCrop } = item;
      return replaceItem(state, withoutCrop);
    }
    case "set-ui":
      return { ...state, ui: { ...state.ui, ...action.values } };
  }
}
