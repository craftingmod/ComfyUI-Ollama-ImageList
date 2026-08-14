import type { ComfyApiLike } from "../comfyui";
import type {
  ImageEditRecipe,
  MediaKind,
  MediaMetadata,
  MediaSource,
  TimeRange,
} from "./types";

export const REFERENCE_DIRECTOR_API_BASE = "/ollama_multimodal/reference_director";
export const MAX_REFERENCE_DIRECTOR_JSON_BYTES = 1024 * 1024;

interface ApiSourceDescriptor {
  path?: unknown;
  mime?: unknown;
  mime_type?: unknown;
  sha256?: unknown;
  size?: unknown;
  revision?: unknown;
  type?: unknown;
  subfolder?: unknown;
  filename?: unknown;
}

export interface UploadedReference {
  kind: MediaKind;
  source: MediaSource;
  metadata: MediaMetadata;
}

export interface ProxyResult {
  url: string;
  cacheKey?: string;
  source?: MediaSource;
}

export interface WaveformResult {
  pairs: ReadonlyArray<readonly [number, number]>;
  duration?: number;
  cacheKey?: string;
}

export interface ApplyEditResult {
  source: MediaSource;
  edit: ImageEditRecipe;
  proxyUrl?: string;
  metadata?: MediaMetadata;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mediaKind(value: unknown): MediaKind | undefined {
  return value === "image" || value === "audio" || value === "video" ? value : undefined;
}

function apiAssetUrl(api: ComfyApiLike, value: string): string {
  if (!api.apiURL || !value.startsWith("/api/")) return value;
  return api.apiURL(value.slice("/api".length));
}

function apiPath(source: ApiSourceDescriptor): string {
  if (typeof source.path === "string" && source.path) return source.path;
  const subfolder = typeof source.subfolder === "string" ? source.subfolder.replace(/\\/g, "/") : "";
  const filename = typeof source.filename === "string" ? source.filename : "";
  return [subfolder, filename]
    .filter((segment) => segment.length > 0)
    .join("/")
    .replace(/\/{2,}/g, "/");
}

export function normalizeApiSource(value: unknown): MediaSource {
  if (!isRecord(value)) throw new Error("The server returned an invalid media source.");
  const source = value as ApiSourceDescriptor;
  const path = apiPath(source);
  const mime = typeof source.mime === "string" ? source.mime : source.mime_type;
  const sha256 = source.sha256;
  if (!path || typeof mime !== "string" || !mime || typeof sha256 !== "string" || !sha256) {
    throw new Error("The server returned an incomplete media source.");
  }
  const size = source.size;
  const revision = source.revision;
  return {
    path,
    mime,
    sha256,
    ...(typeof size === "number" && Number.isFinite(size) && size >= 0 ? { size } : {}),
    ...(typeof revision === "number" && Number.isInteger(revision) && revision >= 0 ? { revision } : {}),
  };
}

function normalizeMetadata(value: unknown): MediaMetadata {
  if (!isRecord(value)) return {};
  const metadata: MediaMetadata = {};
  const mappings = [
    ["width", "width"],
    ["height", "height"],
    ["duration", "duration"],
    ["frameRate", "frame_rate"],
    ["sampleRate", "sample_rate"],
    ["channels", "channels"],
  ] as const;
  for (const [target, source] of mappings) {
    const candidate = value[target] ?? value[source];
    if (typeof candidate === "number" && Number.isFinite(candidate)) metadata[target] = candidate;
  }
  const hasAudio = value.hasAudio ?? value.has_audio;
  if (typeof hasAudio === "boolean") metadata.hasAudio = hasAudio;
  return metadata;
}

async function payloadOrError(response: Response): Promise<unknown> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`ComfyUI returned HTTP ${response.status}.`);
  }
  if (!response.ok) {
    const rawError = isRecord(payload) ? payload.error : undefined;
    const detail = typeof rawError === "string"
      ? rawError
      : isRecord(rawError) && typeof rawError.message === "string"
        ? typeof rawError.code === "string"
          ? `${rawError.message} (${rawError.code})`
          : rawError.message
        : undefined;
    throw new Error(detail ?? `ComfyUI returned HTTP ${response.status}.`);
  }
  return payload;
}

export class ReferenceDirectorApi {
  constructor(private readonly api: ComfyApiLike) {}

