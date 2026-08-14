from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace

import pytest

from backend import reference_routes as routes


class JsonRequest:
    content_length = None

    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class ChunkedJsonRequest:
    content_length = None

    def __init__(self, chunks):
        class Content:
            async def iter_chunked(_self, size):
                assert size == 64 * 1024
                for chunk in chunks:
                    yield chunk

        self.content = Content()


class UploadPart:
    name = "file"

    def __init__(self, chunks, filename="../untrusted name.png"):
        self.chunks = list(chunks)
        self.filename = filename

    async def read_chunk(self, *, size):
        assert size == routes.UPLOAD_CHUNK_BYTES
        return self.chunks.pop(0) if self.chunks else b""


class MultipartReader:
    def __init__(self, parts):
        self.parts = list(parts)

    async def next(self):
        return self.parts.pop(0) if self.parts else None


class UploadRequest:
    content_type = "multipart/form-data"

    def __init__(self, parts):
        self.reader = MultipartReader(parts)

    async def multipart(self):
        return self.reader


class QueryRequest:
    def __init__(self, source):
        self.query = {"source": json.dumps(source)}


def install_runtime_stubs(monkeypatch, input_root: Path):
    folder_paths = ModuleType("folder_paths")
    folder_paths.get_input_directory = lambda: str(input_root)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)

    aiohttp = ModuleType("aiohttp")
    aiohttp.web = SimpleNamespace(
        json_response=lambda payload, status=200: SimpleNamespace(payload=payload, status=status),
        FileResponse=lambda path, headers=None: SimpleNamespace(path=path, headers=headers, status=200),
    )
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp)


def write_managed_source(input_root: Path, data: bytes, suffix: str) -> tuple[Path, dict]:
    digest = hashlib.sha256(data).hexdigest()
    directory = input_root / "reference_director" / "sources"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.{suffix}"
    path.write_bytes(data)
    return path, {
        "path": f"reference_director/sources/{path.name}",
        "sha256": digest,
        "mime": routes._mime_from_suffix(path),
        "size": len(data),
    }


def test_register_reference_routes_is_idempotent():
    class Registrar:
        def __init__(self):
            self.calls = []

        def post(self, path):
            return lambda handler: self.calls.append(("POST", path, handler)) or handler

        def get(self, path):
            return lambda handler: self.calls.append(("GET", path, handler)) or handler

    registrar = Registrar()
    routes._registered_route_ids.discard(id(registrar))
    routes.register_reference_routes(registrar)
    routes.register_reference_routes(registrar)

    assert [(method, path) for method, path, _handler in registrar.calls] == [
        ("POST", routes.UPLOAD_ROUTE),
        ("POST", routes.METADATA_ROUTE),
        ("POST", routes.IMAGE_PROXY_ROUTE),
        ("POST", routes.BACKGROUND_PREVIEW_ROUTE),
        ("GET", routes.AUDIO_PREVIEW_ROUTE),
        ("GET", routes.VIDEO_PREVIEW_ROUTE),
        ("POST", routes.WAVEFORM_ROUTE),
        ("POST", routes.APPLY_EDIT_ROUTE),
        ("GET", routes.CACHE_VIEW_ROUTE),
    ]


def test_chunked_json_request_enforces_the_endpoint_body_limit(monkeypatch):
    monkeypatch.setattr(routes, "MAX_JSON_BYTES", 8)

    with pytest.raises(routes.ReferenceRouteError) as caught:
        asyncio.run(routes._request_json(ChunkedJsonRequest([b'{"key":', b'"value"}'])))

    assert caught.value.status == 413
    assert caught.value.code == "request_too_large"


def test_decoder_work_runs_inside_the_global_concurrency_gate(monkeypatch):
    events = []

    class Gate:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *_args):
            events.append("exit")

    monkeypatch.setattr(routes, "_MEDIA_WORK_SEMAPHORE", Gate())

    result = routes._limited_media_work(
        lambda left, *, right: events.append("work") or left + right,
        2,
        right=3,
    )

    assert result == 5
    assert events == ["enter", "work", "exit"]


