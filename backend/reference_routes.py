from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import stat
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .core.reference_background import (
    ReferenceBackgroundRemovalError,
    ReferenceBackgroundRemovalUnavailable,
    remove_reference_background,
)


ROUTE_PREFIX = "/ollama_multimodal/reference_director"
UPLOAD_ROUTE = f"{ROUTE_PREFIX}/upload"
METADATA_ROUTE = f"{ROUTE_PREFIX}/metadata"
IMAGE_PROXY_ROUTE = f"{ROUTE_PREFIX}/image_proxy"
AUDIO_PREVIEW_ROUTE = f"{ROUTE_PREFIX}/audio_preview"
VIDEO_PREVIEW_ROUTE = f"{ROUTE_PREFIX}/video_preview"
WAVEFORM_ROUTE = f"{ROUTE_PREFIX}/waveform"
APPLY_EDIT_ROUTE = f"{ROUTE_PREFIX}/apply_edit"
CACHE_VIEW_ROUTE = f"{ROUTE_PREFIX}/cache/{{kind}}/{{filename}}"

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
DEFAULT_PROXY_PIXELS = 1_000_000
MAX_PROXY_PIXELS = 16_000_000
PROXY_PIXEL_BUCKETS = (
    65_536,
    262_144,
    1_000_000,
    2_000_000,
    4_000_000,
    8_000_000,
    16_000_000,
)
# Keep upload/edit inspection aligned with the execution loader.  Accepting an
# image here that the node can never emit makes an otherwise successful upload
# fail only when the workflow is queued.
MAX_DECODE_PIXELS = 40_000_000
MAX_AUDIO_DURATION_SECONDS = 2 * 60 * 60
MAX_VIDEO_DURATION_SECONDS = 60 * 60
MIN_WAVEFORM_PAIRS = 200
MAX_WAVEFORM_PAIRS = 500

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CACHE_FILE_RE = re.compile(r"^[0-9a-f]{32}(?:[0-9a-f]{32})?\.webp$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_INVALID_UPLOAD_FILENAME_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_WINDOWS_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_ALLOWED_SOURCE_AREAS = frozenset({"sources", "edits", "masks"})
_SOURCE_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".wav",
        ".mp3",
        ".flac",
        ".ogg",
        ".opus",
        ".m4a",
        ".aac",
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
        ".mka",
        ".avi",
    }
)
_AREA_SUFFIXES = {
    "sources": _SOURCE_SUFFIXES,
    "edits": frozenset({".png"}),
    "masks": frozenset({".png"}),
}
_registered_route_ids: set[int] = set()
_CACHE_LOCKS = tuple(threading.Lock() for _ in range(64))
_UPLOAD_STORAGE_LOCK = threading.Lock()
_MEDIA_WORK_SEMAPHORE = threading.BoundedSemaphore(4)


@dataclass(frozen=True)
class ReferenceRouteError(Exception):
    status: int
    code: str
    message: str


@dataclass(frozen=True)
class ResolvedSource:
    path: Path
    relative_path: str
    sha256: str
    mime: str
    size: int

    def descriptor(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "mime": self.mime,
            "sha256": self.sha256,
            "size": self.size,
        }


def _bad_request(code: str, message: str) -> ReferenceRouteError:
    return ReferenceRouteError(400, code, message)


