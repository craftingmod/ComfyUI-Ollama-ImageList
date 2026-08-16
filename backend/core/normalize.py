from __future__ import annotations

from math import prod
from typing import Any

from .codecs import encode_audio_wav, encode_image_png
from .errors import InputNormalizationError
from .media import DEFAULT_MEDIA_LIMITS, MediaBundle, MediaItem, MediaLimits


def _as_values(values: Any) -> list[Any]:
    if isinstance(values, (list, tuple)):
        return list(values)
    return [values]


def unwrap_required_scalar(name: str, values: Any) -> Any:
    candidates = _as_values(values)
    if len(candidates) != 1:
        raise InputNormalizationError(
            f"{name} must resolve to exactly one value; received {len(candidates)} values."
        )
    if candidates[0] is None:
        raise InputNormalizationError(f"{name} is required.")
    return candidates[0]


def unwrap_optional_scalar(name: str, values: Any, default: Any) -> Any:
    if values is None:
        return default
    candidates = _as_values(values)
    if not candidates or candidates == [None]:
        return default
    if len(candidates) != 1:
        raise InputNormalizationError(
            f"{name} must resolve to at most one value; received {len(candidates)} values."
        )
    return candidates[0]


def _shape(value: Any, *, label: str) -> tuple[int, ...]:
    shape = getattr(value, "shape", None)
    if shape is None:
        raise InputNormalizationError(f"{label} is not a tensor-like value with a shape.")
    try:
        result = tuple(int(dimension) for dimension in shape)
    except (TypeError, ValueError) as exc:
        raise InputNormalizationError(f"{label} has an invalid shape {shape!r}.") from exc
    if any(dimension < 0 for dimension in result):
        raise InputNormalizationError(f"{label} has an invalid shape {result!r}.")
    return result


def _raw_bytes(value: Any, shape: tuple[int, ...]) -> int:
    try:
        return int(value.element_size()) * prod(shape)
    except (AttributeError, TypeError, ValueError):
        return 4 * prod(shape)


def _check_totals(items: list[MediaItem], raw_bytes: int, limits: MediaLimits) -> None:
    if raw_bytes > limits.max_total_raw_bytes:
        raise InputNormalizationError(
            f"Media raw size {raw_bytes} bytes exceeds the {limits.max_total_raw_bytes}-byte limit."
        )
    encoded = sum(len(item.payload) for item in items)
    if encoded > limits.max_total_encoded_bytes:
        raise InputNormalizationError(
            f"Media payload {encoded} bytes exceeds the {limits.max_total_encoded_bytes}-byte limit."
        )


def normalize_images(values: Any, *, limits: MediaLimits = DEFAULT_MEDIA_LIMITS) -> MediaBundle:
    items: list[MediaItem] = []
    raw_bytes = 0

    def visit(value: Any, depth: int, source_path: str) -> None:
        nonlocal raw_bytes
        if value is None:
            return
        if depth > limits.max_list_depth:
            raise InputNormalizationError(
                f"Image input nesting exceeds the maximum depth {limits.max_list_depth}."
            )
        if isinstance(value, (list, tuple)):
            for offset, child in enumerate(value):
                visit(child, depth + 1, f"{source_path}[{offset}]")
            return

        shape = _shape(value, label=f"Image input {source_path}")
        if len(shape) == 4:
            batch, height, width, channels = shape
            for batch_index in range(batch):
                visit(value[batch_index], depth + 1, f"{source_path}.batch[{batch_index}]")
            return
        if len(shape) != 3:
            raise InputNormalizationError(
                f"Image input {source_path} has shape {shape}; expected [H,W,C] or [B,H,W,C]."
            )

        height, width, channels = shape
        index = len(items)
        if index >= limits.max_images:
            raise InputNormalizationError(f"Image count exceeds the configured limit of {limits.max_images}.")
        if height <= 0 or width <= 0:
            raise InputNormalizationError(f"Image {index} has empty dimensions {height}×{width}.")
        if channels not in (1, 3, 4):
            raise InputNormalizationError(
                f"Image {index} has {channels} channels; expected 1, 3, or 4."
            )
        pixels = height * width
        if pixels > limits.max_pixels_per_image:
            raise InputNormalizationError(
                f"Image {index} has {pixels} pixels, exceeding the {limits.max_pixels_per_image}-pixel limit."
            )
        raw_bytes += _raw_bytes(value, shape)
        if raw_bytes > limits.max_total_raw_bytes:
            _check_totals(items, raw_bytes, limits)
        try:
            payload, digest = encode_image_png(value, height=height, width=width, channels=channels)
        except InputNormalizationError as exc:
            raise InputNormalizationError(f"Image {index}: {exc}") from exc
        items.append(
            MediaItem(
                kind="image",
                index=index,
                mime_type="image/png",
                payload=payload,
                metadata={
                    "width": width,
                    "height": height,
                    "channels": channels,
                    "sha256": digest,
                    "source": source_path,
                },
            )
        )
        _check_totals(items, raw_bytes, limits)

    visit(values, 0, "images")
    return MediaBundle(tuple(items))