def test_upload_streams_to_original_named_managed_source(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    body = b"trusted-bytes"
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda path, **_kwargs: (
            "image",
            "png",
            "image/png",
            {"width": 2, "height": 3, "mode": "RGB", "frame_count": 1},
        ),
    )

    response = asyncio.run(routes.upload_endpoint(UploadRequest([UploadPart([body[:4], body[4:]])])))

    digest = hashlib.sha256(body).hexdigest()
    assert response.status == 201
    assert response.payload == {
        "source": {
            "path": "reference_director/sources/untrusted name.png",
            "mime": "image/png",
            "sha256": digest,
            "size": len(body),
        },
        "kind": "image",
        "metadata": {"width": 2, "height": 3, "mode": "RGB", "frame_count": 1},
    }
    assert (tmp_path / response.payload["source"]["path"]).read_bytes() == body
    assert routes._resolve_source(response.payload["source"]).sha256 == digest


def test_upload_preserves_names_and_numbers_only_true_name_collisions(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda path, **_kwargs: (
            "image",
            "png",
            "image/png",
            {"width": 2, "height": 3, "mode": "RGB", "frame_count": 1},
        ),
    )

    first = asyncio.run(routes.upload_endpoint(UploadRequest([UploadPart([b"first"], "photo.png")])))
    duplicate = asyncio.run(routes.upload_endpoint(UploadRequest([UploadPart([b"first"], "photo.png")])))
    collision = asyncio.run(routes.upload_endpoint(UploadRequest([UploadPart([b"second"], "photo.png")])))

    assert first.payload["source"]["path"] == "reference_director/sources/photo.png"
    assert duplicate.payload["source"]["path"] == first.payload["source"]["path"]
    assert collision.payload["source"]["path"] == "reference_director/sources/photo (2).png"
    assert (tmp_path / "reference_director" / "sources" / "photo (2).png").read_bytes() == b"second"


