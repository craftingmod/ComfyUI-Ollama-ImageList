from __future__ import annotations

import json
from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..core import InputNormalizationError


LlamaCppMediaDiagnosticsType = io.Custom(
    "OLLAMA_IMAGE_LIST_LLAMA_CPP_MEDIA_DIAGNOSTICS"
)


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputNormalizationError("media_diagnostics must be a diagnostics object.")
    return value


def _count(section: Any, key: str) -> int:
    if not isinstance(section, dict):
        return 0
    try:
        return max(0, int(section.get(key, 0)))
    except (TypeError, ValueError):
        return 0


def format_media_diagnostics(diagnostics: dict[str, Any]) -> str:
    capabilities = diagnostics.get("capabilities", {})
    requested = diagnostics.get("requested", {})
    evaluated = diagnostics.get("evaluated", {})
    mtmd = diagnostics.get("mtmd", {})

    vision_available = bool(capabilities.get("vision", False))
    audio_available = bool(capabilities.get("audio", False))
    video_available = bool(capabilities.get("video", False))
    requested_images = _count(requested, "image_count")
    requested_audio = _count(requested, "audio_count")
    requested_video = _count(requested, "video_count")
    evaluated_images = _count(evaluated, "image_count")
    evaluated_audio = _count(evaluated, "audio_count")
    evaluated_video = _count(evaluated, "video_count")
    all_media_evaluated = bool(mtmd.get("all_media_evaluated", False))
    requested_media = requested_images + requested_audio + requested_video

    if requested_media == 0:
        status = "NO MEDIA"
    elif all_media_evaluated:
        status = "PASS"
    else:
        status = "UNAVAILABLE"

    def availability(value: bool) -> str:
        return "available" if value else "unavailable"

    return "\n".join(
        [
            f"MTMD MEDIA INGESTION: {status}",
            "",
            "Capabilities",
            f"  Vision: {availability(vision_available)}",
            f"  Audio:  {availability(audio_available)}",
            f"  Video:  {availability(video_available)}",
            "",
            "Evaluated",
            f"  Images: {evaluated_images}/{requested_images}",
            f"  Audio:  {evaluated_audio}/{requested_audio}",
            f"  Video:  {evaluated_video}/{requested_video}",
            "",
            f"Handler: {diagnostics.get('handler', 'unknown')}",
            f"Verification: {mtmd.get('verification', 'unavailable')}",
            "Model unloaded: "
            + ("yes" if diagnostics.get("model_unloaded_after_response") else "no"),
        ]
    )


class LlamaCppMediaDiagnosticsNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppMediaDiagnostics",
            display_name="Llama.cpp Media Diagnostics",
            category="Ollama/llama_cpp",
            description=(
                "Expands the fork-specific MTMD ingestion receipt into capability flags, "
                "evaluated media counts, JSON, and formatted text."
            ),
            inputs=[
                LlamaCppMediaDiagnosticsType.Input("media_diagnostics"),
            ],
            outputs=[
                io.Boolean.Output(
                    "all_media_evaluated",
                    display_name="All Media Evaluated",
                ),
                io.Boolean.Output(
                    "vision_available",
                    display_name="Vision Available",
                ),
                io.Boolean.Output(
                    "audio_available",
                    display_name="Audio Available",
                ),
                io.Boolean.Output(
                    "video_available",
                    display_name="Video Available",
                ),
                io.Int.Output("audio_count", display_name="AUDIO_COUNT"),
                io.Int.Output("image_count", display_name="IMAGE_COUNT"),
                io.Int.Output("video_count", display_name="VIDEO_COUNT"),
                io.String.Output("json", display_name="JSON"),
                io.String.Output("formatted_text", display_name="FormattedText"),
            ],
        )

    @classmethod
    def execute(cls, media_diagnostics) -> io.NodeOutput:
        diagnostics = _as_dict(media_diagnostics)
        capabilities = diagnostics.get("capabilities", {})
        evaluated = diagnostics.get("evaluated", {})
        mtmd = diagnostics.get("mtmd", {})
        return io.NodeOutput(
            bool(mtmd.get("all_media_evaluated", False)),
            bool(capabilities.get("vision", False)),
            bool(capabilities.get("audio", False)),
            bool(capabilities.get("video", False)),
            _count(evaluated, "audio_count"),
            _count(evaluated, "image_count"),
            _count(evaluated, "video_count"),
            json.dumps(diagnostics, ensure_ascii=False, indent=2),
            format_media_diagnostics(diagnostics),
        )


__all__ = [
    "LlamaCppMediaDiagnosticsNode",
    "LlamaCppMediaDiagnosticsType",
    "format_media_diagnostics",
]
