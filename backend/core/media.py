from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


MediaKind = Literal["image", "audio"]


@dataclass(frozen=True, slots=True)
class MediaItem:
    kind: MediaKind
    index: int
    mime_type: str
    payload: bytes
    metadata: dict[str, Any]

    def manifest(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "index": self.index,
            "mime_type": self.mime_type,
            "byte_size": len(self.payload),
            **self.metadata,
        }


@dataclass(frozen=True, slots=True)
class MediaBundle:
    items: tuple[MediaItem, ...] = ()

    def manifest(self) -> dict[str, Any]:
        image_count = sum(item.kind == "image" for item in self.items)
        audio_count = sum(item.kind == "audio" for item in self.items)
        return {
            "media_count": len(self.items),
            "image_count": image_count,
            "audio_count": audio_count,
            "total_encoded_bytes": sum(len(item.payload) for item in self.items),
            "items": [item.manifest() for item in self.items],
        }

    def reindexed(self, *, start: int = 0) -> "MediaBundle":
        return MediaBundle(
            tuple(
                MediaItem(
                    kind=item.kind,
                    index=start + offset,
                    mime_type=item.mime_type,
                    payload=item.payload,
                    metadata=item.metadata,
                )
                for offset, item in enumerate(self.items)
            )
        )


@dataclass(frozen=True, slots=True)
class MediaLimits:
    max_images: int = 32
    max_audio_items: int = 8
    max_pixels_per_image: int = 40_000_000
    max_total_raw_bytes: int = 512 * 1024 * 1024
    max_total_encoded_bytes: int = 128 * 1024 * 1024
    max_audio_seconds: float = 600.0
    max_list_depth: int = 16


DEFAULT_MEDIA_LIMITS = MediaLimits()