  async upload(file: File, signal?: AbortSignal): Promise<UploadedReference> {
    const form = new FormData();
    form.append("file", file, file.name);
    const payload = await payloadOrError(
      await this.api.fetchApi(`${REFERENCE_DIRECTOR_API_BASE}/upload`, {
        method: "POST",
        body: form,
        ...(signal ? { signal } : {}),
      }),
    );
    if (!isRecord(payload)) throw new Error("The server returned an invalid upload result.");
    const kind = mediaKind(payload.kind);
    if (!kind || payload.source === undefined) throw new Error("The server returned an invalid upload result.");
    return {
      kind,
      source: normalizeApiSource(payload.source),
      metadata: normalizeMetadata(payload.metadata),
    };
  }

  async metadata(source: MediaSource, signal?: AbortSignal): Promise<MediaMetadata> {
    const payload = await this.#post("metadata", { source }, signal);
    return normalizeMetadata(isRecord(payload) && "metadata" in payload ? payload.metadata : payload);
  }

  audioPreviewUrl(source: MediaSource): string {
    const route = `${REFERENCE_DIRECTOR_API_BASE}/audio_preview?${new URLSearchParams({
      source: JSON.stringify(source),
    })}`;
    return this.api.apiURL ? this.api.apiURL(route) : route;
  }

  videoPreviewUrl(source: MediaSource): string {
    const route = `${REFERENCE_DIRECTOR_API_BASE}/video_preview?${new URLSearchParams({
      source: JSON.stringify(source),
    })}`;
    return this.api.apiURL ? this.api.apiURL(route) : route;
  }

  async imageProxy(
    source: MediaSource,
    maxPixels: number,
    signal?: AbortSignal,
  ): Promise<ProxyResult> {
    const payload = await this.#post("image_proxy", { source, maxPixels }, signal);
    if (!isRecord(payload) || typeof payload.url !== "string") {
      throw new Error("The server returned an invalid preview URL.");
    }
    const result: ProxyResult = { url: apiAssetUrl(this.api, payload.url) };
    const cacheKey = payload.cacheKey ?? payload.cache_key;
    if (typeof cacheKey === "string") result.cacheKey = cacheKey;
    if (payload.source !== undefined) result.source = normalizeApiSource(payload.source);
    return result;
  }

  async waveform(
    source: MediaSource,
    peaks: number,
    crop?: TimeRange,
    signal?: AbortSignal,
  ): Promise<WaveformResult> {
    const payload = await this.#post("waveform", { source, peakCount: peaks, ...(crop ? { crop } : {}) }, signal);
    if (!isRecord(payload) || !Array.isArray(payload.pairs)) {
      throw new Error("The server returned invalid waveform data.");
    }
    const pairs = payload.pairs.flatMap((pair): Array<readonly [number, number]> => {
      if (
        Array.isArray(pair) &&
        typeof pair[0] === "number" &&
        Number.isFinite(pair[0]) &&
        typeof pair[1] === "number" &&
        Number.isFinite(pair[1])
      ) {
        return [[Math.max(-1, pair[0]), Math.min(1, pair[1])] as const];
      }
      return [];
    });
    const result: WaveformResult = { pairs };
    const duration = payload.duration;
    const cacheKey = payload.cacheKey ?? payload.cache_key;
    if (typeof duration === "number" && Number.isFinite(duration)) result.duration = duration;
    if (typeof cacheKey === "string") result.cacheKey = cacheKey;
    return result;
  }

  async applyEdit(
    source: MediaSource,
    edit: ImageEditRecipe,
    signal?: AbortSignal,
  ): Promise<ApplyEditResult> {
    const expectedRevision = source.revision ?? Math.max(0, (edit.revision ?? 1) - 1);
    const payload = await this.#post("apply_edit", { source, edit, expectedRevision }, signal);
    if (!isRecord(payload) || payload.source === undefined || !isRecord(payload.edit)) {
      throw new Error("The server returned an invalid edit result.");
    }
    const result: ApplyEditResult = {
      source: normalizeApiSource(payload.source),
      edit: payload.edit as ImageEditRecipe,
    };
    const proxyUrl = payload.proxyUrl ?? payload.proxy_url;
    if (typeof proxyUrl === "string") result.proxyUrl = apiAssetUrl(this.api, proxyUrl);
    if (payload.metadata !== undefined) result.metadata = normalizeMetadata(payload.metadata);
    return result;
  }

  async #post(endpoint: string, body: unknown, signal?: AbortSignal): Promise<unknown> {
    const serialized = JSON.stringify(body);
    if (new TextEncoder().encode(serialized).byteLength > MAX_REFERENCE_DIRECTOR_JSON_BYTES) {
      throw new Error("The Reference Director request exceeds the 1 MiB JSON limit.");
    }
    return payloadOrError(
      await this.api.fetchApi(`${REFERENCE_DIRECTOR_API_BASE}/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: serialized,
        ...(signal ? { signal } : {}),
      }),
    );
  }
}
