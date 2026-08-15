from __future__ import annotations

import hashlib
import math
import os
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .reference_contract import (
    ImageEdit,
    ImageOutputSettings,
    ReferenceSource,
    ReferenceState,
    TimeRange,
)
from .reference_background import (
    ReferenceBackgroundRemovalError,
    ReferenceBackgroundRemovalUnavailable,
    remove_reference_background,
)


MAX_IMAGE_PIXELS = 40_000_000
MAX_REFERENCE_SOURCE_BYTES = 256 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 2 * 60 * 60
MAX_AUDIO_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_DECODED_OUTPUT_BYTES = 1024 * 1024 * 1024
MAX_VIDEO_DURATION_SECONDS = 60 * 60
HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class LoadedReferenceMedia:
    """Native ComfyUI media values, already filtered into output order."""

    images: tuple[Any, ...] = ()
    audios: tuple[Any, ...] = ()
    videos: tuple[Any, ...] = ()


class ReferenceMediaLoader(Protocol):
    def __call__(self, state: ReferenceState) -> LoadedReferenceMedia: ...


class ReferenceMediaUnavailable(RuntimeError):
    pass


class ReferenceMediaError(ValueError):
    """Raised when validated state cannot be loaded safely as native media."""


def _tensor_nbytes(value: Any) -> int:
    """Return tensor storage size without copying data to host memory."""

    numel = getattr(value, "numel", None)
    element_size = getattr(value, "element_size", None)
    if callable(numel) and callable(element_size):
        try:
            count = int(numel())
            width = int(element_size())
        except (TypeError, ValueError, OverflowError) as exc:
            raise ReferenceMediaError(
                "A decoded media tensor reported an invalid memory size."
            ) from exc
        if count < 0 or width < 0:
            raise ReferenceMediaError(
                "A decoded media tensor reported an invalid memory size."
            )
        return count * width
    waveform = value.get("waveform") if isinstance(value, dict) else None
    if waveform is not None:
        return _tensor_nbytes(waveform)
    return 0


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_reparse_point(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except OSError as exc:
        raise ReferenceMediaError("A reference source could not be inspected.") from exc
    attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_flag = getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _input_root(input_directory: str | os.PathLike[str] | None) -> Path:
    if input_directory is None:
        try:
            import folder_paths

            input_directory = folder_paths.get_input_directory()
        except Exception as exc:
            raise ReferenceMediaUnavailable(
                "ComfyUI input storage is unavailable."
            ) from exc
    try:
        root = Path(input_directory).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReferenceMediaUnavailable(
            "ComfyUI input storage is unavailable."
        ) from exc
    if not root.is_dir():
        raise ReferenceMediaUnavailable("ComfyUI input storage is unavailable.")
    return root


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise ReferenceMediaError("A reference source could not be read.") from exc
    return digest.hexdigest()


def resolve_reference_source(source: ReferenceSource, *, input_root: Path) -> Path:
    """Resolve one input-relative descriptor without traversing links or junctions."""

    relative = PurePosixPath(source.path)
    candidate = input_root.joinpath(*relative.parts)
    current = input_root
    try:
        for part in relative.parts:
            current = current / part
            if _is_reparse_point(current):
                raise ReferenceMediaError("Linked reference sources are not allowed.")
        resolved = candidate.resolve(strict=True)
    except ReferenceMediaError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ReferenceMediaError("A reference source was not found.") from exc
    if not _is_relative_to(resolved, input_root) or not resolved.is_file():
        raise ReferenceMediaError(
            "A reference source must stay inside the ComfyUI input directory."
        )
    try:
        actual_size = resolved.stat().st_size
    except OSError as exc:
        raise ReferenceMediaError("A reference source could not be inspected.") from exc
    if actual_size > MAX_REFERENCE_SOURCE_BYTES:
        raise ReferenceMediaError(
            "A reference source exceeds the 256 MiB file-size limit."
        )
    if source.size is not None and actual_size != source.size:
        raise ReferenceMediaError("A reference source size no longer matches its state.")
    if _sha256_file(resolved) != source.sha256:
        raise ReferenceMediaError("A reference source hash no longer matches its state.")
    return resolved


def _is_materialized_edit(source: ReferenceSource) -> bool:
    parts = PurePosixPath(source.path).parts
    return len(parts) >= 2 and parts[:2] == ("reference_director", "edits")


def _crop_box(image: Any, edit: ImageEdit) -> tuple[int, int, int, int] | None:
    if edit.crop is None:
        return None
    crop = edit.crop
    left = max(0, min(image.width - 1, math.floor(crop.x * image.width)))
    top = max(0, min(image.height - 1, math.floor(crop.y * image.height)))
    right = max(
        left + 1,
        min(image.width, math.ceil((crop.x + crop.width) * image.width)),
    )
    bottom = max(
        top + 1,
        min(image.height, math.ceil((crop.y + crop.height) * image.height)),
    )
    return left, top, right, bottom


def _has_image_alpha(image: Any) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def _apply_image_recipe(image: Any, edit: ImageEdit, mask: Any | None = None) -> Any:
    from PIL import Image, ImageChops, ImageColor, ImageOps

    if edit.remove_background:
        original = image
        try:
            image = remove_reference_background(image)
        except ReferenceBackgroundRemovalUnavailable as exc:
            raise ReferenceMediaUnavailable(str(exc)) from exc
        except ReferenceBackgroundRemovalError as exc:
            raise ReferenceMediaError(str(exc)) from exc
        if image is not original:
            original.close()
    crop_box = _crop_box(image, edit)
    if crop_box is not None:
        image = image.crop(crop_box)
    if edit.flip_x:
        image = ImageOps.mirror(image)
    if edit.flip_y:
        image = ImageOps.flip(image)
    if mask is not None:
        mask = mask.convert("L")
        mask_crop_box = _crop_box(mask, edit)
        if mask_crop_box is not None:
            mask = mask.crop(mask_crop_box)
        if edit.flip_x:
            mask = ImageOps.mirror(mask)
        if edit.flip_y:
            mask = ImageOps.flip(mask)
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.BILINEAR)
        if edit.mask_mode == "erase":
            mask = ImageOps.invert(mask)
        foreground = image.convert("RGBA")
        foreground.putalpha(ImageChops.multiply(foreground.getchannel("A"), mask))
        image = foreground
    if edit.background_mode == "transparent":
        return image.convert("RGBA")
    if edit.background_mode == "solid":
        rgba = ImageColor.getcolor(edit.background_color or "#ffffff", "RGBA")
        foreground = image.convert("RGBA")
        backdrop = Image.new("RGBA", foreground.size, rgba)
        backdrop.alpha_composite(foreground)
        return backdrop.convert("RGB")
    return image.convert("RGBA" if mask is not None or _has_image_alpha(image) else "RGB")


