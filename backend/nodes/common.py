from __future__ import annotations

from typing import Any

from ..core import DEFAULT_MEDIA_LIMITS, InputNormalizationError, MediaBundle, MediaItem


def collect_bundles(values: Any) -> MediaBundle:
    if values is None:
        return MediaBundle()
    candidates = values if isinstance(values, (list, tuple)) else [values]
    items: list[MediaItem] = []

    def visit(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, MediaBundle):
            items.extend(value.items)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
            return
        raise InputNormalizationError(
            f"media must contain MULTIMODAL_MEDIA bundles, received {type(value).__name__}."
        )

    for candidate in candidates:
        visit(candidate)
    return MediaBundle(tuple(items)).reindexed()


def combine_bundles(*bundles: MediaBundle) -> MediaBundle:
    combined = MediaBundle(tuple(item for bundle in bundles for item in bundle.items)).reindexed()
    image_count = sum(item.kind == "image" for item in combined.items)
    audio_count = sum(item.kind == "audio" for item in combined.items)
    encoded_bytes = sum(len(item.payload) for item in combined.items)
    if image_count > DEFAULT_MEDIA_LIMITS.max_images:
        raise InputNormalizationError(
            f"Combined image count exceeds the configured limit of {DEFAULT_MEDIA_LIMITS.max_images}."
        )
    if audio_count > DEFAULT_MEDIA_LIMITS.max_audio_items:
        raise InputNormalizationError(
            f"Combined audio count exceeds the configured limit of {DEFAULT_MEDIA_LIMITS.max_audio_items}."
        )
    if encoded_bytes > DEFAULT_MEDIA_LIMITS.max_total_encoded_bytes:
        raise InputNormalizationError(
            "Combined media payload exceeds the configured encoded byte limit."
        )
    return combined
