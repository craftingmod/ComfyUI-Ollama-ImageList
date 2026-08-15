import type { TimeRange } from "./types";

export type VideoPreviewStatus = "idle" | "loading" | "playing" | "paused" | "error";

export interface VideoPreviewSnapshot {
  owner?: string;
  status: VideoPreviewStatus;
  currentTime: number;
  range?: TimeRange;
  error?: string;
}

type VideoPreviewListener = (snapshot: VideoPreviewSnapshot) => void;

const RANGE_END_EPSILON_SECONDS = 0.001;
const PREVIEW_UPDATE_INTERVAL_MS = 1_000 / 30;

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
  #lastAnimationTimestamp: number | undefined;
  #destroyed = false;
  #retainSourceOnEnd: boolean;

  constructor(
    element: HTMLVideoElement = document.createElement("video"),
    options: { retainSourceOnEnd?: boolean } = {},
  ) {
    this.element = element;
    this.#retainSourceOnEnd = options.retainSourceOnEnd === true;
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
      if (this.#status === "playing" && this.#atRangeEnd()) this.#finishRange();
    });
    this.element.addEventListener("ended", () => this.#finishRange());
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
      currentTime: Number.isFinite(this.element.currentTime) ? this.element.currentTime : this.#range?.start ?? 0,
      ...(this.#range ? { range: { ...this.#range } } : {}),
      ...(this.#error ? { error: this.#error } : {}),
    };
  }

  subscribe(listener: VideoPreviewListener): () => void {
    this.#listeners.add(listener);
    listener(this.snapshot);
    return () => this.#listeners.delete(listener);
  }

  prepare(owner: string, url: string, range: TimeRange, startAt: number = range.start): void {
    if (this.#destroyed) return;
    this.#stopAnimation();
    const nextRange = normalizedRange(range);
    const changingSource = this.#owner !== owner || this.#url !== url;
    if (changingSource) {
      this.#releaseSource();
      this.#owner = owner;
      this.#url = url;
      this.element.src = url;
      this.element.load();
    }
    this.#range = nextRange;
    this.#error = undefined;
    this.#status = "idle";
    this.#setCurrentTime(startAt);
    this.#emit();
  }

  async play(owner: string, url: string, range: TimeRange, startAt?: number): Promise<void> {
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
    const requestedStart = startAt === undefined
      ? changingSource ? nextRange.start : this.element.currentTime
      : startAt;
    this.#setCurrentTime(requestedStart);
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

  pause(owner: string): void {
    if (this.#destroyed || this.#owner !== owner) return;
    this.#sequence += 1;
    this.#stopAnimation();
    this.element.pause();
    this.#status = "paused";
    this.#emit();
  }

  seek(owner: string, seconds: number): void {
    if (this.#destroyed || this.#owner !== owner || !this.#range || !Number.isFinite(seconds)) return;
    this.#setCurrentTime(seconds);
    if (this.#status === "playing" && this.#atRangeEnd()) {
      this.reset(owner);
      return;
    }
    this.#emit();
  }

  setRange(owner: string, range: TimeRange): void {
    if (this.#destroyed || this.#owner !== owner) return;
    this.#range = normalizedRange(range);
    this.#setCurrentTime(this.element.currentTime);
    this.#emit();
  }

  reset(owner: string): void {
    if (this.#destroyed || this.#owner !== owner) return;
    this.#sequence += 1;
    this.#stopAnimation();
    this.element.pause();
    this.#setCurrentTime(this.#range?.start ?? 0);
    this.#status = "idle";
    this.#error = undefined;
    this.#emit();
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
    this.element.remove();
  }

  #releaseSource(): void {
    this.element.pause();
    this.element.removeAttribute("src");
    this.element.load();
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

  #setCurrentTime(seconds: number): void {
    const range = this.#range;
    const position = range
      ? Math.max(range.start, Math.min(range.end, seconds))
      : Math.max(0, seconds);
    try {
      this.element.currentTime = position;
    } catch {
      // Some browsers reject a seek until media metadata is available. The
      // loadedmetadata handler or the next explicit seek will retry it.
    }
  }

  #finishRange(): void {
    const owner = this.#owner;
    if (!owner) return;
    if (this.#retainSourceOnEnd) this.reset(owner);
    else this.stop(owner);
  }

  #startAnimation(): void {
    this.#lastAnimationTimestamp = undefined;
    const tick = (timestamp: number): void => {
      if (this.#destroyed || this.#status !== "playing") {
        this.#animationFrame = undefined;
        return;
      }
      if (this.#atRangeEnd()) {
        this.#finishRange();
        return;
      }
      if (this.#lastAnimationTimestamp === undefined) {
        this.#lastAnimationTimestamp = timestamp;
      } else {
        const elapsed = timestamp - this.#lastAnimationTimestamp;
        if (elapsed >= PREVIEW_UPDATE_INTERVAL_MS) {
          this.#lastAnimationTimestamp = timestamp - (elapsed % PREVIEW_UPDATE_INTERVAL_MS);
          this.#emit();
        }
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
    this.#lastAnimationTimestamp = undefined;
  }
}
