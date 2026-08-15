from __future__ import annotations

import json

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI builds
    from comfy_api.latest import io

from ..core.reference_contract import (
    ReferenceContractError,
    execution_fingerprint,
    image_output_settings,
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
        "imageOrder": [],
        "videoOrder": [],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
        "ui": {
            "cardAspectRatio": "4 / 3",
            "gridColumns": 3,
            "previewMaxPixels": 1_000_000,
            "previewFit": "contain",
            "waveformPeaks": 300,
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
                "Orders image, audio, and video references without batching, with optional "
                "downscale-only IMAGE output limiting, "
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
                ),
                io.Boolean.Input(
                    "limit_image_pixels",
                    display_name="limit_image_pixels",
                    default=False,
                    label_on="Limited",
                    label_off="Original",
                    advanced=True,
                    socketless=False,
                    tooltip="Downscale IMAGE outputs above max_image_pixels; source and edit files remain unchanged.",
                ),
                io.Float.Input(
                    "max_image_pixels",
                    display_name="max_image_pixels (MPixel)",
                    default=2.0,
                    min=0.25,
                    max=40.0,
                    step=0.1,
                    round=0.01,
                    advanced=True,
                    socketless=False,
                    tooltip="Maximum IMAGE output resolution in megapixels when limiting is enabled; smaller images are not enlarged.",
                ),
                io.Boolean.Input(
                    "composite_alpha",
                    display_name="composite_alpha",
                    default=False,
                    label_on="Opaque",
                    label_off="Preserve",
                    advanced=True,
                    socketless=False,
                    tooltip="Composite alpha-bearing IMAGE outputs onto alpha_background and emit RGB.",
                ),
                io.Color.Input(
                    "alpha_background",
                    display_name="alpha_background",
                    default="#000000",
                    advanced=True,
                    socketless=False,
                    tooltip="Fallback color used only when composite_alpha is Opaque.",
                ),
                io.Int.Input(
                    "grid_columns",
                    display_name="grid_columns",
                    default=3,
                    min=1,
                    max=8,
                    step=1,
                    advanced=True,
                    socketless=True,
                    tooltip="Number of card columns used by each Director channel.",
                ),
                io.Float.Input(
                    "preview_pixels",
                    display_name="preview_pixels (MPixel)",
                    default=1.0,
                    min=0.25,
                    max=16.0,
                    step=0.25,
                    round=0.01,
                    advanced=True,
                    socketless=True,
                    tooltip="Maximum preview resolution in megapixels; execution media is unchanged.",
                ),
                io.Boolean.Input(
                    "show_captions",
                    display_name="show_captions",
                    default=True,
                    label_on="Shown",
                    label_off="Hidden",
                    advanced=True,
                    socketless=True,
                    tooltip="Show caption fields on Director cards; captions remain available in Edit when hidden.",
                ),
                io.Combo.Input(
                    "card_aspect",
                    display_name="card_aspect",
                    options=["1 / 1", "4 / 3", "3 / 4", "16 / 9", "9 / 16"],
                    default="4 / 3",
                    advanced=True,
                    socketless=True,
                    tooltip="Aspect ratio used by image and video cards in the Director grid.",
                ),
                io.Combo.Input(
                    "preview_fit",
                    display_name="preview_fit",
                    options=["contain", "cover"],
                    default="contain",
                    advanced=True,
                    socketless=True,
                    tooltip="Fit mode used by image and video previews; execution media is unchanged.",
                ),
                io.Int.Input(
                    "waveform_pairs",
                    display_name="waveform_pairs",
                    default=300,
                    min=100,
                    max=1000,
                    step=50,
                    advanced=True,
                    socketless=True,
                    tooltip="Number of min/max amplitude pairs requested for audio waveforms.",
                ),
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
    def fingerprint_inputs(
        cls,
        director_state: str,
        limit_image_pixels: bool = False,
        max_image_pixels: float = 2.0,
        composite_alpha: bool = False,
        alpha_background: str = "#000000",
        grid_columns: int = 3,
        preview_pixels: float = 1.0,
        show_captions: bool = True,
        card_aspect: str = "4 / 3",
        preview_fit: str = "contain",
        waveform_pairs: int = 300,
    ) -> str:
        _ = (
            grid_columns,
            preview_pixels,
            show_captions,
            card_aspect,
            preview_fit,
            waveform_pairs,
        )
        state = parse_reference_state(director_state)
        validate_reference_sources(state)
        output_settings = image_output_settings(
            limit_image_pixels,
            max_image_pixels,
            composite_alpha,
            alpha_background,
        )
        return execution_fingerprint(state, image_output=output_settings)

    @classmethod
    def execute(
        cls,
        director_state: str,
        limit_image_pixels: bool = False,
        max_image_pixels: float = 2.0,
        composite_alpha: bool = False,
        alpha_background: str = "#000000",
        grid_columns: int = 3,
        preview_pixels: float = 1.0,
        show_captions: bool = True,
        card_aspect: str = "4 / 3",
        preview_fit: str = "contain",
        waveform_pairs: int = 300,
    ) -> io.NodeOutput:
        _ = (
            grid_columns,
            preview_pixels,
            show_captions,
            card_aspect,
            preview_fit,
            waveform_pairs,
        )
        state = parse_reference_state(director_state)
        output_settings = image_output_settings(
            limit_image_pixels,
            max_image_pixels,
            composite_alpha,
            alpha_background,
        )
        plan = build_reference_output_plan(state)
        loaded = load_reference_media(state, image_output=output_settings)
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
            build_reference_manifest(state, image_output=output_settings),
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
