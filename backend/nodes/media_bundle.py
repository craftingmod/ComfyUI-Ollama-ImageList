from __future__ import annotations

import json

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..core import normalize_media


MultimodalMediaType = io.Custom("MULTIMODAL_MEDIA")


class MultimodalOllamaMediaBundleNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MultimodalOllama_MediaBundle",
            display_name="Multimodal Ollama Media Bundle",
            category="Ollama/multimodal",
            description=(
                "Normalizes image batches/data lists and audio into an immutable media bundle "
                "without resizing or padding."
            ),
            is_input_list=True,
            inputs=[
                io.Image.Input(
                    "images",
                    optional=True,
                    tooltip="IMAGE single, batch, list, nested list, or ComfyUI data list.",
                ),
                io.Audio.Input(
                    "audio",
                    optional=True,
                    tooltip="AUDIO single, batch, list, nested list, or ComfyUI data list.",
                ),
            ],
            outputs=[
                MultimodalMediaType.Output("media", display_name="media"),
                io.String.Output("manifest_json", display_name="manifest"),
            ],
        )

    @classmethod
    def execute(cls, images=None, audio=None) -> io.NodeOutput:
        bundle = normalize_media(images=images, audio=audio)
        manifest = json.dumps(bundle.manifest(), ensure_ascii=False, indent=2)
        return io.NodeOutput(bundle, manifest)
