from __future__ import annotations

import json

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..backends.ollama import chat
from ..core import normalize_media, unwrap_optional_scalar, unwrap_required_scalar
from .common import collect_bundles, combine_bundles
from .media_bundle import MultimodalMediaType


class OllamaMultimodalGenerateNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaMultimodal_Generate",
            display_name="Ollama Multimodal Generate",
            category="multimodal/ollama",
            description=(
                "Sends one stateless /api/chat request containing all normalized images. "
                "Original image dimensions and list order are preserved."
            ),
            is_input_list=True,
            not_idempotent=True,
            inputs=[
                io.String.Input(
                    "url",
                    default="http://127.0.0.1:11434",
                    tooltip="Ollama base URL. Only HTTP and HTTPS are accepted.",
                ),
                io.String.Input("model", default="", tooltip="Exact Ollama model name."),
                io.String.Input(
                    "system",
                    default="",
                    multiline=True,
                    dynamic_prompts=False,
                    tooltip="System message sent without trimming or rewriting.",
                ),
                io.String.Input(
                    "prompt",
                    default="",
                    multiline=True,
                    dynamic_prompts=False,
                    tooltip="User message sent without trimming or rewriting.",
                ),
                io.String.Input(
                    "options_json",
                    default="{}",
                    multiline=True,
                    advanced=True,
                    tooltip="Ollama options object, for example temperature, seed, and num_ctx.",
                ),
                io.String.Input(
                    "format_json",
                    default="",
                    multiline=True,
                    advanced=True,
                    tooltip="Empty, the literal json, or a JSON Schema object.",
                ),
                io.Combo.Input(
                    "think",
                    options=["off", "on", "low", "medium", "high", "max"],
                    default="off",
                    advanced=True,
                ),
                io.String.Input("keep_alive", default="5m", advanced=True),
                io.Int.Input(
                    "timeout_seconds",
                    default=300,
                    min=1,
                    max=86_400,
                    step=1,
                    advanced=True,
                ),
                io.Combo.Input(
                    "audio_transport",
                    options=["disabled", "experimental_wav_in_images", "native"],
                    default="disabled",
                    advanced=True,
                    tooltip=(
                        "Ollama has no documented native audio field. Experimental mode places WAV bytes "
                        "in images and may fail depending on model/server."
                    ),
                ),
                io.Boolean.Input(
                    "debug",
                    default=False,
                    advanced=True,
                    tooltip="Include a payload-free request manifest in the manifest output.",
                ),
                MultimodalMediaType.Input(
                    "media",
                    optional=True,
                    tooltip="Optional pre-normalized Multimodal Media Bundle.",
                ),
                io.Image.Input(
                    "images",
                    optional=True,
                    tooltip="IMAGE single, batch, list, nested list, or ComfyUI data list.",
                ),
                io.Audio.Input(
                    "audio",
                    optional=True,
                    tooltip="AUDIO input; transport is disabled by default because Ollama lacks a native field.",
                ),
            ],
            outputs=[
                io.String.Output("response", display_name="response"),
                io.String.Output("thinking", display_name="thinking"),
                io.String.Output("raw_json", display_name="raw JSON"),
                io.String.Output("metrics_json", display_name="metrics"),
                io.String.Output("media_manifest_json", display_name="media manifest"),
            ],
        )

    @classmethod
    def execute(
        cls,
        url,
        model,
        system,
        prompt,
        options_json,
        format_json,
        think,
        keep_alive,
        timeout_seconds,
        audio_transport,
        debug,
        media=None,
        images=None,
        audio=None,
    ) -> io.NodeOutput:
        normalized = normalize_media(images=images, audio=audio)
        bundle = combine_bundles(collect_bundles(media), normalized)
        debug_enabled = bool(unwrap_optional_scalar("debug", debug, False))
        result = chat(
            url=str(unwrap_required_scalar("url", url)),
            model=str(unwrap_required_scalar("model", model)),
            system=str(unwrap_required_scalar("system", system)),
            prompt=str(unwrap_required_scalar("prompt", prompt)),
            media=bundle,
            options_json=str(unwrap_optional_scalar("options_json", options_json, "{}")),
            format_json=str(unwrap_optional_scalar("format_json", format_json, "")),
            think=str(unwrap_optional_scalar("think", think, "off")),
            keep_alive=str(unwrap_optional_scalar("keep_alive", keep_alive, "5m")),
            timeout_seconds=float(unwrap_optional_scalar("timeout_seconds", timeout_seconds, 300)),
            audio_transport=str(
                unwrap_optional_scalar("audio_transport", audio_transport, "disabled")
            ),
        )
        manifest = bundle.manifest()
        if debug_enabled:
            manifest = {**manifest, "request": result.request_manifest}
        return io.NodeOutput(
            result.response,
            result.thinking,
            json.dumps(result.raw, ensure_ascii=False, indent=2),
            json.dumps(result.metrics, ensure_ascii=False, indent=2),
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
