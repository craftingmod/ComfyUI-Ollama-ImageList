import type { DirectorState, ImageEditRecipe, MediaSource, TimeRange } from "./types";
import { validateDirectorState } from "./validation";

export interface ExecutionItem {
  id: string;
  kind: "image" | "audio" | "video";
  source: MediaSource;
  caption: string;
  enabled: boolean;
  crop?: TimeRange;
  edit?: ImageEditRecipe;
  derivedFrom?: string;
}

export interface DirectorExecutionProjection {
  version: 1;
  imageOrder: string[];
  videoOrder: string[];
  audioOrder: string[];
  videoAudioPolicy: "preserve";
  images: ExecutionItem[];
  audios: ExecutionItem[];
  videos: ExecutionItem[];
}

function optionalCrop<T extends ExecutionItem>(item: T, crop: TimeRange | undefined): T {
  return crop ? { ...item, crop } : item;
}

function executionSource(source: MediaSource): MediaSource {
  const { revision: _runtimeRevision, ...portable } = source;
  return portable;
}

function executionEdit(edit: ImageEditRecipe): ImageEditRecipe {
  return edit.mask ? { ...edit, mask: executionSource(edit.mask) } : edit;
}

export function projectDirectorExecution(state: DirectorState): DirectorExecutionProjection {
  const canonical = validateDirectorState(state).state;
  const images: ExecutionItem[] = [];
  const videos: ExecutionItem[] = [];
  const audios: ExecutionItem[] = [];

  for (const id of canonical.imageOrder) {
    const item = canonical.items[id];
    if (!item || item.kind !== "image") continue;
    const projected: ExecutionItem = {
      id,
      kind: item.kind,
      source: executionSource(item.source),
      caption: item.caption,
      enabled: item.imageEnabled,
    };
    images.push(item.edit ? { ...projected, edit: executionEdit(item.edit) } : projected);
  }

  for (const id of canonical.videoOrder) {
    const item = canonical.items[id];
    if (!item || item.kind !== "video") continue;
    videos.push(optionalCrop({
      id,
      kind: item.kind,
      source: executionSource(item.source),
      caption: item.caption,
      enabled: item.videoEnabled,
    }, item.crop));
  }

  for (const id of canonical.audioOrder) {
    const item = canonical.items[id];
    if (!item || item.kind === "image") continue;
    if (item.kind === "audio") {
      audios.push(
        optionalCrop(
          {
            id,
            kind: item.kind,
            source: executionSource(item.source),
            caption: item.caption,
            enabled: item.audioEnabled,
          },
          item.crop,
        ),
      );
    } else {
      audios.push(
        optionalCrop(
          {
            id: `${id}:audio`,
            kind: "audio",
            source: executionSource(item.source),
            caption: item.audioCaptionOverride ?? item.caption,
            enabled: item.audioEnabled,
            derivedFrom: id,
          },
          item.crop,
        ),
      );
    }
  }

  return {
    version: 1,
    imageOrder: [...canonical.imageOrder],
    videoOrder: [...canonical.videoOrder],
    audioOrder: [...canonical.audioOrder],
    videoAudioPolicy: canonical.videoAudioPolicy,
    images,
    audios,
    videos,
  };
}

export function executionFingerprintSource(state: DirectorState): string {
  return JSON.stringify(projectDirectorExecution(state));
}
