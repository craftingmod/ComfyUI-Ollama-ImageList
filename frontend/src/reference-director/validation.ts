import {
  DEFAULT_UI_PREFERENCES,
  DIRECTOR_STATE_VERSION,
  VIDEO_AUDIO_POLICY,
  createEmptyDirectorState,
  isAudioItem,
  isVisualItem,
  type BackgroundEdit,
  type DirectorState,
  type DirectorUiPreferences,
  type ImageEditRecipe,
  type MediaItem,
  type MediaKind,
  type MediaSource,
  type NormalizedCrop,
  type TimeRange,
} from "./types";

export interface DirectorValidationResult {
  state: DirectorState;
  issues: string[];
  migrated: boolean;
}

const PREVIEW_PIXEL_CHOICES = [262_144, 1_000_000, 2_000_000, 4_000_000] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function captionValue(value: unknown): string {
  return stringValue(value).slice(0, 16_384);
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function readAliased(record: Record<string, unknown>, camel: string, snake: string): unknown {
  return record[camel] ?? record[snake];
}

function sanitizeSource(value: unknown): MediaSource | undefined {
  if (!isRecord(value)) return undefined;
  const path = stringValue(value.path);
  const mime = stringValue(readAliased(value, "mime", "mime_type")).toLowerCase();
  const sha256 = stringValue(value.sha256).toLowerCase();
  const pathParts = path.split("/");
  if (
    !path ||
    path.length > 512 ||
    path.includes("\\") ||
    path.includes("\0") ||
    path.startsWith("/") ||
    pathParts[0]?.toLowerCase() === "input" ||
    pathParts.some((part) => !part || part === "." || part === ".." || part.includes(":")) ||
    !/^[a-z0-9][a-z0-9.+-]*\/[a-z0-9][a-z0-9.+-]*$/.test(mime) ||
    !/^[0-9a-f]{64}$/.test(sha256)
  ) return undefined;
  const size = finiteNumber(value.size);
  const revision = finiteNumber(value.revision);
  return {
    path,
    mime,
    sha256,
    ...(size !== undefined && Number.isInteger(size) && size >= 0 ? { size } : {}),
    ...(revision !== undefined && Number.isInteger(revision) && revision >= 0 ? { revision } : {}),
  };
}

function sanitizeTimeRange(value: unknown): TimeRange | undefined {
  if (!isRecord(value)) return undefined;
  const start = finiteNumber(value.start);
  const end = finiteNumber(value.end);
  if (start === undefined || end === undefined || start < 0 || end <= start) return undefined;
  return { start, end };
}

function sanitizeNormalizedCrop(value: unknown): NormalizedCrop | undefined {
  if (!isRecord(value)) return undefined;
  const x = finiteNumber(value.x);
  const y = finiteNumber(value.y);
  const width = finiteNumber(value.width);
  const height = finiteNumber(value.height);
  if (
    x === undefined ||
    y === undefined ||
    width === undefined ||
    height === undefined ||
    x < 0 ||
    y < 0 ||
    width <= 0 ||
    height <= 0 ||
    x + width > 1.000_001 ||
    y + height > 1.000_001
  ) {
    return undefined;
  }
  return { x, y, width, height };
}

function sanitizeBackground(value: unknown): BackgroundEdit | undefined {
  if (!isRecord(value) || (value.mode !== "transparent" && value.mode !== "solid")) {
    return undefined;
  }
  const color = stringValue(value.color, "#ffffff");
  return { mode: value.mode, color: /^#[\da-f]{6}$/i.test(color) ? color : "#ffffff" };
}

function sanitizeImageEdit(value: unknown): ImageEditRecipe | undefined {
  if (!isRecord(value)) return undefined;
  const recipe: ImageEditRecipe = {};
  const crop = sanitizeNormalizedCrop(value.crop);
  const background = sanitizeBackground(value.background);
  const mask = sanitizeSource(value.mask ?? value.mask_source);
  const revision = finiteNumber(value.revision);
  if (crop) recipe.crop = crop;
  if (typeof value.flipX === "boolean") recipe.flipX = value.flipX;
  else if (typeof value.flip_x === "boolean") recipe.flipX = value.flip_x;
  if (typeof value.flipY === "boolean") recipe.flipY = value.flipY;
  else if (typeof value.flip_y === "boolean") recipe.flipY = value.flip_y;
  if (typeof value.removeBackground === "boolean") recipe.removeBackground = value.removeBackground;
  else if (typeof value.remove_background === "boolean") recipe.removeBackground = value.remove_background;
  if (background) recipe.background = background;
  if (mask?.mime.startsWith("image/")) {
    recipe.mask = mask;
    recipe.maskMode = value.maskMode === "erase" || value.mask_mode === "erase" ? "erase" : "keep";
  }
  if (revision !== undefined && revision >= 0) recipe.revision = Math.floor(revision);
  return Object.keys(recipe).length > 0 ? recipe : undefined;
}

function sanitizeKind(value: unknown): MediaKind | undefined {
  return value === "image" || value === "audio" || value === "video" ? value : undefined;
}

function sanitizeItem(key: string, value: unknown): MediaItem | undefined {
  if (!isRecord(value)) return undefined;
  const id = stringValue(value.id, key);
  const kind = sanitizeKind(value.kind);
  const source = sanitizeSource(value.source);
  if (!id || id !== key || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id) || !kind || !source || !source.mime.startsWith(`${kind}/`)) return undefined;
  const caption = captionValue(value.caption);

  if (kind === "image") {
    const item: MediaItem = {
      id,
      kind,
      source,
      caption,
      visualEnabled: booleanValue(readAliased(value, "visualEnabled", "visual_enabled"), true),
    };
    const edit = sanitizeImageEdit(value.edit);
    if (edit) item.edit = edit;
    return item;
  }

  const crop = sanitizeTimeRange(value.crop);
  if (kind === "audio") {
    const item: MediaItem = {
      id,
      kind,
      source,
      caption,
      audioEnabled: booleanValue(readAliased(value, "audioEnabled", "audio_enabled"), true),
    };
    if (crop) item.crop = crop;
    return item;
  }

  const item: MediaItem = {
    id,
    kind,
    source,
    caption,
    visualEnabled: booleanValue(readAliased(value, "visualEnabled", "visual_enabled"), true),
    audioEnabled: booleanValue(readAliased(value, "audioEnabled", "audio_enabled"), true),
  };
  const audioCaption = readAliased(value, "audioCaptionOverride", "audio_caption_override");
  if (typeof audioCaption === "string") item.audioCaptionOverride = audioCaption.slice(0, 16_384);
  if (crop) item.crop = crop;
  return item;
}

function sanitizeUi(value: unknown): DirectorUiPreferences {
  if (!isRecord(value)) return { ...DEFAULT_UI_PREFERENCES };
  const aspect = stringValue(readAliased(value, "cardAspectRatio", "card_aspect_ratio"));
  const preview = finiteNumber(readAliased(value, "previewMaxPixels", "preview_max_pixels"));
  const peaks = finiteNumber(readAliased(value, "waveformPeaks", "waveform_peaks"));
  const channel = readAliased(value, "activeChannel", "active_channel");
  const previewChoice = preview === undefined
    ? DEFAULT_UI_PREFERENCES.previewMaxPixels
    : PREVIEW_PIXEL_CHOICES.reduce((closest, candidate) =>
      Math.abs(candidate - preview) < Math.abs(closest - preview) ? candidate : closest,
    );
  return {
    cardAspectRatio: /^\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?$/.test(aspect)
      ? aspect
      : DEFAULT_UI_PREFERENCES.cardAspectRatio,
    previewMaxPixels: previewChoice,
    waveformPeaks:
      peaks !== undefined ? Math.min(500, Math.max(200, Math.floor(peaks))) : DEFAULT_UI_PREFERENCES.waveformPeaks,
    activeChannel: channel === "audio" ? "audio" : "visual",
  };
}

function sanitizeOrder(
  value: unknown,
  items: Record<string, MediaItem>,
  predicate: (item: MediaItem) => boolean,
  issues: string[],
  label: string,
): string[] {
  const order: string[] = [];
  const seen = new Set<string>();
  if (Array.isArray(value)) {
    for (const candidate of value) {
      if (typeof candidate !== "string" || seen.has(candidate)) continue;
      const item = items[candidate];
      if (!item || !predicate(item)) continue;
      seen.add(candidate);
      order.push(candidate);
    }
  } else {
    issues.push(`${label} was not an array.`);
  }
  for (const item of Object.values(items)) {
    if (predicate(item) && !seen.has(item.id)) {
      order.push(item.id);
      issues.push(`${label} was missing item ${item.id}.`);
    }
  }
  return order;
}

export function validateDirectorState(value: unknown): DirectorValidationResult {
  if (!isRecord(value)) {
    return { state: createEmptyDirectorState(), issues: ["State was not an object."], migrated: false };
  }
  const issues: string[] = [];
  const rawVersion = value.version;
  const migrated = rawVersion === 0 || rawVersion === undefined;
  if (rawVersion !== DIRECTOR_STATE_VERSION && !migrated) {
    return {
      state: createEmptyDirectorState(),
      issues: [`Unsupported Reference Director state version: ${String(rawVersion)}.`],
      migrated: false,
    };
  }

  const items: Record<string, MediaItem> = {};
  if (isRecord(value.items)) {
    const counts: Record<MediaKind, number> = { image: 0, audio: 0, video: 0 };
    const limits: Record<MediaKind, number> = { image: 32, audio: 8, video: 4 };
    for (const [id, rawItem] of Object.entries(value.items)) {
      const item = sanitizeItem(id, rawItem);
      if (item && counts[item.kind] < limits[item.kind]) {
        items[id] = item;
        counts[item.kind] += 1;
      }
      else if (item) issues.push(`Media item ${id} exceeded the ${item.kind} limit and was discarded.`);
      else issues.push(`Invalid media item ${id} was discarded.`);
    }
  } else {
    issues.push("items was not an object.");
  }

  const visualOrder = sanitizeOrder(
    readAliased(value, "visualOrder", "visual_order"),
    items,
    isVisualItem,
    issues,
    "visualOrder",
  );
  const audioOrder = sanitizeOrder(
    readAliased(value, "audioOrder", "audio_order"),
    items,
    isAudioItem,
    issues,
    "audioOrder",
  );
  if (value.videoAudioPolicy !== undefined && value.videoAudioPolicy !== VIDEO_AUDIO_POLICY) {
    issues.push("Unsupported videoAudioPolicy was reset to preserve.");
  }

  return {
    state: {
      version: DIRECTOR_STATE_VERSION,
      items,
      visualOrder,
      audioOrder,
      videoAudioPolicy: VIDEO_AUDIO_POLICY,
      ui: sanitizeUi(value.ui),
    },
    issues,
    migrated,
  };
}