def test_upload_enforces_streaming_limit_and_removes_partial_file(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    monkeypatch.setattr(routes, "MAX_UPLOAD_BYTES", 5)

    response = asyncio.run(routes.upload_endpoint(UploadRequest([UploadPart([b"123", b"456"])])))

    assert response.status == 413
    assert response.payload["error"]["code"] == "upload_too_large"
    incoming = tmp_path / "reference_director" / ".incoming"
    assert list(incoming.iterdir()) == []


@pytest.mark.parametrize(
    "source_path",
    [
        "../secret.png",
        "/absolute/secret.png",
        "reference_director/sources/../secret.png",
        "reference_director/.incoming/" + "a" * 64 + ".png",
        "reference_director/cache/" + "a" * 64 + ".png",
        "reference_director/edits/" + "a" * 64 + ".json",
        "reference_director/sources/not-a-hash.png",
    ],
)
def test_source_resolver_rejects_paths_outside_managed_media(monkeypatch, tmp_path, source_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._resolve_source({"path": source_path})
    assert str(tmp_path) not in caught.value.message


def test_recipe_sidecar_is_never_resolved_as_a_media_source(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    digest = hashlib.sha256(b"recipe").hexdigest()
    edits = tmp_path / "reference_director" / "edits"
    edits.mkdir(parents=True)
    (edits / f"{digest}.json").write_text("{}", encoding="utf-8")

    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._resolve_source(
            {
                "path": f"reference_director/edits/{digest}.json",
                "sha256": digest,
                "mime": "application/json",
            }
        )

    assert caught.value.code == "invalid_source"


def test_resolver_rejects_content_that_does_not_match_hash_name(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    declared_hash = hashlib.sha256(b"declared").hexdigest()
    sources = tmp_path / "reference_director" / "sources"
    sources.mkdir(parents=True)
    (sources / f"{declared_hash}.png").write_bytes(b"different")

    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._resolve_source(
            {
                "path": f"reference_director/sources/{declared_hash}.png",
                "sha256": declared_hash,
                "mime": "image/png",
            }
        )

    assert caught.value.code == "source_mismatch"


def test_resolver_rejects_declared_size_or_mime_that_does_not_match(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"image", "png")

    for mismatch in ({**source, "size": 999}, {**source, "mime": "image/jpeg"}):
        with pytest.raises(routes.ReferenceRouteError) as caught:
            routes._resolve_source(mismatch)
        assert caught.value.code == "source_mismatch"


def test_link_like_detects_generic_windows_reparse_attribute():
    class ReparsePoint:
        def is_symlink(self):
            return False

        def is_junction(self):
            return False

        def lstat(self):
            return SimpleNamespace(st_file_attributes=0x400)

    assert routes._is_link_like(ReparsePoint()) is True


@pytest.mark.parametrize(
    ("kind", "limit"),
    [
        ("audio", routes.MAX_AUDIO_DURATION_SECONDS),
        ("video", routes.MAX_VIDEO_DURATION_SECONDS),
    ],
)
def test_duration_limits_reject_known_oversize_and_allow_unknown(kind, limit):
    routes._enforce_duration_limit(kind, None)
    routes._enforce_duration_limit(kind, float(limit))

    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._enforce_duration_limit(kind, float(limit) + 0.01)

    assert caught.value.status == 413
    assert caught.value.code == "media_duration_exceeded"


def test_supported_stream_selection_skips_cover_art_and_missing_codecs():
    missing_codec = SimpleNamespace(codec_context=None)
    cover_art = SimpleNamespace(
        codec_context=object(),
        disposition=SimpleNamespace(attached_pic=True),
    )
    video = SimpleNamespace(
        codec_context=object(),
        disposition=SimpleNamespace(attached_pic=False),
    )
    audio = SimpleNamespace(codec_context=object())
    container = SimpleNamespace(
        streams=SimpleNamespace(
            video=[missing_codec, cover_art, video],
            audio=[missing_codec, audio],
        )
    )

    assert routes._supported_streams(container, "video") == [video]
    assert routes._supported_streams(container, "audio") == [audio]


def test_video_layout_rejects_tracks_comfy_cannot_select_consistently():
    video = SimpleNamespace(codec_context=object(), disposition=None)
    cover = SimpleNamespace(
        codec_context=object(),
        disposition=SimpleNamespace(attached_pic=True),
    )
    audio = SimpleNamespace(codec_context=object())
    container = SimpleNamespace(
        streams=SimpleNamespace(video=[cover, video], audio=[audio])
    )

    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._validate_comfy_video_layout(container, [video])

    assert caught.value.status == 415
    assert caught.value.code == "unsupported_stream_layout"


@pytest.mark.parametrize(
    ("kind", "suffix", "container_name", "limit"),
    [
        ("audio", "wav", "wav", routes.MAX_AUDIO_DURATION_SECONDS),
        ("video", "mp4", "mp4", routes.MAX_VIDEO_DURATION_SECONDS),
    ],
)
def test_inspection_applies_known_duration_limit(
    monkeypatch,
    tmp_path,
    kind,
    suffix,
    container_name,
    limit,
):
    media_path = tmp_path / f"too-long.{suffix}"
    media_path.write_bytes(b"not-an-image")
    stream = SimpleNamespace(
        duration=limit + 1,
        time_base=1,
        average_rate=24,
        codec_context=SimpleNamespace(
            sample_rate=48_000,
            channels=2,
            width=1920,
            height=1080,
        ),
    )

    class Container:
        def __init__(self):
            self.format = SimpleNamespace(name=container_name)
            self.streams = SimpleNamespace(
                video=[stream] if kind == "video" else [],
                audio=[stream] if kind == "audio" else [],
            )
            self.duration = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    av = ModuleType("av")
    av.open = lambda *_args, **_kwargs: Container()
    av.time_base = 1_000_000
    monkeypatch.setitem(sys.modules, "av", av)

    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._inspect_media(media_path)

    assert caught.value.status == 413
    assert caught.value.code == "media_duration_exceeded"


def test_edit_normalization_accepts_canonical_camel_case_flips():
    edit, mask = routes._normalize_edit(
        {"revision": 1, "flipX": True, "flipY": False},
        current_revision=0,
    )

    assert mask is None
    assert edit["flipX"] is True
    assert edit["flipY"] is False
    assert "transform" not in edit


def test_edit_normalization_accepts_canonical_mask_mode():
    mask_source = {
        "path": f"reference_director/sources/{'d' * 64}.png",
        "mime": "image/png",
        "sha256": "d" * 64,
    }
    edit, mask = routes._normalize_edit(
        {"revision": 1, "mask": mask_source, "maskMode": "erase"},
        current_revision=0,
    )

    assert mask == mask_source
    assert edit["maskMode"] == "erase"
    assert "mask_mode" not in edit


def test_metadata_endpoint_returns_canonical_source_without_absolute_path(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"image", "png")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: ("image", "png", "image/png", {"width": 10, "height": 5}),
    )

    response = asyncio.run(routes.metadata_endpoint(JsonRequest({"source": source})))

    assert response.status == 200
    assert response.payload["source"] == source
    assert response.payload["kind"] == "image"
    assert response.payload["metadata"] == {"width": 10, "height": 5}
    assert str(tmp_path) not in json.dumps(response.payload)


def test_image_proxy_never_exceeds_requested_total_pixels(monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    install_runtime_stubs(monkeypatch, tmp_path)
    raw = tmp_path / "raw.png"
    Image.new("RGB", (400, 200), "red").save(raw)
    data = raw.read_bytes()
    _source_path, source = write_managed_source(tmp_path, data, "png")

    result = routes._proxy_payload(source, 100_000)
    same_bucket = routes._proxy_payload(source, 120_000)

    assert result["kind"] == "image"
    assert result["mime"] == "image/webp"
    assert result["width"] * result["height"] <= 65_536
    assert result["max_pixels"] == 65_536
    assert same_bucket["cache_key"] == result["cache_key"]
    assert len(result["cache_key"]) == 32
    assert result["url"].startswith("/api/ollama_multimodal/reference_director/cache/image_proxy/")
    cache_file = tmp_path / "reference_director" / "cache" / "image_proxy" / f"{result['cache_key']}.webp"
    with Image.open(cache_file) as preview:
        assert preview.size == (result["width"], result["height"])


def test_audio_preview_serves_only_a_validated_managed_audio_source(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    source_path, source = write_managed_source(tmp_path, b"audio", "wav")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: (
            "audio",
            "wav",
            "audio/wav",
            {"duration": 1.0},
        ),
    )

    response = asyncio.run(routes.audio_preview_endpoint(QueryRequest(source)))

    assert response.status == 200
    assert response.path == source_path
    assert response.headers == {
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": "inline",
        "Content-Type": "audio/wav",
        "X-Content-Type-Options": "nosniff",
    }


@pytest.mark.parametrize(
    ("kind", "extension", "mime"),
    [
        ("image", "png", "image/png"),
        ("video", "mp4", "video/mp4"),
    ],
)
def test_audio_preview_rejects_non_audio_media(
    monkeypatch,
    tmp_path,
    kind,
    extension,
    mime,
):
    install_runtime_stubs(monkeypatch, tmp_path)
    _source_path, source = write_managed_source(
        tmp_path,
        kind.encode("ascii"),
        extension,
    )
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: (
            kind,
            extension,
            mime,
            {"has_audio": True} if kind == "video" else {},
        ),
    )

    response = asyncio.run(routes.audio_preview_endpoint(QueryRequest(source)))

    assert response.status == 400
    assert "Only audio sources" in response.payload["error"]["message"]


def test_video_preview_serves_a_silent_video_source(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    source_path, source = write_managed_source(tmp_path, b"silent-video", "mp4")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: (
            "video",
            "mp4",
            "video/mp4",
            {"duration": 1.0, "has_audio": False},
        ),
    )

    response = asyncio.run(routes.video_preview_endpoint(QueryRequest(source)))

    assert response.status == 200
    assert response.path == source_path
    assert response.headers == {
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": "inline",
        "Content-Type": "video/mp4",
        "X-Content-Type-Options": "nosniff",
    }


@pytest.mark.parametrize(
    ("kind", "extension", "mime"),
    [
        ("image", "png", "image/png"),
        ("audio", "wav", "audio/wav"),
    ],
)
def test_video_preview_rejects_non_video_media(monkeypatch, tmp_path, kind, extension, mime):
    install_runtime_stubs(monkeypatch, tmp_path)
    _source_path, source = write_managed_source(tmp_path, kind.encode("ascii"), extension)
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: (kind, extension, mime, {}),
    )

    response = asyncio.run(routes.video_preview_endpoint(QueryRequest(source)))

    assert response.status == 400
    assert "Only video sources" in response.payload["error"]["message"]


def test_image_proxy_accepts_video_and_uses_first_decodable_frame(monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"video", "mp4")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: ("video", "mp4", "video/mp4", {"width": 300, "height": 200}),
    )
    monkeypatch.setattr(routes, "_load_proxy_frame", lambda _path, kind: Image.new("RGB", (300, 200)))

    result = routes._proxy_payload(source, 100_000)

    assert result["kind"] == "video"
    assert result["width"] * result["height"] <= 65_536


def test_waveform_returns_and_caches_requested_normalized_pairs(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"audio", "wav")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: ("audio", "wav", "audio/wav", {"duration": 1.0}),
    )
    calls = []

    def decode(_path, count, _crop, *, media_kind):
        assert media_kind == "audio"
        calls.append(count)
        return [[-1.0, 1.0] for _ in range(count)], 1.0, 1.0, {"start": 0.0, "end": 1.0}

    monkeypatch.setattr(routes, "_decode_waveform", decode)

    first = routes._waveform_payload(source, 200, None)
    second = routes._waveform_payload(source, 200, None)

    assert len(first["pairs"]) == 200
    assert first == second
    assert calls == [200]
    assert all(-1.0 <= value <= 1.0 for pair in first["pairs"] for value in pair)


