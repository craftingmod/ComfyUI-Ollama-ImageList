export const DIRECTOR_STATE_VERSION = 1 as const;
export const VIDEO_AUDIO_POLICY = "preserve" as const;

export type MediaKind = "image" | "audio" | "video";

export interface MediaSource {
  path: string;
  mime: string;
  sha256: string;
  size?: number;
  revision?: number;
}

export interface NormalizedCrop {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TimeRange {
  start: number;
  end: number;
}

export interface BackgroundEdit {
  mode: "transparent" | "solid";
  color: string;
}

export interface ImageEditRecipe {
  crop?: NormalizedCrop;
  flipX?: boolean;
  flipY?: boolean;
  removeBackground?: boolean;
  background?: BackgroundEdit;
  mask?: MediaSource;
  maskMode?: "keep" | "erase";
  revision?: number;
}

interface BaseItem {
  id: string;
  kind: MediaKind;
  source: MediaSource;
  sourceFilename?: string;
  caption: string;
}

export interface ImageItem extends BaseItem {
  kind: "image";
  imageEnabled: boolean;
  edit?: ImageEditRecipe;
}

export interface AudioItem extends BaseItem {
  kind: "audio";
  audioEnabled: boolean;
  crop?: TimeRange;
}

export interface VideoItem extends BaseItem {
  kind: "video";
  videoEnabled: boolean;
  audioEnabled: boolean;
  audioCaptionOverride?: string;
  crop?: TimeRange;
}

export type MediaItem = ImageItem | AudioItem | VideoItem;

export interface DirectorUiPreferences {
  cardAspectRatio: string;
  gridColumns: number;
  previewMaxPixels: number;
  waveformPeaks: number;
}

export interface DirectorState {
  version: typeof DIRECTOR_STATE_VERSION;
  items: Record<string, MediaItem>;
  imageOrder: string[];
  videoOrder: string[];
  audioOrder: string[];
  videoAudioPolicy: typeof VIDEO_AUDIO_POLICY;
  ui: DirectorUiPreferences;
}

export interface MediaMetadata {
  width?: number;
  height?: number;
  duration?: number;
  frameRate?: number;
  sampleRate?: number;
  channels?: number;
  hasAudio?: boolean;
}

export interface ItemRuntime {
  loading: boolean;
  error?: string;
  previewUrl?: string;
  waveform?: ReadonlyArray<readonly [number, number]>;
  metadata?: MediaMetadata;
}

export const DEFAULT_UI_PREFERENCES: DirectorUiPreferences = {
  cardAspectRatio: "4 / 3",
  gridColumns: 3,
  previewMaxPixels: 1_000_000,
  waveformPeaks: 300,
};

export function createEmptyDirectorState(): DirectorState {
  return {
    version: DIRECTOR_STATE_VERSION,
    items: {},
    imageOrder: [],
    videoOrder: [],
    audioOrder: [],
    videoAudioPolicy: VIDEO_AUDIO_POLICY,
    ui: { ...DEFAULT_UI_PREFERENCES },
  };
}

export function createMediaItem(
  kind: MediaKind,
  source: MediaSource,
  id: string = globalThis.crypto?.randomUUID?.() ?? `reference-${Date.now()}-${Math.random()}`,
  options: { hasAudio?: boolean } = {},
): MediaItem {
  const sourceFilename = source.path.split("/").pop() ?? source.path;
  const base = { id, kind, source, sourceFilename, caption: "" };
  if (kind === "image") {
    return { ...base, kind, imageEnabled: true };
  }
  if (kind === "audio") {
    return { ...base, kind, audioEnabled: true };
  }
  return { ...base, kind, videoEnabled: true, audioEnabled: options.hasAudio !== false };
}

export function isAudioItem(item: MediaItem): item is AudioItem | VideoItem {
  return item.kind === "audio" || item.kind === "video";
}