def normalize_audio(values: Any, *, limits: MediaLimits = DEFAULT_MEDIA_LIMITS) -> MediaBundle:
    items: list[MediaItem] = []
    raw_bytes = 0

    def visit(value: Any, depth: int, source_path: str) -> None:
        nonlocal raw_bytes
        if value is None:
            return
        if depth > limits.max_list_depth:
            raise InputNormalizationError(
                f"Audio input nesting exceeds the maximum depth {limits.max_list_depth}."
            )
        if isinstance(value, (list, tuple)):
            for offset, child in enumerate(value):
                visit(child, depth + 1, f"{source_path}[{offset}]")
            return
        if not isinstance(value, dict) or "waveform" not in value or "sample_rate" not in value:
            raise InputNormalizationError(
                f"Audio input {source_path} must contain waveform and sample_rate."
            )

        waveform = value["waveform"]
        shape = _shape(waveform, label=f"Audio waveform {source_path}")
        if len(shape) == 2:
            batch, channels, samples = 1, shape[0], shape[1]
            batches = [waveform]
        elif len(shape) == 3:
            batch, channels, samples = shape
            batches = [waveform[index] for index in range(batch)]
        else:
            raise InputNormalizationError(
                f"Audio waveform {source_path} has shape {shape}; expected [C,T] or [B,C,T]."
            )
        try:
            sample_rate = int(value["sample_rate"])
        except (TypeError, ValueError) as exc:
            raise InputNormalizationError(f"Audio input {source_path} has an invalid sample rate.") from exc
        if sample_rate <= 0 or channels <= 0 or samples <= 0:
            raise InputNormalizationError(f"Audio input {source_path} has empty or invalid dimensions.")
        duration = samples / sample_rate
        if duration > limits.max_audio_seconds:
            raise InputNormalizationError(
                f"Audio input {source_path} is {duration:.2f}s, exceeding the {limits.max_audio_seconds:.2f}s limit."
            )

        for batch_index, audio_item in enumerate(batches):
            index = len(items)
            if index >= limits.max_audio_items:
                raise InputNormalizationError(
                    f"Audio item count exceeds the configured limit of {limits.max_audio_items}."
                )
            raw_bytes += _raw_bytes(audio_item, (channels, samples))
            if raw_bytes > limits.max_total_raw_bytes:
                _check_totals(items, raw_bytes, limits)
            try:
                payload, digest = encode_audio_wav(
                    audio_item,
                    sample_rate=sample_rate,
                    channels=channels,
                    samples=samples,
                )
            except InputNormalizationError as exc:
                raise InputNormalizationError(f"Audio {index}: {exc}") from exc
            items.append(
                MediaItem(
                    kind="audio",
                    index=index,
                    mime_type="audio/wav",
                    payload=payload,
                    metadata={
                        "sample_rate": sample_rate,
                        "channels": channels,
                        "samples": samples,
                        "duration_seconds": duration,
                        "sha256": digest,
                        "source": f"{source_path}.batch[{batch_index}]" if batch > 1 else source_path,
                    },
                )
            )
            _check_totals(items, raw_bytes, limits)

    visit(values, 0, "audio")
    return MediaBundle(tuple(items))


def normalize_media(
    *,
    images: Any = None,
    audio: Any = None,
    limits: MediaLimits = DEFAULT_MEDIA_LIMITS,
) -> MediaBundle:
    image_items = normalize_images(images, limits=limits).items
    audio_items = normalize_audio(audio, limits=limits).items
    combined = MediaBundle(tuple(image_items + audio_items)).reindexed()
    if sum(len(item.payload) for item in combined.items) > limits.max_total_encoded_bytes:
        raise InputNormalizationError(
            f"Combined media payload exceeds the {limits.max_total_encoded_bytes}-byte limit."
        )
    return combined