def _limit_image_pixels(image: Any, max_pixels: int | None) -> Any:
    if max_pixels is None or image.width * image.height <= max_pixels:
        return image
    from PIL import Image

    scale = math.sqrt(max_pixels / (image.width * image.height))
    width = max(1, math.floor(image.width * scale))
    height = max(1, math.floor(image.height * scale))
    while width * height > max_pixels:
        if width >= height and width > 1:
            width -= 1
        elif height > 1:
            height -= 1
        else:
            break
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    if resized is not image:
        image.close()
    return resized


def _composite_image_alpha(image: Any, background_color: str) -> Any:
    if not _has_image_alpha(image):
        return image
    composite = _apply_image_recipe(
        image,
        ImageEdit(
            background_mode="solid",
            background_color=background_color,
        ),
    )
    if composite is not image:
        image.close()
    return composite


def _load_image(
    path: Path,
    source: ReferenceSource,
    edit: ImageEdit | None,
    mask_path: Path | None = None,
    *,
    max_output_bytes: int | None = None,
    max_pixels: int | None = None,
    composite_alpha: bool = False,
    alpha_background: str = "#000000",
) -> Any:
    try:
        from PIL import Image, ImageOps
        import numpy as np
        import torch
    except Exception as exc:
        raise ReferenceMediaUnavailable(
            "Image decoding requires Pillow, NumPy, and torch."
        ) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as opened:
                opened.load()
                image = ImageOps.exif_transpose(opened).copy()
    except Exception as exc:
        raise ReferenceMediaError("An image reference could not be decoded.") from exc
    mask = None
    try:
        if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
            raise ReferenceMediaError(
                f"An image reference exceeds the {MAX_IMAGE_PIXELS}-pixel limit."
            )
        if _is_materialized_edit(source):
            image = image.convert("RGBA" if _has_image_alpha(image) else "RGB")
        elif edit is not None:
            if mask_path is not None:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", Image.DecompressionBombWarning)
                        with Image.open(mask_path) as opened_mask:
                            opened_mask.load()
                            mask = ImageOps.exif_transpose(opened_mask).copy()
                except Exception as exc:
                    raise ReferenceMediaError(
                        "An image edit mask could not be decoded."
                    ) from exc
                if (
                    mask.width <= 0
                    or mask.height <= 0
                    or mask.width * mask.height > MAX_IMAGE_PIXELS
                ):
                    raise ReferenceMediaError(
                        f"An image edit mask exceeds the {MAX_IMAGE_PIXELS}-pixel limit."
                    )
            image = _apply_image_recipe(image, edit, mask)
        else:
            image = image.convert("RGBA" if _has_image_alpha(image) else "RGB")
        if composite_alpha:
            image = _composite_image_alpha(image, alpha_background)
        image = _limit_image_pixels(image, max_pixels)
        channels = len(image.getbands())
        output_bytes = image.width * image.height * channels * 4
        if max_output_bytes is not None and output_bytes > max_output_bytes:
            raise ReferenceMediaError(
                "Decoded IMAGE/AUDIO outputs exceed the 1 GiB aggregate memory limit."
            )
        array = np.array(image, dtype=np.float32, copy=True) / 255.0
        return torch.from_numpy(array).unsqueeze(0)
    finally:
        if mask is not None:
            mask.close()
        image.close()


