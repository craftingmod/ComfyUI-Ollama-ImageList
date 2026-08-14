import type { TimeRange } from "./types";

export type VideoPreviewStatus = "idle" | "loading" | "playing" | "error";

export interface VideoPreviewSnapshot {
  owner?: string;
  status: VideoPreviewStatus;
  range?: TimeRange;
  error?: string;
}

type VideoPreviewListener = (snapshot: VideoPreviewSnapshot) => void;

const RANGE_END_EPSILON_SECONDS = 0.001;

function normalizedRange(range: TimeRange): TimeRange {
  const start = Math.max(0, range.start);
  return {
    start,
    end: Math.max(start + 0.01, range.end),
  };
}

function playbackError(error: unknown): string {
  if (error instanceof DOMException && error.name === "NotSupportedError") {
    return "This browser cannot play the source video codec.";
  }
  return error instanceof Error ? error.message : "Video preview could not be played.";
}

export class VideoPreviewPlayer {
  readonly element: HTMLVideoElement;
  #owner: string | undefined;
  #url: string | undefined;
  #range: TimeRange | undefined;
  #status: VideoPreviewStatus = "idle";
  #error: string | undefined;
  #listeners = new Set<VideoPreviewListener>();
  #sequence = 0;
  #animationFrame: number | undefined;
  #destroyed = false;

  constructor(element: HTMLVideoElement = document.createElement("video")) {
    this.element = element;
    this.element.className = "rd-video-preview";
    this.element.preload = "metadata";
    this.element.removeAttribute("muted");
    this.element.muted = false;
    this.element.defaultMuted = false;
    this.element.playsInline = true;
    this.element.controls = false;
    this.element.disablePictureInPicture = true;
    this.element.setAttribute("aria-label", "Video preview with audio");
    this.element.addEventListener("timeupdate", () => {
      if (this.#status === "playing" && this.#atRangeEnd()) this.stop(this.#owner);
    });
    this.element.addEventListener("ended", () => this.stop(this.#owner));
    this.element.addEventListener("error", () => {
      if (!this.#owner || this.#destroyed) return;
      this.#stopAnimation();
      this.#owner = undefined;
      this.#url = undefined;
      this.#releaseSource();
      this.#status = "error";
      this.#error = "This browser could not decode the video preview.";
      this.#emit();
    });
  }

  get snapshot(): VideoPreviewSnapshot {
    return {
      ...(this.#owner ? { owner: this.#owner } : {}),
      status: this.#status,
      ...(this.#range ? { range: { ...this.#range } } : {}),
      ...(this.#error ? { error: this.#error } : {}),
    };
  }

  subscribe(listener: VideoPreviewListener): () => void {
    this.#listeners.add(listener);
    listener(this.snapshot);
    return () => this.#listeners.delete(listener);
  }

  async play(owner: string, url: string, range: TimeRange): Promise<void> {
    if (this.#destroyed) return;
    this.#stopAnimation();
    const nextRange = normalizedRange(range);
    const changingSource = this.#owner !== owner || this.#url !== url;
    const sequence = ++this.#sequence;
    if (changingSource) {
      this.#releaseSource();
      this.#owner = owner;
      this.#url = url;
      this.element.src = url;
      this.element.load();
    }
    this.#range = nextRange;
    this.#error = undefined;
    if (
      changingSource
      || this.element.currentTime < nextRange.start
      || this.element.currentTime >= nextRange.end - 0.01
    ) {
      this.element.currentTime = nextRange.start;
    }
    this.#status = "loading";
    this.#emit();
    try {
      await Promise.resolve(this.element.play());
      if (this.#destroyed || sequence !== this.#sequence || this.#owner !== owner) return;
      this.#status = "playing";
      this.#emit();
      this.#startAnimation();
    } catch (error) {
      if (this.#destroyed || sequence !== this.#sequence || this.#owner !== owner) return;
      this.#owner = undefined;
      this.#url = undefined;
      this.#releaseSource();
      this.#status = "error";
      this.#error = playbackError(error);
      this.#emit();
      throw new Error(this.#error);
    }
  }

  stop(owner?: string): void {
    if (this.#destroyed || (owner !== undefined && this.#owner !== owner)) return;
    this.#sequence += 1;
    this.#stopAnimation();
    this.element.pause();
    if (this.#range) this.element.currentTime = this.#range.start;
    this.#releaseSource();
    this.#owner = undefined;
    this.#url = undefined;
    this.#status = "idle";
    this.#error = undefined;
    this.#emit();
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.stop();
    this.#destroyed = true;
    this.#listeners.clear();
  }

  #releaseSource(): void {
    this.element.pause();
    this.element.removeAttribute("src");
    this.element.load();
    this.element.remove();
  }

  #emit(): void {
    const snapshot = this.snapshot;
    for (const listener of this.#listeners) listener(snapshot);
  }

  #atRangeEnd(): boolean {
    return Boolean(
      this.#range
      && this.element.currentTime >= this.#range.end - RANGE_END_EPSILON_SECONDS,
    );
  }

  #startAnimation(): void {
    const tick = (): void => {
      if (this.#destroyed || this.#status !== "playing") {
        this.#animationFrame = undefined;
        return;
      }
      if (this.#atRangeEnd()) {
        this.stop(this.#owner);
        return;
      }
      this.#animationFrame = globalThis.requestAnimationFrame(tick);
    };
    this.#animationFrame = globalThis.requestAnimationFrame(tick);
  }

  #stopAnimation(): void {
    if (this.#animationFrame !== undefined) {
      globalThis.cancelAnimationFrame(this.#animationFrame);
      this.#animationFrame = undefined;
    }
  }
}
