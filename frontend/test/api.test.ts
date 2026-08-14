import { describe, expect, test } from "bun:test";

import type { ComfyApiLike } from "../src/comfyui";
import {
  MAX_REFERENCE_DIRECTOR_JSON_BYTES,
  ReferenceDirectorApi,
  REFERENCE_DIRECTOR_API_BASE,
  normalizeApiSource,
} from "../src/reference-director/api";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

describe("Reference Director API", () => {
  test("uploads exactly one multipart file field and normalizes the canonical response", async () => {
    let route = "";
    let init: RequestInit | undefined;
    const api: ComfyApiLike = {
      fetchApi(requestRoute, requestInit) {
        route = requestRoute;
        init = requestInit;
        return Promise.resolve(
          jsonResponse(
            {
              kind: "image",
              source: { path: "reference_director/sources/hash.webp", mime: "image/webp", sha256: "hash", size: 100 },
              metadata: { width: 64, height: 32 },
            },
            201,
          ),
        );
      },
    };
    const result = await new ReferenceDirectorApi(api).upload(new File(["x"], "x.png", { type: "image/png" }));
    expect(route).toBe(`${REFERENCE_DIRECTOR_API_BASE}/upload`);
    expect(init?.body).toBeInstanceOf(FormData);
    const fields = [...(init?.body as FormData).entries()];
    expect(fields).toHaveLength(1);
    expect(fields[0]?.[0]).toBe("file");
    expect(result).toMatchObject({ kind: "image", source: { path: "reference_director/sources/hash.webp", size: 100 }, metadata: { width: 64 } });
  });

  test("sends canonical proxy and waveform requests and accepts snake_case responses", async () => {
    const calls: Array<{ route: string; body: Record<string, unknown> }> = [];
    const api: ComfyApiLike = {
      async fetchApi(route, init) {
        calls.push({ route, body: JSON.parse(String(init?.body)) as Record<string, unknown> });
        if (route.endsWith("image_proxy")) return jsonResponse({ url: "/api/cache/x.webp", cache_key: "x" });
        if (route.endsWith("background_preview")) return jsonResponse({ url: "/api/cache/foreground.png", cache_key: "r" });
        return jsonResponse({ pairs: [[-0.4, 0.8]], duration: 2, cache_key: "w" });
      },
    };
    const client = new ReferenceDirectorApi(api);
    const source = { path: "reference_director/sources/a.wav", mime: "audio/wav", sha256: "hash" };
    const previewUrl = new URL(client.audioPreviewUrl(source), "http://localhost");
    const videoPreviewUrl = new URL(client.videoPreviewUrl(source), "http://localhost");
    expect(previewUrl.pathname).toBe(`${REFERENCE_DIRECTOR_API_BASE}/audio_preview`);
    expect(JSON.parse(previewUrl.searchParams.get("source") ?? "{}")).toEqual(source);
    expect(videoPreviewUrl.pathname).toBe(`${REFERENCE_DIRECTOR_API_BASE}/video_preview`);
    expect(JSON.parse(videoPreviewUrl.searchParams.get("source") ?? "{}")).toEqual(source);
    expect(await client.imageProxy(source, 123)).toEqual({ url: "/api/cache/x.webp", cacheKey: "x" });
    expect(await client.backgroundPreview(source)).toEqual({ url: "/api/cache/foreground.png", cacheKey: "r" });
    expect(await client.waveform(source, 300, { start: 0, end: 1 })).toEqual({ pairs: [[-0.4, 0.8]], duration: 2, cacheKey: "w" });
    expect(calls[0]?.body.maxPixels).toBe(123);
    expect(calls[1]?.body.source).toEqual(source);
    expect(calls[2]?.body.peakCount).toBe(300);
  });

  test("rebases backend /api asset URLs through ComfyUI's configured API base", async () => {
    const api: ComfyApiLike = {
      apiURL: (route) => `/comfy/api${route}`,
      async fetchApi(route) {
        if (route.endsWith("image_proxy")) return jsonResponse({ url: "/api/ollama_multimodal/reference_director/cache/image_proxy/x.webp" });
        return jsonResponse({
          source: { path: "reference_director/edits/x.png", mime: "image/png", sha256: "a".repeat(64), revision: 1 },
          edit: { revision: 1 },
          proxy_url: "/api/ollama_multimodal/reference_director/cache/image_proxy/y.webp",
        }, 201);
      },
    };
    const client = new ReferenceDirectorApi(api);
    const source = { path: "reference_director/sources/x.png", mime: "image/png", sha256: "a".repeat(64) };
    expect(client.audioPreviewUrl(source)).toStartWith(
      "/comfy/api/ollama_multimodal/reference_director/audio_preview?",
    );
    expect(client.videoPreviewUrl(source)).toStartWith(
      "/comfy/api/ollama_multimodal/reference_director/video_preview?",
    );
    expect((await client.imageProxy(source, 100)).url).toBe(
      "/comfy/api/ollama_multimodal/reference_director/cache/image_proxy/x.webp",
    );
    expect((await client.applyEdit(source, { revision: 1 })).proxyUrl).toBe(
      "/comfy/api/ollama_multimodal/reference_director/cache/image_proxy/y.webp",
    );
  });

  test("rejects an oversized JSON body before invoking fetchApi", async () => {
    let calls = 0;
    const api: ComfyApiLike = {
      fetchApi: async () => {
        calls += 1;
        return jsonResponse({});
      },
    };
    const source = {
      path: "reference_director/sources/x.png",
      mime: "image/png",
      sha256: "a".repeat(64),
      padding: "x".repeat(MAX_REFERENCE_DIRECTOR_JSON_BYTES),
    };
    await expect(new ReferenceDirectorApi(api).metadata(source)).rejects.toThrow("exceeds the 1 MiB JSON limit");
    expect(calls).toBe(0);
  });

  test("does not add an input prefix when normalizing legacy descriptors", () => {
    expect(normalizeApiSource({ type: "input", subfolder: "reference_director/sources", filename: "x.png", mime_type: "image/png", sha256: "x" })).toEqual({
      path: "reference_director/sources/x.png",
      mime: "image/png",
      sha256: "x",
    });
  });

  test("surfaces route error details", async () => {
    const api: ComfyApiLike = {
      fetchApi: async () => jsonResponse({ error: { code: "upload_too_large", message: "The upload is too large." } }, 413),
    };
    await expect(new ReferenceDirectorApi(api).metadata({ path: "x", mime: "image/png", sha256: "x" })).rejects.toThrow(
      "The upload is too large. (upload_too_large)",
    );
  });

  test("sends the current source revision as optimistic concurrency metadata", async () => {
    let body: Record<string, unknown> = {};
    const api: ComfyApiLike = {
      async fetchApi(_route, init) {
        body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return jsonResponse({
          source: { path: "reference_director/edits/next.png", mime: "image/png", sha256: "b".repeat(64), revision: 3 },
          edit: { crop: { x: 0, y: 0, width: 1, height: 1 }, revision: 3 },
        }, 201);
      },
    };
    await new ReferenceDirectorApi(api).applyEdit(
      { path: "reference_director/edits/old.png", mime: "image/png", sha256: "a".repeat(64), revision: 2 },
      {
        crop: { x: 0, y: 0, width: 1, height: 1 },
        mask: { path: "reference_director/sources/mask.png", mime: "image/png", sha256: "c".repeat(64) },
        maskMode: "keep",
        revision: 3,
      },
    );
    expect(body.expectedRevision).toBe(2);
    expect(body.edit).toMatchObject({ maskMode: "keep", mask: { path: "reference_director/sources/mask.png" } });
  });
});
