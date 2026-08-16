from __future__ import annotations

try:
    from comfy_api.v0_0_2 import ComfyExtension, io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import ComfyExtension, io

from .nodes import (
    ClipImageListGenerateNode,
    LlamaCppGemma4RuntimePresetNode,
    LlamaCppHardwareRuntimeProfileNode,
    LlamaCppImageListGenerateNode,
    LlamaCppMediaDiagnosticsNode,
    LlamaCppModelProfileNode,
    LlamaCppNativeSpeculativeConfigNode,
    LlamaCppNGramSpeculativeConfigNode,
    LlamaCppNGramSpeculativePresetNode,
    LlamaCppProfiledGenerateNode,
    LlamaCppReasoningConfigNode,
    LlamaCppSamplingPresetNode,
    LlamaCppSequentialGenerateNode,
    MiniMaxSystemPromptPresetNode,
    MuseGlimmerResponseParserNode,
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
            MiniMaxSystemPromptPresetNode,
            LlamaCppSamplingPresetNode,
            LlamaCppGemma4RuntimePresetNode,
            LlamaCppNGramSpeculativePresetNode,
            LlamaCppModelProfileNode,
            LlamaCppHardwareRuntimeProfileNode,
            LlamaCppReasoningConfigNode,
            LlamaCppNGramSpeculativeConfigNode,
            LlamaCppNativeSpeculativeConfigNode,
            LlamaCppProfiledGenerateNode,
            LlamaCppSequentialGenerateNode,
            LlamaCppImageListGenerateNode,
            LlamaCppMediaDiagnosticsNode,
            MuseGlimmerResponseParserNode,
            ClipImageListGenerateNode,
        ]


async def comfy_entrypoint() -> OllamaImageListExtension:
    register_routes()
    return OllamaImageListExtension()