def _resampled_frames(resampler: Any, frame: Any) -> list[Any]:
    result = resampler.resample(frame)
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return list(result)
    return [result]


def _audio_frame_array(frame: Any, np: Any) -> tuple[Any, int]:
    array = np.asarray(frame.to_ndarray(), dtype=np.float32)
    channels = int(getattr(getattr(frame, "layout", None), "nb_channels", 0) or 0)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    elif channels and array.shape[0] != channels:
        if array.ndim == 2 and array.shape[1] == channels:
            array = array.T
        else:
            array = array.reshape(channels, -1)
    if array.ndim != 2 or array.shape[0] <= 0 or array.shape[1] <= 0:
        raise ReferenceMediaError("An audio reference produced an invalid waveform.")
    return array, channels or int(array.shape[0])


def _load_audio(
    path: Path,
    crop: TimeRange | None,
    *,
    max_output_bytes: int | None = None,
) -> dict[str, Any]:
    try:
        import av
        import numpy as np
        import torch
    except Exception as exc:
        raise ReferenceMediaUnavailable(
            "Audio decoding requires PyAV, NumPy, and torch."
        ) from exc

    arrays: list[Any] = []
    sample_rate = 0
    channels = 0
    decoded_samples = 0
    selected_samples = 0
    crop_start_sample: int | None = None
    crop_end_sample: int | None = None
    if crop is not None and crop.end > MAX_AUDIO_DURATION_SECONDS:
        raise ReferenceMediaError(
            "An audio crop exceeds the 2-hour decoded-duration limit."
        )

    def consume(frame: Any) -> bool:
        nonlocal channels
        nonlocal crop_end_sample
        nonlocal crop_start_sample
        nonlocal decoded_samples
        nonlocal sample_rate
        nonlocal selected_samples

        array, frame_channels = _audio_frame_array(frame, np)
        frame_rate = int(getattr(frame, "sample_rate", 0) or 0)
        if frame_rate <= 0:
            frame_rate = int(
                getattr(stream.codec_context, "sample_rate", 0) or 0
            )
        if frame_rate <= 0:
            raise ReferenceMediaError(
                "The audio reference has no valid sample rate."
            )
        if sample_rate and sample_rate != frame_rate:
            raise ReferenceMediaError(
                "The audio reference changed sample rate while decoding."
            )
        if channels and channels != frame_channels:
            raise ReferenceMediaError(
                "The audio reference changed channel count while decoding."
            )
        sample_rate = frame_rate
        channels = frame_channels
        if crop is not None and crop_start_sample is None:
            crop_start_sample = int(round(crop.start * sample_rate))
            crop_end_sample = int(round(crop.end * sample_rate))

        frame_start = decoded_samples
        frame_samples = int(array.shape[1])
        max_samples = sample_rate * MAX_AUDIO_DURATION_SECONDS
        if frame_samples > max_samples - decoded_samples:
            raise ReferenceMediaError(
                "An audio reference exceeds the 2-hour decoded-duration limit."
            )
        decoded_samples += frame_samples

        selected_start = frame_start if crop_start_sample is None else crop_start_sample
        selected_end = decoded_samples if crop_end_sample is None else crop_end_sample
        left = max(frame_start, selected_start)
        right = min(decoded_samples, selected_end)
        if right > left:
            next_selected_samples = selected_samples + right - left
            next_output_bytes = next_selected_samples * channels * 4
            if (
                max_output_bytes is not None
                and next_output_bytes > max_output_bytes
            ):
                raise ReferenceMediaError(
                    "Decoded IMAGE/AUDIO outputs exceed the 1 GiB aggregate memory limit."
                )
            if next_output_bytes > MAX_AUDIO_OUTPUT_BYTES:
                raise ReferenceMediaError(
                    "A decoded AUDIO output exceeds the 256 MiB waveform-memory limit."
                )
            arrays.append(array[:, left - frame_start : right - frame_start])
            selected_samples = next_selected_samples
        return crop_end_sample is not None and decoded_samples >= crop_end_sample

    try:
        with av.open(str(path), mode="r") as container:
            stream = next(
                (
                    candidate
                    for candidate in container.streams.audio
                    if getattr(candidate, "codec_context", None) is not None
                ),
                None,
            )
            if stream is None:
                raise ReferenceMediaError("The reference has no decodable audio stream.")
            resampler = av.audio.resampler.AudioResampler(format="fltp")
            selection_complete = False
            for decoded in container.decode(stream):
                for frame in _resampled_frames(resampler, decoded):
                    if consume(frame):
                        selection_complete = True
                        break
                if selection_complete:
                    break
            if not selection_complete:
                for frame in _resampled_frames(resampler, None):
                    if consume(frame):
                        selection_complete = True
                        break
    except ReferenceMediaError:
        raise
    except Exception as exc:
        raise ReferenceMediaError("An audio reference could not be decoded.") from exc
    if not arrays or sample_rate <= 0:
        raise ReferenceMediaError("The reference has no decodable audio samples.")
    if crop_end_sample is not None and decoded_samples < crop_end_sample:
        raise ReferenceMediaError(
            "An audio crop must stay inside the decoded source duration."
        )
    waveform = np.concatenate(arrays, axis=1)
    return {
        "waveform": torch.from_numpy(
            np.ascontiguousarray(waveform, dtype=np.float32)
        ).unsqueeze(0),
        "sample_rate": sample_rate,
    }