def _limited_media_work(function: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Cap concurrent decoder work across otherwise independent HTTP requests."""

    with _MEDIA_WORK_SEMAPHORE:
        return function(*args, **kwargs)


def _input_root() -> Path:
    try:
        import folder_paths

        root = folder_paths.get_input_directory()
    except Exception as exc:
        raise ReferenceRouteError(
            503,
            "storage_unavailable",
            "ComfyUI input storage is unavailable.",
        ) from exc
    try:
        return Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReferenceRouteError(
            503,
            "storage_unavailable",
            "ComfyUI input storage is unavailable.",
        ) from exc


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _ensure_managed_directory(*parts: str) -> Path:
    root = _input_root()
    current = root
    for part in ("reference_director", *parts):
        if not part or part in {".", ".."} or "/" in part or "\\" in part:
            raise ReferenceRouteError(500, "storage_error", "Media storage is unavailable.")
        current = current / part
        try:
            if current.exists() and _is_link_like(current):
                raise ReferenceRouteError(
                    503,
                    "storage_unavailable",
                    "Media storage is unavailable.",
                )
            current.mkdir(exist_ok=True)
            resolved = current.resolve(strict=True)
        except ReferenceRouteError:
            raise
        except (OSError, RuntimeError) as exc:
            raise ReferenceRouteError(
                503,
                "storage_unavailable",
                "Media storage is unavailable.",
            ) from exc
        if not _is_relative_to(resolved, root):
            raise ReferenceRouteError(
                503,
                "storage_unavailable",
                "Media storage is unavailable.",
            )
        current = resolved
    return current


def _normalize_source_path(source: Mapping[str, Any]) -> str:
    value = source.get("path")
    if value is None:
        source_type = source.get("type", "input")
        subfolder = source.get("subfolder")
        filename = source.get("filename")
        if source_type != "input" or not isinstance(subfolder, str) or not isinstance(filename, str):
            raise _bad_request("invalid_source", "source.path must be a managed input path.")
        value = f"{subfolder.rstrip('/')}/{filename}"
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        raise _bad_request("invalid_source", "source.path must be a managed input path.")
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise _bad_request("invalid_source", "source.path must be a managed input path.")
    parts = pure.parts
    if len(parts) != 3 or parts[0] != "reference_director" or parts[1] not in _ALLOWED_SOURCE_AREAS:
        raise _bad_request("invalid_source", "source.path must be a managed input path.")
    filename = parts[2]
    if filename != Path(filename).name or ":" in filename:
        raise _bad_request("invalid_source", "source.path must be a managed input path.")
    suffix = Path(filename).suffix.lower()
    if suffix not in _AREA_SUFFIXES[parts[1]]:
        raise _bad_request("invalid_source", "source.path must identify a supported media file.")
    return pure.as_posix()


def _mime_from_suffix(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".mka": "audio/x-matroska",
        ".avi": "video/x-msvideo",
    }.get(path.suffix.lower(), "application/octet-stream")


def _resolve_source(source: Any) -> ResolvedSource:
    if not isinstance(source, Mapping):
        raise _bad_request("invalid_source", "source must be an object.")
    relative = _normalize_source_path(source)
    root = _input_root()
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReferenceRouteError(404, "source_not_found", "The media source was not found.") from exc
    if not _is_relative_to(resolved, root) or not resolved.is_file():
        raise ReferenceRouteError(404, "source_not_found", "The media source was not found.")

    current = root
    try:
        for part in PurePosixPath(relative).parts:
            current = current / part
            if _is_link_like(current):
                raise _bad_request("invalid_source", "Symlinked media sources are not allowed.")
    except OSError as exc:
        raise ReferenceRouteError(404, "source_not_found", "The media source was not found.") from exc

    supplied_hash = source.get("sha256")
    if (
        not isinstance(supplied_hash, str)
        or not _HASH_RE.fullmatch(supplied_hash.lower())
    ):
        raise _bad_request("source_mismatch", "The media source identity is missing or invalid.")
    supplied_hash = supplied_hash.lower()
    area = PurePosixPath(relative).parts[1]
    if area == "sources":
        source_hash = supplied_hash
    else:
        source_hash = resolved.stem.lower()
        if resolved.name.endswith("-mask.png"):
            source_hash = resolved.name.removesuffix("-mask.png").lower()
        if not _HASH_RE.fullmatch(source_hash):
            raise _bad_request("invalid_source", "The media source name is invalid.")
        if supplied_hash != source_hash:
            raise _bad_request("source_mismatch", "The media source identity does not match its path.")
    expected_mime = _mime_from_suffix(resolved)
    mime = source.get("mime", source.get("mime_type"))
    if mime is None:
        mime = expected_mime
    elif (
        not isinstance(mime, str)
        or len(mime) > 100
        or mime.lower() != expected_mime
    ):
        raise _bad_request(
            "source_mismatch",
            "The media source MIME type does not match its extension.",
        )
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise ReferenceRouteError(404, "source_not_found", "The media source was not found.") from exc
    if size > MAX_UPLOAD_BYTES:
        raise ReferenceRouteError(413, "source_too_large", "The media source exceeds 256 MiB.")
    supplied_size = source.get("size")
    if supplied_size is not None and (
        isinstance(supplied_size, bool)
        or not isinstance(supplied_size, int)
        or supplied_size != size
    ):
        raise _bad_request("source_mismatch", "The media source size does not match its descriptor.")
    try:
        actual_hash = _sha256_file(resolved)
    except OSError as exc:
        raise ReferenceRouteError(404, "source_not_found", "The media source was not found.") from exc
    if actual_hash != source_hash:
        raise _bad_request("source_mismatch", "The media source content does not match its identity.")
    return ResolvedSource(resolved, relative, source_hash, mime.lower(), size)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(UPLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _image_details(path: Path, *, verify_only: bool = False) -> tuple[str, str, dict[str, Any]]:
    try:
        from PIL import Image
    except Exception as exc:
        raise ReferenceRouteError(503, "decoder_unavailable", "Image decoding is unavailable.") from exc

    format_map = {
        "PNG": ("png", "image/png"),
        "JPEG": ("jpg", "image/jpeg"),
        "WEBP": ("webp", "image/webp"),
        "GIF": ("gif", "image/gif"),
        "BMP": ("bmp", "image/bmp"),
        "TIFF": ("tiff", "image/tiff"),
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image_format = str(image.format or "").upper()
                if image_format not in format_map:
                    raise ValueError("unsupported image")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_DECODE_PIXELS:
                    raise ReferenceRouteError(
                        413,
                        "image_too_large",
                        "The decoded image exceeds the pixel limit.",
                    )
                metadata = {
                    "width": width,
                    "height": height,
                    "mode": str(image.mode),
                    "frame_count": int(getattr(image, "n_frames", 1)),
                }
                if verify_only:
                    image.verify()
    except ReferenceRouteError:
        raise
    except Exception as exc:
        raise ReferenceRouteError(415, "unsupported_media", "The uploaded file is not supported media.") from exc
    extension, mime = format_map[image_format]
    return extension, mime, metadata


def _looks_like_image(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(16)
    except OSError as exc:
        raise ReferenceRouteError(404, "source_not_found", "The media source was not found.") from exc
    return bool(
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or header.startswith((b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*"))
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _fraction_float(value: Any) -> float | None:
    result = _safe_float(value)
    return result if result and result > 0 else None


def _container_duration(container: Any, stream: Any = None) -> float | None:
    if stream is not None and getattr(stream, "duration", None) is not None:
        try:
            duration = _safe_float(stream.duration * stream.time_base)
        except (TypeError, ValueError, OverflowError):
            duration = None
        if duration is not None and duration > 0:
            return duration
    duration = getattr(container, "duration", None)
    if duration is None:
        return None
    try:
        import av

        return _safe_float(duration / av.time_base)
    except Exception:
        return None


def _enforce_duration_limit(kind: str, duration: float | None) -> None:
    if duration is None:
        return
    if kind == "audio":
        limit = MAX_AUDIO_DURATION_SECONDS
        label = "audio"
    elif kind == "video":
        limit = MAX_VIDEO_DURATION_SECONDS
        label = "video"
    else:
        return
    if duration > limit + 1e-6:
        raise ReferenceRouteError(
            413,
            "media_duration_exceeded",
            f"The {label} duration exceeds the supported limit.",
        )


def _is_attached_picture(stream: Any) -> bool:
    disposition = getattr(stream, "disposition", None)
    if disposition is None:
        return False
    if isinstance(disposition, Mapping):
        return bool(disposition.get("attached_pic", False))
    flag = getattr(type(disposition), "attached_pic", None)
    try:
        if flag is not None:
            return bool(disposition & flag)
    except TypeError:
        pass
    direct = getattr(disposition, "attached_pic", None)
    return direct is True


def _supported_streams(container: Any, kind: str) -> list[Any]:
    streams = getattr(getattr(container, "streams", None), kind, ())
    return [
        stream
        for stream in streams
        if getattr(stream, "codec_context", None) is not None
        and (kind != "video" or not _is_attached_picture(stream))
    ]


def _validate_comfy_video_layout(
    container: Any,
    video_streams: list[Any],
) -> None:
    """Keep proxy/metadata track selection identical to Comfy's VIDEO value."""

    if not video_streams:
        return
    physical_videos = list(getattr(container.streams, "video", ()))
    physical_audios = list(getattr(container.streams, "audio", ()))
    if (
        len(physical_videos) != 1
        or physical_videos[0] is not video_streams[0]
        or len(physical_audios) > 1
        or any(
            getattr(stream, "codec_context", None) is None
            for stream in physical_audios
        )
    ):
        raise ReferenceRouteError(
            415,
            "unsupported_stream_layout",
            "Videos must contain one primary video track, at most one audio track, and no attached-picture video track.",
        )


def _av_details(path: Path) -> tuple[str, str, dict[str, Any]]:
    try:
        import av
    except Exception as exc:
        raise ReferenceRouteError(503, "decoder_unavailable", "Audio/video decoding is unavailable.") from exc
    try:
        with av.open(str(path), mode="r") as container:
            video_streams = _supported_streams(container, "video")
            audio_streams = _supported_streams(container, "audio")
            _validate_comfy_video_layout(container, video_streams)
            if not video_streams and not audio_streams:
                raise ValueError("no supported streams")
            names = {name.strip().lower() for name in str(container.format.name or "").split(",")}
            if video_streams:
                stream = video_streams[0]
                extension, mime = _video_container_type(names, path.suffix.lower())
                width = int(getattr(stream.codec_context, "width", 0) or 0)
                height = int(getattr(stream.codec_context, "height", 0) or 0)
                if width <= 0 or height <= 0 or width * height > MAX_DECODE_PIXELS:
                    raise ReferenceRouteError(413, "video_too_large", "The decoded video frame exceeds the pixel limit.")
                duration = _container_duration(container, stream)
                _enforce_duration_limit("video", duration)
                metadata = {
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "frame_rate": _fraction_float(getattr(stream, "average_rate", None)),
                    "has_audio": bool(audio_streams),
                }
                return "video", extension, {"mime": mime, **metadata}
            stream = audio_streams[0]
            extension, mime = _audio_container_type(names, path.suffix.lower())
            duration = _container_duration(container, stream)
            _enforce_duration_limit("audio", duration)
            metadata = {
                "duration": duration,
                "sample_rate": int(getattr(stream.codec_context, "sample_rate", 0) or 0) or None,
                "channels": int(getattr(stream.codec_context, "channels", 0) or 0) or None,
            }
            return "audio", extension, {"mime": mime, **metadata}
    except ReferenceRouteError:
        raise
    except Exception as exc:
        raise ReferenceRouteError(415, "unsupported_media", "The uploaded file is not supported media.") from exc


def _video_container_type(names: set[str], suffix_hint: str = "") -> tuple[str, str]:
    if names & {"matroska", "matroska,webm"}:
        if suffix_hint == ".webm":
            return "webm", "video/webm"
        return "mkv", "video/x-matroska"
    if "webm" in names:
        return "webm", "video/webm"
    if "avi" in names:
        return "avi", "video/x-msvideo"
    if names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}:
        if suffix_hint == ".mov":
            return "mov", "video/quicktime"
        return "mp4", "video/mp4"
    raise ReferenceRouteError(415, "unsupported_media", "The video container is not supported.")


