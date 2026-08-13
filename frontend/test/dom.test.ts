import { describe, expect, test } from "bun:test";

import type { ComfyApiLike, ComfyNode } from "../src/comfyui";
import { ReferenceDirectorApi } from "../src/reference-director/api";
import { ReferenceDirectorController } from "../src/reference-director/components/director";
import { directorReducer } from "../src/reference-director/reducer";
import { createEmptyDirectorState, createMediaItem } from "../src/reference-director/types";
import { serializeDirectorState } from "../src/reference-director/serialization";

describe("Reference Director DOM lifecycle", () => {
  test("mounts independent channels and removes its DOM on cleanup", () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const api: ComfyApiLike = { fetchApi: async () => new Response("{}") };
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), undefined);
    expect(root.querySelectorAll(".rd-channel")).toHaveLength(2);
    expect(root.textContent).toContain("Visual");
    expect(root.textContent).toContain("Audio");
    controller.destroy();
    expect(root.childElementCount).toBe(0);
    root.remove();
  });

  test("arms native article dragging from the card surface but not its controls", () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const api: ComfyApiLike = { fetchApi: async () => new Response("{}") };
    const image = createMediaItem("image", {
      path: "reference_director/sources/a.png",
      mime: "image/png",
      sha256: "a".repeat(64),
    }, "a");
    const state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(state));
    const card = root.querySelector<HTMLElement>('.rd-card[data-channel="visual"]');
    const surface = card?.querySelector<HTMLElement>(".rd-card__media");
    const caption = card?.querySelector<HTMLTextAreaElement>("textarea");
    expect(card).toBeDefined();
    expect(root.querySelector(".rd-drag")).toBeNull();
    surface?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    const drag = new DragEvent("dragstart", { bubbles: true, cancelable: true });
    card?.dispatchEvent(drag);
    expect(drag.defaultPrevented).toBe(false);
    card?.dispatchEvent(new DragEvent("dragend", { bubbles: true }));
    caption?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    const blockedDrag = new DragEvent("dragstart", { bubbles: true, cancelable: true });
    card?.dispatchEvent(blockedDrag);
    expect(blockedDrag.defaultPrevented).toBe(true);
    expect(card?.querySelector('[data-action="remove"]')?.classList.contains("rd-remove")).toBe(true);
    controller.destroy();
    root.remove();
  });

  test("wraps state mutations in the owning graph change transaction", () => {
    const root = document.createElement("div");
    document.body.append(root);
    const transactions: string[] = [];
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
      graph: {
        beforeChange: () => transactions.push("before"),
        afterChange: () => transactions.push("after"),
      },
    };
    const image = createMediaItem("image", {
      path: "reference_director/sources/a.png",
      mime: "image/png",
      sha256: "a".repeat(64),
    }, "a");
    const state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    const controller = new ReferenceDirectorController(
      root,
      node,
      new ReferenceDirectorApi({ fetchApi: async () => new Promise<Response>(() => undefined) }),
      serializeDirectorState(state),
      {
        beforeChange: () => transactions.push("emit-before"),
        afterChange: () => transactions.push("emit-after"),
      },
    );
    root.querySelector<HTMLButtonElement>('[data-action="toggle-visual"]')?.click();
    expect(transactions).toEqual(["emit-before", "before", "after", "emit-after"]);
    controller.destroy();
    root.remove();
  });

  test("ignores a delayed runtime response from before same-id workflow restore", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const resolvers: Array<(response: Response) => void> = [];
    const api: ComfyApiLike = { fetchApi: () => new Promise((resolve) => resolvers.push(resolve)) };
    const first = createMediaItem("image", { path: "reference_director/sources/old.png", mime: "image/png", sha256: "a".repeat(64) }, "same");
    const second = createMediaItem("image", { path: "reference_director/sources/new.png", mime: "image/png", sha256: "b".repeat(64) }, "same");
    const firstState = directorReducer(createEmptyDirectorState(), { type: "add", item: first });
    const secondState = directorReducer(createEmptyDirectorState(), { type: "add", item: second });
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(firstState));
    await Promise.resolve();
    expect(resolvers.length).toBe(2);
    controller.restore(serializeDirectorState(secondState));
    await Promise.resolve();
    expect(resolvers.length).toBe(4);
    resolvers[0]?.(new Response(JSON.stringify({ metadata: { width: 1 } }), { status: 200 }));
    resolvers[1]?.(new Response(JSON.stringify({ url: "/old.webp" }), { status: 200 }));
    await Promise.resolve();
    await Promise.resolve();
    resolvers[2]?.(new Response(JSON.stringify({ metadata: { width: 2 } }), { status: 200 }));
    resolvers[3]?.(new Response(JSON.stringify({ url: "/new.webp" }), { status: 200 }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(root.querySelector<HTMLImageElement>("img")?.getAttribute("src")).toBe("/new.webp");
    controller.destroy();
    root.remove();
  });

  test("limits runtime hydration to four media items at a time", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    let activeRequests = 0;
    let maximumActiveRequests = 0;
    let calls = 0;
    const api: ComfyApiLike = {
      fetchApi(route, init) {
        calls += 1;
        activeRequests += 1;
        maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
        return new Promise((resolve, reject) => {
          let settled = false;
          const finish = (): void => {
            if (settled) return;
            settled = true;
            activeRequests -= 1;
            init?.signal?.removeEventListener("abort", abort);
            resolve(route.endsWith("metadata")
              ? new Response(JSON.stringify({ metadata: { width: 1, height: 1 } }), { status: 200 })
              : new Response(JSON.stringify({ url: `/preview-${calls}.webp` }), { status: 200 }));
          };
          const abort = (): void => {
            if (settled) return;
            settled = true;
            activeRequests -= 1;
            reject(new DOMException("Aborted", "AbortError"));
          };
          init?.signal?.addEventListener("abort", abort, { once: true });
          setTimeout(finish, 5);
        });
      },
    };
    let state = createEmptyDirectorState();
    for (let index = 0; index < 6; index += 1) {
      state = directorReducer(state, {
        type: "add",
        item: createMediaItem("image", {
          path: `reference_director/sources/${index}.png`,
          mime: "image/png",
          sha256: String(index).repeat(64),
        }, `image-${index}`),
      });
    }
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(state));
    await new Promise((resolve) => setTimeout(resolve, 35));

    expect(calls).toBe(12);
    // Each hydrated image performs metadata and proxy requests in parallel.
    expect(maximumActiveRequests).toBeLessThanOrEqual(8);
    expect(root.querySelectorAll("img")).toHaveLength(6);
    controller.destroy();
    root.remove();
  });

  test("keeps a silent video's proxy without requesting a waveform", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const routes: string[] = [];
    const api: ComfyApiLike = {
      async fetchApi(route) {
        routes.push(route);
        if (route.endsWith("metadata")) return new Response(JSON.stringify({ metadata: { duration: 2, has_audio: false } }), { status: 200 });
        if (route.endsWith("image_proxy")) return new Response(JSON.stringify({ url: "/silent.webp" }), { status: 200 });
        throw new Error("waveform must not be requested for silent video");
      },
    };
    const video = createMediaItem("video", { path: "reference_director/sources/v.mp4", mime: "video/mp4", sha256: "a".repeat(64) }, "v");
    const state = directorReducer(createEmptyDirectorState(), { type: "add", item: video });
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(state));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(routes.some((route) => route.endsWith("waveform"))).toBe(false);
    expect(root.querySelector<HTMLImageElement>('.rd-card[data-channel="visual"] img')?.getAttribute("src")).toBe("/silent.webp");
    expect(root.querySelector('.rd-card[data-channel="audio"] img')).toBeNull();
    expect(root.querySelector('.rd-card[data-channel="audio"] canvas')).not.toBeNull();
    expect(root.querySelector<HTMLButtonElement>('[data-action="toggle-audio"]')?.disabled).toBe(true);
    expect(JSON.parse(controller.serialize()).items.v.audioEnabled).toBe(false);
    controller.destroy();
    root.remove();
  });

  test("defers async preview rendering while a caption textarea owns focus", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const resolvers: Array<(response: Response) => void> = [];
    const api: ComfyApiLike = { fetchApi: () => new Promise((resolve) => resolvers.push(resolve)) };
    const image = createMediaItem("image", { path: "reference_director/sources/a.png", mime: "image/png", sha256: "a".repeat(64) }, "a");
    const state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(state));
    const textarea = root.querySelector<HTMLTextAreaElement>("textarea");
    textarea?.focus();
    textarea?.setSelectionRange(0, 0);
    await Promise.resolve();
    resolvers[0]?.(new Response(JSON.stringify({ metadata: { width: 2 } }), { status: 200 }));
    resolvers[1]?.(new Response(JSON.stringify({ url: "/focused.webp" }), { status: 200 }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.activeElement).toBe(textarea);
    expect(root.querySelector("textarea")).toBe(textarea);
    expect(root.querySelector("img")).toBeNull();
    textarea?.blur();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(root.querySelector<HTMLImageElement>("img")?.getAttribute("src")).toBe("/focused.webp");
    controller.destroy();
    root.remove();
  });

  test("does not let an old-source preview overwrite a completed image edit", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const oldResolvers = new Map<string, (response: Response) => void>();
    let resolveApply: ((response: Response) => void) | undefined;
    const api: ComfyApiLike = {
      fetchApi(route) {
        if (route.endsWith("apply_edit")) {
          return new Promise((resolve) => {
            resolveApply = resolve;
          });
        }
        return new Promise((resolve) => oldResolvers.set(route, resolve));
      },
    };
    const image = createMediaItem("image", {
      path: "reference_director/sources/old.png",
      mime: "image/png",
      sha256: "a".repeat(64),
    }, "edited");
    const state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(state));
    await Promise.resolve();
    expect(oldResolvers.size).toBe(2);

    root.querySelector<HTMLButtonElement>('[data-action="edit"]')?.click();
    document.querySelector<HTMLButtonElement>('.rd-image-editor [data-action="apply"]')?.click();
    await Promise.resolve();
    expect(resolveApply).toBeDefined();
    resolveApply?.(new Response(JSON.stringify({
      source: {
        path: "reference_director/edits/fresh.png",
        mime: "image/png",
        sha256: "b".repeat(64),
        revision: 1,
      },
      edit: { revision: 1 },
      proxy_url: "/fresh.webp",
      metadata: { width: 2, height: 2 },
    }), { status: 201 }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    oldResolvers.get("/ollama_multimodal/reference_director/metadata")?.(
      new Response(JSON.stringify({ metadata: { width: 1, height: 1 } }), { status: 200 }),
    );
    oldResolvers.get("/ollama_multimodal/reference_director/image_proxy")?.(
      new Response(JSON.stringify({ url: "/stale.webp" }), { status: 200 }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(root.querySelector<HTMLImageElement>("img")?.getAttribute("src")).toBe("/fresh.webp");
    expect(JSON.parse(controller.serialize()).items.edited.source.path).toBe("reference_director/edits/fresh.png");
    controller.destroy();
    root.remove();
  });

  test("never remounts or mutates after teardown when runtime requests finish late", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    const resolvers: Array<(response: Response) => void> = [];
    const api: ComfyApiLike = { fetchApi: () => new Promise((resolve) => resolvers.push(resolve)) };
    const image = createMediaItem("image", { path: "reference_director/sources/a.png", mime: "image/png", sha256: "a".repeat(64) }, "a");
    const state = directorReducer(createEmptyDirectorState(), { type: "add", item: image });
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), serializeDirectorState(state));
    await Promise.resolve();
    expect(resolvers.length).toBe(2);
    controller.destroy();
    resolvers[0]?.(new Response(JSON.stringify({ metadata: { width: 2 } }), { status: 200 }));
    resolvers[1]?.(new Response(JSON.stringify({ url: "/late.webp" }), { status: 200 }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(root.childElementCount).toBe(0);
    expect(controller.serialize()).toBe(serializeDirectorState(state));
    root.remove();
  });

  test("does not let a pending upload cross a workflow restore", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    let resolveUpload: ((response: Response) => void) | undefined;
    const api: ComfyApiLike = {
      fetchApi: () => new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    };
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), undefined);
    const input = root.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["image"], "pending.png", { type: "image/png" });
    Object.defineProperty(input, "files", { configurable: true, value: [file] });
    input?.dispatchEvent(new Event("change", { bubbles: true }));
    expect(root.textContent).toContain("pending.png");

    controller.restore(serializeDirectorState(createEmptyDirectorState()));
    resolveUpload?.(new Response(JSON.stringify({
      kind: "image",
      source: { path: "reference_director/sources/pending.png", mime: "image/png", sha256: "c".repeat(64) },
      metadata: { width: 1, height: 1 },
    }), { status: 201 }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(JSON.parse(controller.serialize()).items).toEqual({});
    expect(root.textContent).not.toContain("pending.png");
    controller.destroy();
    root.remove();
  });

  test("isolates a stale upload rejection and finally render from restored workflow state", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    let rejectUpload: ((reason: Error) => void) | undefined;
    let uploadSignal: AbortSignal | undefined;
    const api: ComfyApiLike = {
      fetchApi: (_route, init) => {
        uploadSignal = init?.signal ?? undefined;
        return new Promise((_resolve, reject) => {
          rejectUpload = reject;
        });
      },
    };
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), undefined);
    const input = root.querySelector<HTMLInputElement>('input[type="file"]');
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["image"], "stale.png", { type: "image/png" })],
    });
    input?.dispatchEvent(new Event("change", { bubbles: true }));
    controller.restore(serializeDirectorState(createEmptyDirectorState()));
    expect(uploadSignal?.aborted).toBe(true);
    rejectUpload?.(new Error("late stale failure"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(root.querySelector(".rd-status")?.textContent).toBe("Workflow state restored.");
    expect(root.textContent).not.toContain("late stale failure");
    expect(root.textContent).not.toContain("stale.png");
    expect(JSON.parse(controller.serialize()).items).toEqual({});
    controller.destroy();
    root.remove();
  });

  test("shows a status when every dropped file has an unsupported extension", () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    let calls = 0;
    const api: ComfyApiLike = {
      fetchApi: async () => {
        calls += 1;
        return new Response("{}");
      },
    };
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), undefined);
    const input = root.querySelector<HTMLInputElement>('input[type="file"]');
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["image"], "unsupported.avif", { type: "" })],
    });
    input?.dispatchEvent(new Event("change", { bubbles: true }));

    expect(root.querySelector(".rd-status")?.textContent).toContain("unsupported or over-limit");
    expect(calls).toBe(0);
    controller.destroy();
    root.remove();
  });

  test("rechecks the server-detected media kind before adding an upload", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    let state = createEmptyDirectorState();
    for (let index = 0; index < 8; index += 1) {
      state = directorReducer(state, {
        type: "add",
        item: createMediaItem(
          "audio",
          {
            path: `reference_director/sources/audio-${index}.wav`,
            mime: "audio/wav",
            sha256: index.toString(16).padStart(64, "0"),
          },
          `audio-${index}`,
        ),
      });
    }
    const api: ComfyApiLike = {
      fetchApi: async () => new Response(JSON.stringify({
        kind: "audio",
        source: {
          path: "reference_director/sources/audio-only.m4a",
          mime: "audio/mp4",
          sha256: "f".repeat(64),
        },
        metadata: { duration: 1 },
      }), { status: 201 }),
    };
    const controller = new ReferenceDirectorController(
      root,
      node,
      new ReferenceDirectorApi(api),
      serializeDirectorState(state),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    const input = root.querySelector<HTMLInputElement>('input[type="file"]');
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["audio"], "looks-like-video.mp4", { type: "video/mp4" })],
    });
    input?.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(Object.keys(JSON.parse(controller.serialize()).items)).toHaveLength(8);
    expect(root.querySelector(".rd-status")?.textContent).toContain("identified this as audio");
    controller.destroy();
    root.remove();
  });

  test("never remounts after teardown when an upload client ignores abort", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const node: ComfyNode = {
      addWidget: () => ({ name: "unused", value: null }),
      addDOMWidget: () => ({ name: "unused", value: null }),
      setDirtyCanvas: () => undefined,
    };
    let resolveUpload: ((response: Response) => void) | undefined;
    const api: ComfyApiLike = {
      fetchApi: () => new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    };
    const controller = new ReferenceDirectorController(root, node, new ReferenceDirectorApi(api), undefined);
    const input = root.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["image"], "late.png", { type: "image/png" });
    Object.defineProperty(input, "files", { configurable: true, value: [file] });
    input?.dispatchEvent(new Event("change", { bubbles: true }));
    controller.destroy();
    resolveUpload?.(new Response(JSON.stringify({
      kind: "image",
      source: { path: "reference_director/sources/late.png", mime: "image/png", sha256: "d".repeat(64) },
      metadata: { width: 1, height: 1 },
    }), { status: 201 }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(root.childElementCount).toBe(0);
    expect(controller.serialize()).toBe(serializeDirectorState(createEmptyDirectorState()));
    root.remove();
  });
});