def _video_input_impl() -> Any:
    try:
        from comfy_api.v0_0_2 import InputImpl
    except ImportError:  # pragma: no cover - newer development builds
        try:
            from comfy_api.latest import InputImpl
        except ImportError as exc:
            raise ReferenceMediaUnavailable(
                "The ComfyUI VIDEO implementation is unavailable."
            ) from exc
    return InputImpl


def _is_attached_video_stream(stream: Any) -> bool:
    disposition = getattr(stream, "disposition", None)
    if disposition is None:
        return False
    flag = getattr(type(disposition), "attached_pic", None)
    try:
        if flag is not None:
            return bool(disposition & flag)
    except TypeError:
        pass
    return getattr(disposition, "attached_pic", None) is True


def _validate_video_stream_layout(path: Path) -> None:
    try:
        import av

        with av.open(str(path), mode="r") as container:
            physical_videos = list(container.streams.video)
            physical_audios = list(container.streams.audio)
            primary_videos = [
                stream
                for stream in physical_videos
                if getattr(stream, "codec_context", None) is not None
                and not _is_attached_video_stream(stream)
            ]
            if (
                len(physical_videos) != 1
                or len(primary_videos) != 1
                or physical_videos[0] is not primary_videos[0]
                or len(physical_audios) > 1
                or any(
                    getattr(stream, "codec_context", None) is None
                    for stream in physical_audios
                )
            ):
                raise ReferenceMediaError(
                    "Videos must contain one primary video track, at most one audio track, and no attached-picture video track."
                )
    except ReferenceMediaError:
        raise
    except Exception as exc:
        raise ReferenceMediaError(
            "A video stream layout could not be inspected."
        ) from exc