def _audio_container_type(names: set[str], suffix_hint: str = "") -> tuple[str, str]:
    for name, result in (
        ("wav", ("wav", "audio/wav")),
        ("mp3", ("mp3", "audio/mpeg")),
        ("flac", ("flac", "audio/flac")),
        ("ogg", ("ogg", "audio/ogg")),
        ("aac", ("aac", "audio/aac")),
    ):
        if name in names:
            if name == "ogg" and suffix_hint == ".opus":
                return "opus", "audio/ogg"
            return result
    if names & {"matroska", "matroska,webm"}:
        return "mka", "audio/x-matroska"
    if names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}:
        return "m4a", "audio/mp4"
    raise ReferenceRouteError(415, "unsupported_media", "The audio container is not supported.")


def _inspect_media(path: Path, *, verify_image: bool = False) -> tuple[str, str, str, dict[str, Any]]:
    if _looks_like_image(path):
        extension, mime, metadata = _image_details(path, verify_only=verify_image)
        kind = "image"
    else:
        kind, extension, metadata = _av_details(path)
        mime = str(metadata.pop("mime"))
    if path.suffix.lower() in _SOURCE_SUFFIXES and _mime_from_suffix(path) != mime:
        raise ReferenceRouteError(
            415,
            "media_type_mismatch",
            "The media content does not match its file extension.",
        )
    return kind, extension, mime, metadata


def _metadata_payload(source_value: Any) -> dict[str, Any]:
    source = _resolve_source(source_value)
    kind, _extension, mime, metadata = _inspect_media(source.path)
    canonical = ResolvedSource(source.path, source.relative_path, source.sha256, mime, source.size)
    return {"source": canonical.descriptor(), "kind": kind, "metadata": metadata}


