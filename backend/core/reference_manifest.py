from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .reference_contract import ReferenceItem, ReferenceState, execution_projection


@dataclass(frozen=True, slots=True)
class ReferenceOutputPlan:
    image_ids: tuple[str, ...]
    image_captions: tuple[str, ...]
    audio_ids: tuple[str, ...]
    audio_captions: tuple[str, ...]
    video_ids: tuple[str, ...]
    video_captions: tuple[str, ...]


def build_reference_output_plan(state: ReferenceState) -> ReferenceOutputPlan:
    projection = execution_projection(state)

    def active(name: str) -> list[dict[str, Any]]:
        return [entry for entry in projection[name] if entry["enabled"]]

    images = active("images")
    audios = active("audios")
    videos = active("videos")
    return ReferenceOutputPlan(
        image_ids=tuple(entry["id"] for entry in images),
        image_captions=tuple(entry["caption"] for entry in images),
        audio_ids=tuple(entry["id"] for entry in audios),
        audio_captions=tuple(entry["caption"] for entry in audios),
        video_ids=tuple(entry["id"] for entry in videos),
        video_captions=tuple(entry["caption"] for entry in videos),
    )


def _original_item_manifest(item: ReferenceItem) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": item.kind,
        "source": item.source.projection(),
        "caption": {"text": item.caption, "source": "user"},
        "enabled": {},
    }
    if item.image_enabled is not None:
        value["enabled"]["image"] = item.image_enabled
    if item.video_enabled is not None:
        value["enabled"]["video"] = item.video_enabled
    if item.audio_enabled is not None:
        value["enabled"]["audio"] = item.audio_enabled
    if item.crop is not None:
        value["crop"] = item.crop.projection()
    if item.edit is not None:
        value["edit"] = item.edit.projection()
    if item.audio_caption_override is not None:
        value["audio_caption_override"] = item.audio_caption_override
    return value


def _derived_audio_manifest(item: ReferenceItem) -> dict[str, Any]:
    caption = (
        item.audio_caption_override
        if item.audio_caption_override is not None
        else item.caption
    )
    value: dict[str, Any] = {
        "kind": "audio",
        "source": item.source.projection(),
        "caption": {"text": caption, "source": "user"},
        "enabled": {"audio": item.audio_enabled},
        "derived_from": item.id,
        "derivation": "embedded_audio",
    }
    if item.crop is not None:
        value["crop"] = item.crop.projection()
    return value


def build_reference_manifest(state: ReferenceState) -> dict[str, Any]:
    """Build a payload-free manifest for both active and disabled references."""

    plan = build_reference_output_plan(state)
    items: dict[str, Any] = {}
    for item_id in sorted(state.items):
        item = state.items[item_id]
        items[item_id] = _original_item_manifest(item)
        if item.kind == "video":
            items[f"{item_id}:audio"] = _derived_audio_manifest(item)

    return {
        "version": state.version,
        "video_audio_policy": state.video_audio_policy,
        "image_order": list(state.image_order),
        "video_order": list(state.video_order),
        # audio_order deliberately stores original item IDs, including videos.
        "audio_order": list(state.audio_order),
        "outputs": {
            "images": list(plan.image_ids),
            "audios": list(plan.audio_ids),
            "videos": list(plan.video_ids),
        },
        "output_captions": {
            "images": list(plan.image_captions),
            "audios": list(plan.audio_captions),
            "videos": list(plan.video_captions),
        },
        "items": items,
    }


__all__ = [
    "ReferenceOutputPlan",
    "build_reference_manifest",
    "build_reference_output_plan",
]