def test_waveform_cache_key_canonicalizes_aliases_and_rejects_extra_fields():
    assert routes._waveform_crop_cache_key(
        {"start_time": 0, "end_time": 1}
    ) == {"start": 0.0, "end": 1.0}
    assert routes._waveform_crop_cache_key({"start": 0.0, "end": 1.0}) == {
        "start": 0.0,
        "end": 1.0,
    }

    with pytest.raises(routes.ReferenceRouteError, match="unsupported fields"):
        routes._waveform_crop_cache_key(
            {"start": 0.0, "end": 1.0, "nonce": "unbounded-key"}
        )


def test_concurrent_waveform_cache_miss_decodes_once(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"concurrent-audio", "wav")
    ready = Event()
    both_requested_lock = Event()
    release = Event()
    calls = []
    lock_requests = []

    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: (
            "audio",
            "wav",
            "audio/wav",
            {"duration": 1.0},
        ),
    )

    def decode(_path, count, _crop, *, media_kind):
        calls.append((count, media_kind))
        ready.set()
        assert release.wait(timeout=2)
        return [[-1.0, 1.0] for _ in range(count)], 1.0, 1.0, {
            "start": 0.0,
            "end": 1.0,
        }

    monkeypatch.setattr(routes, "_decode_waveform", decode)
    original_cache_lock = routes._cache_lock

    def observed_cache_lock(key):
        lock_requests.append(key)
        if len(lock_requests) == 2:
            both_requested_lock.set()
        return original_cache_lock(key)

    monkeypatch.setattr(routes, "_cache_lock", observed_cache_lock)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(routes._waveform_payload, source, 200, None)
        assert ready.wait(timeout=2)
        second = executor.submit(routes._waveform_payload, source, 200, None)
        assert both_requested_lock.wait(timeout=2)
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert calls == [(200, "audio")]
    assert lock_requests[0] == lock_requests[1]