def _cache_key(namespace: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {"namespace": namespace, **payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_lock(key: str) -> threading.Lock:
    """Bound duplicate cache work without retaining one lock per user asset."""

    return _CACHE_LOCKS[int(key[:8], 16) % len(_CACHE_LOCKS)]


def _safe_upload_filename(value: str, *, extension: str, mime: str) -> str:
    basename = value.replace("\\", "/").rsplit("/", 1)[-1]
    basename = _INVALID_UPLOAD_FILENAME_RE.sub("_", basename).strip().rstrip(".")
    original = Path(basename)
    if basename and _mime_from_suffix(original) == mime:
        suffix = original.suffix
        stem = original.stem
    else:
        suffix = f".{extension}"
        stem = original.stem if original.suffix else original.name
    stem = stem.strip().rstrip(".") or "reference"
    if stem.upper() in _WINDOWS_RESERVED_FILENAMES:
        stem = f"_{stem}"
    maximum_stem = max(1, 180 - len(suffix))
    return f"{stem[:maximum_stem]}{suffix}"


def _store_uploaded_source(
    temporary: Path,
    sources: Path,
    filename: str,
    sha256: str,
    size: int,
) -> tuple[Path, bool]:
    with _UPLOAD_STORAGE_LOCK:
        original = Path(filename)
        for index in range(1, 10_001):
            candidate = sources / (
                original.name
                if index == 1
                else f"{original.stem} ({index}){original.suffix}"
            )
            if candidate.exists():
                if _is_link_like(candidate):
                    raise ReferenceRouteError(409, "storage_conflict", "A media identity conflict was detected.")
                if candidate.stat().st_size == size and _sha256_file(candidate) == sha256:
                    return candidate, False
                continue
            os.replace(temporary, candidate)
            return candidate, True
    raise ReferenceRouteError(409, "storage_conflict", "Too many media files use the same name.")


def _atomic_json(path: Path, payload: Any) -> None:
    try:
        if path.exists() and _is_link_like(path):
            raise ReferenceRouteError(503, "storage_unavailable", "Media storage is unavailable.")
    except ReferenceRouteError:
        raise
    except OSError as exc:
        raise ReferenceRouteError(503, "storage_unavailable", "Media storage is unavailable.") from exc
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _load_proxy_frame(path: Path, kind: str):
    try:
        from PIL import Image, ImageOps
    except Exception as exc:
        raise ReferenceRouteError(503, "decoder_unavailable", "Image decoding is unavailable.") from exc

    if kind == "image":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as original:
                    original.load()
                    return ImageOps.exif_transpose(original).copy()
        except Exception as exc:
            raise ReferenceRouteError(422, "decode_failed", "The image could not be decoded.") from exc

    if kind != "video":
        raise _bad_request("invalid_media_kind", "Only image and video sources can have an image proxy.")
    try:
        import av

        with av.open(str(path), mode="r") as container:
            stream = next(iter(_supported_streams(container, "video")), None)
            if stream is None:
                raise ValueError("no video stream")
            for index, frame in enumerate(container.decode(stream)):
                if index >= 120:
                    break
                image = frame.to_image()
                if image.width > 0 and image.height > 0:
                    return image
    except Exception as exc:
        raise ReferenceRouteError(422, "decode_failed", "A video preview frame could not be decoded.") from exc
    raise ReferenceRouteError(422, "decode_failed", "A video preview frame could not be decoded.")


def _load_or_create_proxy(
    destination: Path,
    source: ResolvedSource,
    kind: str,
    max_pixels: int,
) -> tuple[int, int]:
    width = height = 0
    if destination.exists() and _is_link_like(destination):
        raise ReferenceRouteError(500, "cache_error", "The preview cache could not be read.")
    if not destination.exists():
        image = _load_proxy_frame(source.path, kind)
        try:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_DECODE_PIXELS:
                raise ReferenceRouteError(413, "image_too_large", "The decoded image exceeds the pixel limit.")
            if width * height > max_pixels:
                scale = math.sqrt(max_pixels / (width * height))
                width = max(1, math.floor(width * scale))
                height = max(1, math.floor(height * scale))
                while width * height > max_pixels:
                    if width >= height and width > 1:
                        width -= 1
                    elif height > 1:
                        height -= 1
                    else:
                        break
                try:
                    from PIL import Image

                    resampling = Image.Resampling.LANCZOS
                except AttributeError:
                    from PIL import Image

                    resampling = Image.LANCZOS
                image = image.resize((width, height), resampling)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
            try:
                image.save(temporary, format="WEBP", quality=82, method=4)
                os.replace(temporary, destination)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        finally:
            image.close()
    if width <= 0 or height <= 0:
        try:
            from PIL import Image

            with Image.open(destination) as cached:
                width, height = cached.size
        except Exception as exc:
            raise ReferenceRouteError(500, "cache_error", "The preview cache could not be read.") from exc
    return width, height


def _proxy_payload(source_value: Any, max_pixels_value: Any) -> dict[str, Any]:
    if isinstance(max_pixels_value, bool):
        raise _bad_request("invalid_max_pixels", "max_pixels must be an integer.")
    try:
        max_pixels = int(max_pixels_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _bad_request("invalid_max_pixels", "max_pixels must be an integer.") from exc
    if max_pixels < PROXY_PIXEL_BUCKETS[0] or max_pixels > MAX_PROXY_PIXELS:
        raise _bad_request(
            "invalid_max_pixels",
            f"max_pixels must be between {PROXY_PIXEL_BUCKETS[0]} and {MAX_PROXY_PIXELS}.",
        )
    max_pixels = max(
        bucket for bucket in PROXY_PIXEL_BUCKETS if bucket <= max_pixels
    )
    source = _resolve_source(source_value)
    kind, _extension, mime, _metadata = _inspect_media(source.path)
    if kind not in {"image", "video"}:
        raise _bad_request("invalid_media_kind", "Only image and video sources can have an image proxy.")
    key = _cache_key("image_proxy_v1", {"sha256": source.sha256, "max_pixels": max_pixels})[:32]
    directory = _ensure_managed_directory("cache", "image_proxy")
    destination = directory / f"{key}.webp"
    with _cache_lock(key):
        width, height = _load_or_create_proxy(destination, source, kind, max_pixels)
    canonical = ResolvedSource(source.path, source.relative_path, source.sha256, mime, source.size)
    return {
        "source": canonical.descriptor(),
        "kind": kind,
        "url": f"/api{ROUTE_PREFIX}/cache/image_proxy/{key}.webp",
        "cache_key": key,
        "mime": "image/webp",
        "width": width,
        "height": height,
        "max_pixels": max_pixels,
    }


def _audio_frame_envelope(frame: Any):
    try:
        import numpy as np
    except Exception as exc:
        raise ReferenceRouteError(503, "decoder_unavailable", "Waveform processing is unavailable.") from exc
    array = frame.to_ndarray()
    if array.size == 0:
        return np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32)
    if np.issubdtype(array.dtype, np.integer):
        info = np.iinfo(array.dtype)
        divisor = float(max(abs(info.min), abs(info.max)))
        values = array.astype(np.float32) / divisor
    else:
        values = array.astype(np.float32, copy=False)
    samples = int(getattr(frame, "samples", 0) or 0)
    if samples <= 0:
        samples = values.size
    layout = getattr(frame, "layout", None)
    channel_count = len(getattr(layout, "channels", ()) or ())
    frame_format = getattr(frame, "format", None)
    is_planar = bool(getattr(frame_format, "is_planar", False))
    if values.ndim == 1:
        if channel_count > 1 and values.size == samples * channel_count and not is_planar:
            channels = values.reshape(samples, channel_count).T
        else:
            channels = values.reshape(1, -1)
    elif values.shape[-1] == samples and (is_planar or values.shape[0] == channel_count):
        channels = values.reshape(-1, samples)
    elif channel_count > 0 and values.size == samples * channel_count:
        channels = values.reshape(samples, channel_count).T
    else:
        channels = values.reshape(1, -1)
    return channels.min(axis=0), channels.max(axis=0)


def _audio_stream_info(path: Path, *, media_kind: str) -> tuple[int, int, float]:
    try:
        import av
    except Exception as exc:
        raise ReferenceRouteError(503, "decoder_unavailable", "Audio decoding is unavailable.") from exc
    total_samples = 0
    sample_rate = 0
    try:
        with av.open(str(path), mode="r") as container:
            stream = next(iter(_supported_streams(container, "audio")), None)
            if stream is None:
                raise ReferenceRouteError(422, "audio_missing", "The media source has no audio stream.")
            sample_rate = int(getattr(stream.codec_context, "sample_rate", 0) or 0)
            for frame in container.decode(stream):
                total_samples += int(getattr(frame, "samples", 0) or 0)
                if not sample_rate:
                    sample_rate = int(getattr(frame, "sample_rate", 0) or 0)
                if sample_rate > 0:
                    _enforce_duration_limit(media_kind, total_samples / sample_rate)
    except ReferenceRouteError:
        raise
    except Exception as exc:
        raise ReferenceRouteError(422, "decode_failed", "The audio stream could not be decoded.") from exc
    if sample_rate <= 0 or total_samples <= 0:
        raise ReferenceRouteError(422, "decode_failed", "The audio stream could not be decoded.")
    duration = total_samples / sample_rate
    _enforce_duration_limit(media_kind, duration)
    return total_samples, sample_rate, duration


def _normalize_crop(crop_value: Any, duration: float) -> tuple[float, float]:
    if crop_value is None:
        return 0.0, duration
    if not isinstance(crop_value, Mapping):
        raise _bad_request("invalid_crop", "crop must be an object.")
    start_value = crop_value.get("start", crop_value.get("start_time", 0.0))
    end_value = crop_value.get("end", crop_value.get("end_time", duration))
    try:
        start = float(start_value)
        end = float(end_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _bad_request("invalid_crop", "crop start and end must be finite seconds.") from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > duration + 1e-6:
        raise _bad_request("invalid_crop", "crop must be a non-empty range within the source duration.")
    return start, min(end, duration)


def _waveform_crop_cache_key(crop_value: Any) -> dict[str, float] | None:
    if crop_value is None:
        return None
    if not isinstance(crop_value, Mapping):
        raise _bad_request("invalid_crop", "crop must be an object.")
    allowed = {"start", "end", "start_time", "end_time"}
    if any(key not in allowed for key in crop_value):
        raise _bad_request("invalid_crop", "crop contains unsupported fields.")
    start_value = crop_value.get("start", crop_value.get("start_time"))
    end_value = crop_value.get("end", crop_value.get("end_time"))
    try:
        start = float(start_value)
        end = float(end_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _bad_request(
            "invalid_crop",
            "crop must contain finite start and end seconds.",
        ) from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise _bad_request(
            "invalid_crop",
            "crop must satisfy 0 <= start < end.",
        )
    return {"start": start, "end": end}


def _decode_waveform(
    path: Path,
    pair_count: int,
    crop_value: Any,
    *,
    media_kind: str,
) -> tuple[list[list[float]], float, float, dict[str, float]]:
    total_samples, sample_rate, duration = _audio_stream_info(path, media_kind=media_kind)
    crop_start, crop_end = _normalize_crop(crop_value, duration)
    start_sample = min(total_samples, max(0, round(crop_start * sample_rate)))
    end_sample = min(total_samples, max(start_sample + 1, round(crop_end * sample_rate)))
    selected_samples = end_sample - start_sample
    try:
        import av
        import numpy as np
    except Exception as exc:
        raise ReferenceRouteError(503, "decoder_unavailable", "Waveform processing is unavailable.") from exc
    minima = np.full(pair_count, np.inf, dtype=np.float32)
    maxima = np.full(pair_count, -np.inf, dtype=np.float32)
    offset = 0
    try:
        with av.open(str(path), mode="r") as container:
            stream = next(iter(_supported_streams(container, "audio")), None)
            if stream is None:
                raise ReferenceRouteError(422, "audio_missing", "The media source has no audio stream.")
            for frame in container.decode(stream):
                frame_min, frame_max = _audio_frame_envelope(frame)
                frame_count = len(frame_min)
                frame_start = offset
                frame_end = offset + frame_count
                offset = frame_end
                left = max(frame_start, start_sample)
                right = min(frame_end, end_sample)
                if right <= left:
                    if frame_start >= end_sample:
                        break
                    continue
                local_left = left - frame_start
                local_right = right - frame_start
                positions = np.arange(left - start_sample, right - start_sample, dtype=np.int64)
                bins = np.minimum(pair_count - 1, (positions * pair_count) // selected_samples)
                np.minimum.at(minima, bins, frame_min[local_left:local_right])
                np.maximum.at(maxima, bins, frame_max[local_left:local_right])
    except ReferenceRouteError:
        raise
    except Exception as exc:
        raise ReferenceRouteError(422, "decode_failed", "The audio stream could not be decoded.") from exc
    empty = ~np.isfinite(minima) | ~np.isfinite(maxima)
    minima[empty] = 0.0
    maxima[empty] = 0.0
    peak = float(max(np.max(np.abs(minima)), np.max(np.abs(maxima))))
    if peak > 0:
        minima /= peak
        maxima /= peak
    pairs = [[round(float(low), 6), round(float(high), 6)] for low, high in zip(minima, maxima, strict=True)]
    return pairs, duration, crop_end - crop_start, {"start": crop_start, "end": crop_end}


def _waveform_payload(source_value: Any, pair_count_value: Any, crop_value: Any) -> dict[str, Any]:
    if isinstance(pair_count_value, bool):
        raise _bad_request("invalid_peak_count", "peak_count must be an integer.")
    try:
        pair_count = int(pair_count_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _bad_request("invalid_peak_count", "peak_count must be an integer.") from exc
    if pair_count < MIN_WAVEFORM_PAIRS or pair_count > MAX_WAVEFORM_PAIRS:
        raise _bad_request(
            "invalid_peak_count",
            f"peak_count must be between {MIN_WAVEFORM_PAIRS} and {MAX_WAVEFORM_PAIRS}.",
        )
    source = _resolve_source(source_value)
    kind, _extension, mime, _metadata = _inspect_media(source.path)
    if kind not in {"audio", "video"}:
        raise _bad_request("invalid_media_kind", "Only audio and video sources can have a waveform.")
    crop_key = _waveform_crop_cache_key(crop_value)
    key = _cache_key(
        "waveform_v1",
        {"sha256": source.sha256, "peak_count": pair_count, "crop": crop_key},
    )
    directory = _ensure_managed_directory("cache", "waveform")
    destination = directory / f"{key}.json"
    with _cache_lock(key):
        cached: dict[str, Any] | None = None
        if destination.exists() and _is_link_like(destination):
            raise ReferenceRouteError(500, "cache_error", "The waveform cache could not be read.")
        if destination.exists():
            try:
                loaded = json.loads(destination.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and len(loaded.get("pairs", [])) == pair_count:
                    cached = loaded
            except (OSError, ValueError, TypeError):
                cached = None
        if cached is None:
            pairs, duration, selected_duration, crop = _decode_waveform(
                source.path,
                pair_count,
                crop_key,
                media_kind=kind,
            )
            cached = {
                "pairs": pairs,
                "peak_count": pair_count,
                "duration": duration,
                "selected_duration": selected_duration,
                "crop": crop,
            }
            _atomic_json(destination, cached)
    canonical = ResolvedSource(source.path, source.relative_path, source.sha256, mime, source.size)
    return {
        "source": canonical.descriptor(),
        "kind": kind,
        "cache_key": key,
        **cached,
    }


def _normalized_image_crop(value: Any) -> dict[str, float]:
    if value is None:
        return {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
    if not isinstance(value, Mapping):
        raise _bad_request("invalid_edit", "edit.crop must be an object.")
    try:
        crop = {name: float(value[name]) for name in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _bad_request("invalid_edit", "edit.crop must contain normalized x, y, width, and height.") from exc
    if not all(math.isfinite(number) for number in crop.values()):
        raise _bad_request("invalid_edit", "edit.crop values must be finite.")
    if (
        crop["x"] < 0
        or crop["y"] < 0
        or crop["width"] <= 0
        or crop["height"] <= 0
        or crop["x"] + crop["width"] > 1.0 + 1e-9
        or crop["y"] + crop["height"] > 1.0 + 1e-9
    ):
        raise _bad_request("invalid_edit", "edit.crop must be a non-empty normalized rectangle.")
    return crop


def _current_revision(source_value: Mapping[str, Any], source: ResolvedSource) -> int:
    has_supplied_revision = "revision" in source_value
    supplied = source_value.get("revision", 0)
    if isinstance(supplied, bool) or not isinstance(supplied, int) or supplied < 0:
        raise _bad_request("invalid_revision", "source.revision must be a non-negative integer.")
    if PurePosixPath(source.relative_path).parts[1] != "edits":
        if supplied != 0:
            raise ReferenceRouteError(409, "revision_conflict", "The source revision is stale.")
        return 0
    sidecar = source.path.with_suffix(".json")
    if not sidecar.is_file() or _is_link_like(sidecar):
        raise ReferenceRouteError(409, "revision_conflict", "The source edit history is unavailable.")
    try:
        stored = json.loads(sidecar.read_text(encoding="utf-8"))
        revision = stored.get("edit", {}).get("revision")
    except (OSError, ValueError, AttributeError) as exc:
        raise ReferenceRouteError(409, "revision_conflict", "The source edit history is unavailable.") from exc
    if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0:
        if has_supplied_revision and supplied != revision:
            raise ReferenceRouteError(409, "revision_conflict", "The source revision is stale.")
        return revision
    raise ReferenceRouteError(409, "revision_conflict", "The source edit history is unavailable.")


def _normalize_edit(edit_value: Any, current_revision: int) -> tuple[dict[str, Any], Any]:
    if not isinstance(edit_value, Mapping):
        raise _bad_request("invalid_edit", "edit must be an object.")
    revision = edit_value.get("revision", current_revision + 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision != current_revision + 1:
        raise ReferenceRouteError(409, "revision_conflict", "edit.revision must be the next source revision.")
    transform_value = edit_value.get("transform", {})
    if transform_value is None:
        transform_value = {}
    if not isinstance(transform_value, Mapping):
        raise _bad_request("invalid_edit", "edit.transform must be an object.")
    for name, default in (("scale", 1.0), ("offset_x", 0.0), ("offset_y", 0.0), ("rotation", 0.0)):
        try:
            number = float(transform_value.get(name, default))
        except (TypeError, ValueError, OverflowError) as exc:
            raise _bad_request("invalid_edit", f"edit.transform.{name} must be finite.") from exc
        if not math.isfinite(number) or abs(number - default) > 1e-9:
            raise _bad_request("unsupported_edit", "Pan, zoom, and rotation are not supported by this editor revision.")
    flip_x = transform_value.get(
        "flip_x",
        edit_value.get(
            "flipX",
            edit_value.get("flip_x", edit_value.get("flip_horizontal", False)),
        ),
    )
    flip_y = transform_value.get(
        "flip_y",
        edit_value.get(
            "flipY",
            edit_value.get("flip_y", edit_value.get("flip_vertical", False)),
        ),
    )
    if not isinstance(flip_x, bool) or not isinstance(flip_y, bool):
        raise _bad_request("invalid_edit", "Image flip values must be booleans.")
    remove_background = edit_value.get(
        "removeBackground", edit_value.get("remove_background", False)
    )
    if not isinstance(remove_background, bool):
        raise _bad_request("invalid_edit", "edit.removeBackground must be a boolean.")
    background_value = edit_value.get("background", {"mode": "transparent", "color": "#ffffff"})
    if not isinstance(background_value, Mapping):
        raise _bad_request("invalid_edit", "edit.background must be an object.")
    mode = background_value.get("mode", "transparent")
    color = background_value.get("color", "#ffffff")
    if mode not in {"transparent", "solid"} or not isinstance(color, str) or not _COLOR_RE.fullmatch(color):
        raise _bad_request("invalid_edit", "edit.background must use transparent or solid mode and a hex color.")
    mask_value = edit_value.get("mask", edit_value.get("mask_file"))
    mask_mode = edit_value.get("maskMode", edit_value.get("mask_mode", "keep"))
    if mask_mode not in {"keep", "erase"}:
        raise _bad_request("invalid_edit", "edit.mask_mode must be keep or erase.")
    normalized = {
        "crop": _normalized_image_crop(edit_value.get("crop")),
        "flipX": flip_x,
        "flipY": flip_y,
        "background": {"mode": mode, "color": color.lower()},
        "revision": revision,
    }
    if remove_background:
        normalized["removeBackground"] = True
    if mask_value is not None:
        normalized["maskMode"] = mask_mode
    return normalized, mask_value


def _load_edit_image(path: Path):
    try:
        from PIL import Image, ImageOps

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as original:
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGBA")
    except Exception as exc:
        raise ReferenceRouteError(422, "decode_failed", "The image could not be decoded.") from exc
    if image.width * image.height > MAX_DECODE_PIXELS:
        image.close()
        raise ReferenceRouteError(413, "image_too_large", "The decoded image exceeds the pixel limit.")
    return image


def _apply_edit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    source_value = payload.get("source")
    if not isinstance(source_value, Mapping):
        raise _bad_request("invalid_source", "source must be an object.")
    source = _resolve_source(source_value)
    kind, _extension, _mime, _metadata = _inspect_media(source.path)
    if kind != "image":
        raise _bad_request("invalid_media_kind", "Only image sources can be edited.")
    current_revision = _current_revision(source_value, source)
    expected_revision = payload.get("expected_revision", payload.get("expectedRevision", current_revision))
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != current_revision:
        raise ReferenceRouteError(409, "revision_conflict", "The source revision is stale.")
    edit, mask_value = _normalize_edit(payload.get("edit", payload.get("recipe")), current_revision)
    mask_source: ResolvedSource | None = None
    if mask_value is not None:
        if isinstance(mask_value, str):
            mask_value = {"path": mask_value}
        mask_source = _resolve_source(mask_value)
        mask_kind, _mask_extension, _mask_mime, _mask_metadata = _inspect_media(mask_source.path)
        if mask_kind != "image":
            raise _bad_request("invalid_edit", "edit mask must be an image source.")
        edit["mask"] = mask_source.descriptor()

    image = _load_edit_image(source.path)
    try:
        from PIL import Image, ImageChops, ImageColor, ImageOps, PngImagePlugin

        if edit.get("removeBackground"):
            original = image
            try:
                image = remove_reference_background(image)
            except ReferenceBackgroundRemovalUnavailable as exc:
                raise ReferenceRouteError(501, "rembg_unavailable", str(exc)) from exc
            except ReferenceBackgroundRemovalError as exc:
                raise ReferenceRouteError(422, "background_removal_failed", str(exc)) from exc
            if image is not original:
                original.close()
        crop = edit["crop"]
        left = max(0, min(image.width - 1, math.floor(crop["x"] * image.width)))
        top = max(0, min(image.height - 1, math.floor(crop["y"] * image.height)))
        right = max(left + 1, min(image.width, math.ceil((crop["x"] + crop["width"]) * image.width)))
        bottom = max(top + 1, min(image.height, math.ceil((crop["y"] + crop["height"]) * image.height)))
        image = image.crop((left, top, right, bottom))
        if edit["flipX"]:
            image = ImageOps.mirror(image)
        if edit["flipY"]:
            image = ImageOps.flip(image)
        if mask_source is not None:
            with Image.open(mask_source.path) as opened_mask:
                opened_mask.load()
                mask = opened_mask.convert("L")
            mask_left = max(0, min(mask.width - 1, math.floor(crop["x"] * mask.width)))
            mask_top = max(0, min(mask.height - 1, math.floor(crop["y"] * mask.height)))
            mask_right = max(
                mask_left + 1,
                min(mask.width, math.ceil((crop["x"] + crop["width"]) * mask.width)),
            )
            mask_bottom = max(
                mask_top + 1,
                min(mask.height, math.ceil((crop["y"] + crop["height"]) * mask.height)),
            )
            mask = mask.crop((mask_left, mask_top, mask_right, mask_bottom))
            if edit["flipX"]:
                mask = ImageOps.mirror(mask)
            if edit["flipY"]:
                mask = ImageOps.flip(mask)
            if mask.size != image.size:
                mask = mask.resize(image.size, Image.Resampling.BILINEAR)
            if edit.get("maskMode") == "erase":
                mask = ImageOps.invert(mask)
            alpha = ImageChops.multiply(image.getchannel("A"), mask)
            image.putalpha(alpha)
        background = edit["background"]
        if background["mode"] == "solid":
            rgba = ImageColor.getcolor(background["color"], "RGBA")
            backdrop = Image.new("RGBA", image.size, rgba)
            backdrop.alpha_composite(image)
            image = backdrop.convert("RGB")

        edits_directory = _ensure_managed_directory("edits")
        temporary = edits_directory / f".edit-{secrets.token_hex(12)}.tmp"
        try:
            edit_identity = {
                "schema_version": 1,
                "source_sha256": source.sha256,
                "mask_sha256": mask_source.sha256 if mask_source is not None else None,
                "edit": edit,
            }
            png_info = PngImagePlugin.PngInfo()
            png_info.add_text(
                "reference_director",
                json.dumps(
                    edit_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ),
                zip=True,
            )
            image.save(temporary, format="PNG", optimize=True, pnginfo=png_info)
            if temporary.stat().st_size > MAX_UPLOAD_BYTES:
                raise ReferenceRouteError(413, "edit_too_large", "The edited image exceeds 256 MiB.")
            output_hash = _sha256_file(temporary)
            destination = edits_directory / f"{output_hash}.png"
            if destination.exists():
                if _is_link_like(destination) or _sha256_file(destination) != output_hash:
                    raise ReferenceRouteError(409, "storage_conflict", "A media identity conflict was detected.")
            else:
                os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        image.close()

    result_source = ResolvedSource(
        destination,
        f"reference_director/edits/{destination.name}",
        output_hash,
        "image/png",
        destination.stat().st_size,
    )
    sidecar_payload = {
        "schema_version": 1,
        "source": source.descriptor(),
        "edit": edit,
    }
    _atomic_json(destination.with_suffix(".json"), sidecar_payload)
    result = _metadata_payload(result_source.descriptor())
    result["source"]["revision"] = edit["revision"]
    result["edit"] = edit
    proxy = _proxy_payload(result["source"], DEFAULT_PROXY_PIXELS)
    result["proxy_url"] = proxy["url"]
    result["cache_key"] = proxy["cache_key"]
    return result


async def _request_json(request: Any) -> Mapping[str, Any]:
    content_length = getattr(request, "content_length", None)
    if isinstance(content_length, int) and content_length > MAX_JSON_BYTES:
        raise ReferenceRouteError(413, "request_too_large", "The JSON request is too large.")
    try:
        content = getattr(request, "content", None)
        iter_chunked = getattr(content, "iter_chunked", None)
        if content_length is None and callable(iter_chunked):
            body = bytearray()
            async for chunk in iter_chunked(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_JSON_BYTES:
                    raise ReferenceRouteError(
                        413,
                        "request_too_large",
                        "The JSON request is too large.",
                    )
            payload = json.loads(body)
        else:
            payload = await request.json()
    except ReferenceRouteError:
        raise
    except Exception as exc:
        raise _bad_request("invalid_json", "Request body must be valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise _bad_request("invalid_json", "Request body must be a JSON object.")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise ReferenceRouteError(413, "request_too_large", "The JSON request is too large.")
    return payload


def _json_response(payload: Any, *, status: int = 200):
    from aiohttp import web

    return web.json_response(payload, status=status)


def _error_response(error: ReferenceRouteError):
    return _json_response(
        {"error": {"code": error.code, "message": error.message}},
        status=error.status,
    )


async def upload_endpoint(request: Any):
    temporary: Path | None = None
    try:
        content_type = str(getattr(request, "content_type", ""))
        if content_type and content_type.lower() != "multipart/form-data":
            raise _bad_request("invalid_upload", "Upload requests must use multipart/form-data.")
        try:
            reader = await request.multipart()
            part = await reader.next()
        except Exception as exc:
            raise _bad_request("invalid_upload", "The multipart upload could not be read.") from exc
        if part is None or getattr(part, "name", None) != "file" or not getattr(part, "filename", None):
            raise _bad_request("invalid_upload", "A single multipart file field named file is required.")
        incoming = await asyncio.to_thread(_ensure_managed_directory, ".incoming")
        temporary = incoming / f"upload-{secrets.token_hex(16)}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("x+b") as output:
                while True:
                    chunk = await part.read_chunk(size=UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise _bad_request("invalid_upload", "The multipart file data is invalid.")
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ReferenceRouteError(413, "upload_too_large", "The uploaded file exceeds 256 MiB.")
                    digest.update(chunk)
                    output.write(chunk)
        except ReferenceRouteError:
            raise
        except OSError as exc:
            raise ReferenceRouteError(503, "storage_unavailable", "Media storage is unavailable.") from exc
        if size == 0:
            raise _bad_request("empty_upload", "The uploaded file is empty.")
        try:
            extra_part = await reader.next()
        except Exception as exc:
            raise _bad_request("invalid_upload", "The multipart upload could not be read.") from exc
        if extra_part is not None:
            raise _bad_request("invalid_upload", "Only one multipart file is allowed.")

        kind, extension, mime, metadata = await asyncio.to_thread(
            _limited_media_work,
            _inspect_media,
            temporary,
            verify_image=True,
        )
        sha256 = digest.hexdigest()
        sources = await asyncio.to_thread(_ensure_managed_directory, "sources")
        upload_filename = _safe_upload_filename(
            str(part.filename),
            extension=extension,
            mime=mime,
        )
        destination, moved = await asyncio.to_thread(
            _store_uploaded_source,
            temporary,
            sources,
            upload_filename,
            sha256,
            size,
        )
        if moved:
            temporary = None
        source = ResolvedSource(
            destination,
            f"reference_director/sources/{destination.name}",
            sha256,
            mime,
            size,
        )
        return _json_response({"source": source.descriptor(), "kind": kind, "metadata": metadata}, status=201)
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The upload could not be completed."))
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


async def metadata_endpoint(request: Any):
    try:
        payload = await _request_json(request)
        result = await asyncio.to_thread(
            _limited_media_work,
            _metadata_payload,
            payload.get("source"),
        )
        return _json_response(result)
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "Media metadata could not be read."))


async def image_proxy_endpoint(request: Any):
    try:
        payload = await _request_json(request)
        max_pixels = payload.get("max_pixels", payload.get("maxPixels", DEFAULT_PROXY_PIXELS))
        result = await asyncio.to_thread(
            _limited_media_work,
            _proxy_payload,
            payload.get("source"),
            max_pixels,
        )
        return _json_response(result)
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The media preview could not be created."))


async def _media_preview_response(request: Any, *, expected_kind: str):
    query = getattr(request, "query", {})
    query_get = getattr(query, "get", None)
    source_json = query_get("source") if callable(query_get) else None
    if not isinstance(source_json, str) or not source_json or len(source_json) > 4096:
        raise _bad_request("invalid_source", "A bounded source descriptor is required.")
    try:
        source_value = json.loads(source_json)
    except (TypeError, ValueError) as exc:
        raise _bad_request("invalid_source", "The source descriptor is invalid JSON.") from exc
    source = await asyncio.to_thread(_resolve_source, source_value)
    kind, _extension, mime, _metadata = await asyncio.to_thread(_inspect_media, source.path)
    if kind != expected_kind:
        raise _bad_request(
            "invalid_media_kind",
            f"Only {expected_kind} sources can use this preview route.",
        )
    from aiohttp import web

    return web.FileResponse(
        source.path,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline",
            "Content-Type": mime,
            "X-Content-Type-Options": "nosniff",
        },
    )


async def audio_preview_endpoint(request: Any):
    try:
        return await _media_preview_response(request, expected_kind="audio")
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The audio preview could not be served."))


async def video_preview_endpoint(request: Any):
    try:
        return await _media_preview_response(request, expected_kind="video")
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The video preview could not be served."))


async def waveform_endpoint(request: Any):
    try:
        payload = await _request_json(request)
        pair_count = payload.get(
            "peak_count",
            payload.get("peakCount", payload.get("pair_count", MIN_WAVEFORM_PAIRS)),
        )
        result = await asyncio.to_thread(
            _limited_media_work,
            _waveform_payload,
            payload.get("source"),
            pair_count,
            payload.get("crop"),
        )
        return _json_response(result)
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The waveform could not be created."))


async def apply_edit_endpoint(request: Any):
    try:
        payload = await _request_json(request)
        result = await asyncio.to_thread(
            _limited_media_work,
            _apply_edit_payload,
            payload,
        )
        return _json_response(result, status=201)
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The image edit could not be applied."))


async def cache_view_endpoint(request: Any):
    try:
        match_info = getattr(request, "match_info", {})
        kind = match_info.get("kind")
        filename = match_info.get("filename")
        if kind != "image_proxy" or not isinstance(filename, str) or not _CACHE_FILE_RE.fullmatch(filename):
            raise ReferenceRouteError(404, "cache_not_found", "The cached asset was not found.")
        directory = await asyncio.to_thread(_ensure_managed_directory, "cache", "image_proxy")
        candidate = directory / filename
        try:
            if candidate.exists() and _is_link_like(candidate):
                raise ReferenceRouteError(404, "cache_not_found", "The cached asset was not found.")
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ReferenceRouteError(404, "cache_not_found", "The cached asset was not found.") from exc
        if not _is_relative_to(resolved, directory) or not resolved.is_file():
            raise ReferenceRouteError(404, "cache_not_found", "The cached asset was not found.")
        from aiohttp import web

        return web.FileResponse(
            resolved,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Type": "image/webp",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except ReferenceRouteError as error:
        return _error_response(error)
    except Exception:
        return _error_response(ReferenceRouteError(500, "internal_error", "The cached asset could not be served."))


def register_reference_routes(routes: Any | None = None) -> None:
    if routes is None:
        from server import PromptServer

        routes = PromptServer.instance.routes
    route_id = id(routes)
    if route_id in _registered_route_ids:
        return
    routes.post(UPLOAD_ROUTE)(upload_endpoint)
    routes.post(METADATA_ROUTE)(metadata_endpoint)
    routes.post(IMAGE_PROXY_ROUTE)(image_proxy_endpoint)
    routes.get(AUDIO_PREVIEW_ROUTE)(audio_preview_endpoint)
    routes.get(VIDEO_PREVIEW_ROUTE)(video_preview_endpoint)
    routes.post(WAVEFORM_ROUTE)(waveform_endpoint)
    routes.post(APPLY_EDIT_ROUTE)(apply_edit_endpoint)
    routes.get(CACHE_VIEW_ROUTE)(cache_view_endpoint)
    _registered_route_ids.add(route_id)


__all__ = [
    "APPLY_EDIT_ROUTE",
    "AUDIO_PREVIEW_ROUTE",
    "CACHE_VIEW_ROUTE",
    "IMAGE_PROXY_ROUTE",
    "MAX_AUDIO_DURATION_SECONDS",
    "MAX_VIDEO_DURATION_SECONDS",
    "MAX_UPLOAD_BYTES",
    "METADATA_ROUTE",
    "MIN_WAVEFORM_PAIRS",
    "MAX_WAVEFORM_PAIRS",
    "PROXY_PIXEL_BUCKETS",
    "ROUTE_PREFIX",
    "UPLOAD_ROUTE",
    "VIDEO_PREVIEW_ROUTE",
    "WAVEFORM_ROUTE",
    "apply_edit_endpoint",
    "audio_preview_endpoint",
    "cache_view_endpoint",
    "image_proxy_endpoint",
    "metadata_endpoint",
    "register_reference_routes",
    "upload_endpoint",
    "video_preview_endpoint",
    "waveform_endpoint",
]
