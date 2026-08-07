from __future__ import annotations

try:
    from comfy_api.v0_0_2 import ComfyExtension, io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import ComfyExtension, io

from .nodes import (
    LlamaCppImageListGenerateNode,
    LlamaCppGemma4RuntimePresetNode,
    LlamaCppMediaDiagnosticsNode,
    LlamaCppSamplingPresetNode,
    OllamaImageListConnectivityNode,
    OllamaImageListGenerateNode,
    OllamaImageListOptionsNode,
)
from .routes import register_routes


class OllamaImageListExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            OllamaImageListConnectivityNode,
            OllamaImageListOptionsNode,
            OllamaImageListGenerateNode,
            LlamaCppSamplingPresetNode,
            LlamaCppGemma4RuntimePresetNode,
            LlamaCppImageListGenerateNode,
            LlamaCppMediaDiagnosticsNode,
        ]


async def comfy_entrypoint() -> OllamaImageListExtension:
    register_routes()
    return OllamaImageListExtension()