@pytest.mark.parametrize("count", [199, 501, True, "invalid"])
def test_waveform_rejects_pair_count_outside_contract(monkeypatch, tmp_path, count):
    install_runtime_stubs(monkeypatch, tmp_path)
    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._waveform_payload({}, count, None)
    assert caught.value.code == "invalid_peak_count"


def test_apply_edit_creates_revision_and_never_mutates_original(monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    install_runtime_stubs(monkeypatch, tmp_path)
    raw = tmp_path / "raw-edit.png"
    Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(raw)
    _source_path, source = write_managed_source(tmp_path, raw.read_bytes(), "png")
    original_bytes = (tmp_path / source["path"]).read_bytes()

    result = routes._apply_edit_payload(
        {
            "source": source,
            "expected_revision": 0,
            "edit": {
                "revision": 1,
                "crop": {"x": 0.25, "y": 0.0, "width": 0.5, "height": 1.0},
                "transform": {"flip_x": True, "flip_y": False},
                "background": {"mode": "solid", "color": "#00ff00"},
            },
        }
    )

    assert (tmp_path / source["path"]).read_bytes() == original_bytes
    assert result["source"]["path"].startswith("reference_director/edits/")
    assert result["source"]["revision"] == 1
    assert result["edit"]["revision"] == 1
    assert result["metadata"]["width"] == 10
    assert result["metadata"]["height"] == 10
    sidecar = tmp_path / result["source"]["path"]
    recipe = json.loads(sidecar.with_suffix(".json").read_text(encoding="utf-8"))
    assert str(tmp_path) not in json.dumps(recipe)


def test_apply_edit_materializes_a_content_addressed_keep_mask(monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    install_runtime_stubs(monkeypatch, tmp_path)
    raw = tmp_path / "raw-mask-source.png"
    Image.new("RGBA", (4, 2), (255, 0, 0, 255)).save(raw)
    _source_path, source = write_managed_source(tmp_path, raw.read_bytes(), "png")

    raw_mask = tmp_path / "raw-keep-mask.png"
    keep_mask = Image.new("L", (4, 2), 0)
    for x in range(2):
        for y in range(2):
            keep_mask.putpixel((x, y), 255)
    keep_mask.save(raw_mask)
    _mask_path, mask_source = write_managed_source(
        tmp_path, raw_mask.read_bytes(), "png"
    )

    result = routes._apply_edit_payload(
        {
            "source": source,
            "expectedRevision": 0,
            "edit": {
                "revision": 1,
                "mask": mask_source,
                "maskMode": "keep",
                "background": {"mode": "transparent", "color": "#ffffff"},
            },
        }
    )

    assert result["edit"]["mask"] == mask_source
    output_path = tmp_path / result["source"]["path"]
    with Image.open(output_path) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((0, 0))[3] == 255
        assert output.getpixel((3, 0))[3] == 0


def test_apply_edit_uses_optional_rembg_before_materializing(monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    install_runtime_stubs(monkeypatch, tmp_path)
    raw = tmp_path / "raw-rembg-source.png"
    Image.new("RGB", (4, 2), (255, 0, 0)).save(raw)
    _source_path, source = write_managed_source(tmp_path, raw.read_bytes(), "png")
    calls = []

    def fake_remove_background(image):
        calls.append(image.size)
        output = image.copy().convert("RGBA")
        output.putalpha(Image.new("L", image.size, 127))
        return output

    monkeypatch.setattr(routes, "remove_reference_background", fake_remove_background)
    preview = routes._background_preview_payload(source)
    assert preview["url"].endswith(".webp")
    assert preview["mime"] == "image/webp"
    with Image.open(tmp_path / "reference_director" / "cache" / "background_preview" / f"{preview['foreground_cache_key']}.png") as foreground:
        assert foreground.mode == "RGBA"
        assert foreground.getpixel((0, 0))[3] == 127
    result = routes._apply_edit_payload(
        {
            "source": source,
            "expectedRevision": 0,
            "edit": {
                "revision": 1,
                "removeBackground": True,
                "background": {"mode": "transparent", "color": "#ffffff"},
            },
        }
    )

    assert calls == [(4, 2)]
    assert result["edit"]["removeBackground"] is True
    with Image.open(tmp_path / result["source"]["path"]) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((0, 0))[3] == 127


def test_apply_edit_rejects_non_boolean_background_removal(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"image", "png")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: ("image", "png", "image/png", {"width": 1, "height": 1}),
    )
    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._apply_edit_payload(
            {"source": source, "edit": {"revision": 1, "removeBackground": "yes"}}
        )
    assert caught.value.code == "invalid_edit"


def test_apply_edit_rejects_stale_revision_before_writing(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    _path, source = write_managed_source(tmp_path, b"image", "png")
    monkeypatch.setattr(
        routes,
        "_inspect_media",
        lambda _path, **_kwargs: ("image", "png", "image/png", {"width": 1, "height": 1}),
    )
    with pytest.raises(routes.ReferenceRouteError) as caught:
        routes._apply_edit_payload(
            {"source": source, "expected_revision": 2, "edit": {"revision": 1}}
        )
    assert caught.value.status == 409
    assert caught.value.code == "revision_conflict"


def test_handler_never_exposes_absolute_path_in_error(monkeypatch, tmp_path):
    install_runtime_stubs(monkeypatch, tmp_path)
    source = {
        "path": f"reference_director/sources/{'a' * 64}.png",
        "sha256": "a" * 64,
        "mime": "image/png",
    }

    response = asyncio.run(routes.metadata_endpoint(JsonRequest({"source": source})))

    assert response.status == 404
    assert str(tmp_path) not in json.dumps(response.payload)
