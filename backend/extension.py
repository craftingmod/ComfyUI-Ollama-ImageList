from __future__ import annotations

try:
    from comfy_api.v0_0_2 import ComfyExtension, io
except (
    ImportError
):  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import ComfyExtension, io
from comfy_api.latest import Caching, ComfyAPI

from .llama_cpp_session_cleanup import close_tracked_sessions
from .llama_cpp_runtime import (
    initialize_llama_cpp_runtime,
    register_runtime_routes,
)
from .nodes import (
    ClipImageListGenerateNode,
    JinjaChatTemplatePresetNode,
    LlamaCppCreateQuestionFromInputNode,
    LlamaCppCreateQuestionNode,
    LlamaCppDecideSessionNode,
    LlamaCppCreateRuntimeSessionNode,
    LlamaCppCreateSessionNode,
    LlamaCppConnectSessionNode,
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
    LlamaCppSessionGenerateNode,
    LlamaCppSessionSequentialGenerateNode,
    LlamaCppUnloadSessionNode,
    MiniMaxSystemPromptPresetNode,
    MuseGlimmerResponseParserNode,
    OllamaImageListConnectivityNode,
    OllamaImageListGenerateNode,
    OllamaImageListOptionsNode,
)
from .routes import register_routes


class LlamaCppSessionCleanupProvider(Caching.CacheProvider):
    async def on_lookup(self, _context):
        return None

    async def on_store(self, _context, _value) -> None:
        return None

    def should_cache(self, _context, _value=None) -> bool:
        return False

    def on_prompt_end(self, _prompt_id: str) -> None:
        close_tracked_sessions()


class OllamaImageListExtension(ComfyExtension):
    async def on_load(self) -> None:
        await ComfyAPI().caching.register_provider(LlamaCppSessionCleanupProvider())

    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            OllamaImageListConnectivityNode,
            OllamaImageListOptionsNode,
            OllamaImageListGenerateNode,
            MiniMaxSystemPromptPresetNode,
            JinjaChatTemplatePresetNode,
            LlamaCppSamplingPresetNode,
            LlamaCppGemma4RuntimePresetNode,
            LlamaCppNGramSpeculativePresetNode,
            LlamaCppModelProfileNode,
            LlamaCppHardwareRuntimeProfileNode,
            LlamaCppReasoningConfigNode,
            LlamaCppNGramSpeculativeConfigNode,
            LlamaCppNativeSpeculativeConfigNode,
            LlamaCppCreateSessionNode,
            LlamaCppCreateRuntimeSessionNode,
            LlamaCppConnectSessionNode,
            LlamaCppCreateQuestionNode,
            LlamaCppCreateQuestionFromInputNode,
            LlamaCppDecideSessionNode,
            LlamaCppSessionGenerateNode,
            LlamaCppUnloadSessionNode,
            LlamaCppProfiledGenerateNode,
            LlamaCppSequentialGenerateNode,
            LlamaCppSessionSequentialGenerateNode,
            LlamaCppImageListGenerateNode,
            LlamaCppMediaDiagnosticsNode,
            MuseGlimmerResponseParserNode,
            ClipImageListGenerateNode,
        ]


async def comfy_entrypoint() -> OllamaImageListExtension:
    register_routes()
    register_runtime_routes()
    initialize_llama_cpp_runtime()
    return OllamaImageListExtension()
