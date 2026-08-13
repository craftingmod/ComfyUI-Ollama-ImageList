from __future__ import annotations

import json

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI builds
    from comfy_api.latest import io

from ..core.reference_contract import (
    ReferenceContractError,
    execution_fingerprint,
    parse_reference_state,
)
from ..core.reference_manifest import (
    build_reference_manifest,
    build_reference_output_plan,
)
from ..core.reference_media import load_reference_media, validate_reference_sources


EMPTY_DIRECTOR_STATE_JSON = json.dumps(
    {
        "version": 1,
        "items": {},
        "visualOrder": [],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
        "ui": {
            "cardAspectRatio": "4 / 3",
            "previewMaxPixels": 1_000_000,
            "waveformPeaks": 300,
            "activeChannel": "visual",
        },
    },
    separators=(",", ":"),
)


class ReferenceDirectorNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_ReferenceDirector",
            display_name="Reference Director",
            category="Ollama/Multimodal",
            description=(
                "Orders image, audio, and video references without batching or resizing, "
                "and emits aligned raw caption lists plus a payload-free manifest."
            ),
            search_aliases=["reference", "media director", "multi image selector"],
            inputs=[
                io.String.Input(
                    "director_state",
                    display_name="director state",
                    default=EMPTY_DIRECTOR_STATE_JSON,
                    multiline=True,
                    dynamic_prompts=False,
                    socketless=True,
                    extra_dict={"widgetType": "OLLAMA_REFERENCE_DIRECTOR"},
                )
            ],
            outputs=[
                io.Image.Output("images", is_output_list=True),
                io.String.Output("image_captions", is_output_list=True),
                io.Audio.Output("audios", is_output_list=True),
                io.String.Output("audio_captions", is_output_list=True),
                io.Video.Output("videos", is_output_list=True),
                io.String.Output("video_captions", is_output_list=True),
                io.String.Output("manifest_json"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, director_state: str) -> str:
        state = parse_reference_state(director_state)
        validate_reference_sources(state)
        return execution_fingerprint(state)

    @classmethod
    def execute(cls, director_state: str) -> io.NodeOutput:
        state = parse_reference_state(director_state)
        plan = build_reference_output_plan(state)
        loaded = load_reference_media(state)
        if len(loaded.images) != len(plan.image_ids):
            raise ReferenceContractError(
                "Loaded IMAGE count does not match the active image output contract."
            )
        if len(loaded.audios) != len(plan.audio_ids):
            raise ReferenceContractError(
                "Loaded AUDIO count does not match the active audio output contract."
            )
        if len(loaded.videos) != len(plan.video_ids):
            raise ReferenceContractError(
                "Loaded VIDEO count does not match the active video output contract."
            )
        manifest_json = json.dumps(
            build_reference_manifest(state),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return io.NodeOutput(
            list(loaded.images),
            list(plan.image_captions),
            list(loaded.audios),
            list(plan.audio_captions),
            list(loaded.videos),
            list(plan.video_captions),
            manifest_json,
        )


__all__ = ["EMPTY_DIRECTOR_STATE_JSON", "ReferenceDirectorNode"]