def _load_video(path: Path, crop: TimeRange | None) -> Any:
    _validate_video_stream_layout(path)
    video = _video_input_impl().VideoFromFile(str(path))
    try:
        duration = float(video.get_duration())
    except Exception as exc:
        raise ReferenceMediaError("A video duration could not be inspected.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ReferenceMediaError("A video duration could not be inspected.")
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise ReferenceMediaError(
            "A video reference exceeds the 1-hour duration limit."
        )
    if crop is None:
        return video
    if crop.end > duration + 1e-6:
        raise ReferenceMediaError(
            "A video crop must stay inside the decoded source duration."
        )
    trimmed = video.as_trimmed(
        start_time=crop.start,
        duration=crop.end - crop.start,
        strict_duration=False,
    )
    if trimmed is None:
        raise ReferenceMediaError("A video crop produced an empty reference.")
    return trimmed


def validate_reference_sources(
    state: ReferenceState,
    *,
    input_directory: str | os.PathLike[str] | None = None,
) -> None:
    """Strongly validate every source that can contribute to this execution.

    This is intentionally suitable for ``fingerprint_inputs``: ComfyUI calls it
    even when a previous node result is cached, so externally replaced managed
    files cannot bypass the size/SHA-256 checks in the execution loader.
    """

    root = _input_root(input_directory)
    sources: set[ReferenceSource] = set()
    for item_id in state.image_order:
        item = state.items[item_id]
        if not item.image_enabled:
            continue
        sources.add(item.source)
        if (
            item.kind == "image"
            and not _is_materialized_edit(item.source)
            and item.edit is not None
            and item.edit.mask is not None
        ):
            sources.add(item.edit.mask)
    for item_id in state.video_order:
        item = state.items[item_id]
        if item.video_enabled:
            sources.add(item.source)
    for item_id in state.audio_order:
        item = state.items[item_id]
        if item.audio_enabled:
            sources.add(item.source)
    for source in sources:
        resolve_reference_source(source, input_root=root)


def load_reference_media(
    state: ReferenceState,
    *,
    input_directory: str | os.PathLike[str] | None = None,
    image_output: ImageOutputSettings | None = None,
) -> LoadedReferenceMedia:
    """Decode active references into independent native ComfyUI list items.

    Pillow, PyAV, NumPy, torch, folder_paths, and InputImpl are imported only on
    the code paths that need them, keeping extension registration dependency-free.
    """

    root = _input_root(input_directory)
    resolved: dict[ReferenceSource, Path] = {}

    def source_path(source: ReferenceSource) -> Path:
        if source not in resolved:
            resolved[source] = resolve_reference_source(source, input_root=root)
        return resolved[source]

    images: list[Any] = []
    videos: list[Any] = []
    audios: list[Any] = []
    decoded_output_bytes = 0
    max_image_pixels = (
        image_output.max_pixels
        if image_output is not None and image_output.limit_pixels
        else None
    )

    def retain(value: Any, output: list[Any]) -> None:
        nonlocal decoded_output_bytes

        decoded_output_bytes += _tensor_nbytes(value)
        if decoded_output_bytes > MAX_DECODED_OUTPUT_BYTES:
            raise ReferenceMediaError(
                "Decoded IMAGE/AUDIO outputs exceed the 1 GiB aggregate memory limit."
            )
        output.append(value)

    for item_id in state.image_order:
        item = state.items[item_id]
        if not item.image_enabled:
            continue
        path = source_path(item.source)
        mask_path = (
            source_path(item.edit.mask)
            if (
                not _is_materialized_edit(item.source)
                and item.edit is not None
                and item.edit.mask is not None
            )
            else None
        )
        retain(
            _load_image(
                path,
                item.source,
                item.edit,
                mask_path,
                max_output_bytes=MAX_DECODED_OUTPUT_BYTES
                - decoded_output_bytes,
                max_pixels=max_image_pixels,
                composite_alpha=(
                    image_output.composite_alpha
                    if image_output is not None
                    else False
                ),
                alpha_background=(
                    image_output.alpha_background
                    if image_output is not None
                    else "#000000"
                ),
            ),
            images,
        )
    for item_id in state.video_order:
        item = state.items[item_id]
        if not item.video_enabled:
            continue
        videos.append(_load_video(source_path(item.source), item.crop))
    for item_id in state.audio_order:
        item = state.items[item_id]
        if not item.audio_enabled:
            continue
        retain(
            _load_audio(
                source_path(item.source),
                item.crop,
                max_output_bytes=MAX_DECODED_OUTPUT_BYTES
                - decoded_output_bytes,
            ),
            audios,
        )
    return LoadedReferenceMedia(
        images=tuple(images),
        audios=tuple(audios),
        videos=tuple(videos),
    )


__all__ = [
    "LoadedReferenceMedia",
    "MAX_DECODED_OUTPUT_BYTES",
    "MAX_AUDIO_OUTPUT_BYTES",
    "ReferenceMediaLoader",
    "ReferenceMediaError",
    "ReferenceMediaUnavailable",
    "load_reference_media",
    "resolve_reference_source",
    "validate_reference_sources",
]
