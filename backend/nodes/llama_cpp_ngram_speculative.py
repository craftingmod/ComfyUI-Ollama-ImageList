from __future__ import annotations

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..backends.llama_cpp import normalize_ngram_speculative


LlamaCppNGramSpeculativeType = io.Custom(
    "OLLAMA_IMAGE_LIST_LLAMA_CPP_NGRAM_SPECULATIVE"
)


class LlamaCppNGramSpeculativePresetNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppNGramSpeculativePreset",
            display_name="Llama.cpp N-gram Speculative Preset",
            category="Ollama/llama_cpp",
            description=(
                "Configures optional model-free n-gram speculative decoding for the normal "
                "Llama.cpp Generate node. It does not use a draft GGUF or the Experimental "
                "native DFlash/DSpark API."
            ),
            inputs=[
                io.Combo.Input(
                    "speculative_mode",
                    options=["off", "ngram"],
                    default="off",
                    tooltip=(
                        "off preserves normal generation. ngram predicts candidates from "
                        "repeated token patterns already in the current context."
                    ),
                ),
                io.Int.Input(
                    "ngram_size",
                    default=3,
                    min=1,
                    max=8,
                    step=1,
                    tooltip="Number of verified context tokens used as each lookup key.",
                ),
                io.Int.Input(
                    "num_pred_tokens",
                    default=10,
                    min=1,
                    max=32,
                    step=1,
                    tooltip="Maximum candidate tokens proposed per draft call.",
                ),
                io.Combo.Input(
                    "ngram_mode",
                    options=["k", "k4v"],
                    default="k",
                    tooltip=(
                        "k stores historical positions and uses less memory. k4v caches "
                        "continuations for cheaper lookup and should use a memory cap."
                    ),
                ),
                io.Int.Input(
                    "ngram_min_hits",
                    default=2,
                    min=1,
                    max=16,
                    step=1,
                    tooltip="Minimum historical matches required before proposing tokens.",
                ),
                io.Int.Input(
                    "ngram_max_entries_per_key",
                    default=8,
                    min=0,
                    max=1024,
                    step=1,
                    tooltip=(
                        "Maximum stored entries per key. 0 passes None for no explicit cap; "
                        "a cap is recommended for k4v."
                    ),
                ),
                io.Int.Input(
                    "ngram_sync_check_tokens",
                    default=16,
                    min=1,
                    max=256,
                    step=1,
                    tooltip=(
                        "Trailing tokens checked when synchronizing the incremental history "
                        "index."
                    ),
                ),
            ],
            outputs=[
                LlamaCppNGramSpeculativeType.Output(
                    "ngram_speculative",
                    display_name="ngram speculative",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        speculative_mode: str,
        ngram_size: int,
        num_pred_tokens: int,
        ngram_mode: str,
        ngram_min_hits: int,
        ngram_max_entries_per_key: int,
        ngram_sync_check_tokens: int,
    ) -> io.NodeOutput:
        return io.NodeOutput(
            normalize_ngram_speculative(
                {
                    "speculative_mode": speculative_mode,
                    "ngram_size": ngram_size,
                    "num_pred_tokens": num_pred_tokens,
                    "ngram_mode": ngram_mode,
                    "ngram_min_hits": ngram_min_hits,
                    "ngram_max_entries_per_key": ngram_max_entries_per_key,
                    "ngram_sync_check_tokens": ngram_sync_check_tokens,
                }
            )
        )


__all__ = [
    "LlamaCppNGramSpeculativePresetNode",
    "LlamaCppNGramSpeculativeType",
]
