from __future__ import annotations

import os

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..backends.llama_cpp import require_native_speculative
from .llama_cpp_generate import (
    NO_DRAFT_OPTION,
    NO_MODEL_OPTION,
    LlamaCppImageListGenerateNode,
    _gguf_options,
)


def _draft_gguf_options() -> list[str]:
    model_options, _ = _gguf_options()
    filenames = [name for name in model_options if name != NO_MODEL_OPTION]
    prioritized = sorted(
        filenames,
        key=lambda filename: (
            not any(
                hint in os.path.basename(filename).casefold()
                for hint in ("dflash", "dspark", "draft", "mtp")
            ),
        ),
    )
    if not prioritized:
        return [NO_MODEL_OPTION]
    return [NO_DRAFT_OPTION, *prioritized]


class LlamaCppSpeculativeGenerateNode(LlamaCppImageListGenerateNode):
    _supports_ngram_speculative = False

    @classmethod
    def _prepare_backend_execution(cls) -> dict[str, object]:
        return {"speculative_class": require_native_speculative()}

    @classmethod
    def define_schema(cls) -> io.Schema:
        base_schema = super().define_schema()
        draft_options = _draft_gguf_options()
        speculative_inputs = [
            io.Combo.Input(
                "draft_model",
                options=draft_options,
                default=draft_options[0],
                tooltip=(
                    "Experimental DFlash or DSpark draft GGUF from ComfyUI's registered "
                    "LLM paths. The draft must be compatible with the target model; an "
                    "incompatible pair may fail during initialization or generation."
                ),
            ),
            io.Combo.Input(
                "spec_type",
                options=["draft-dflash", "draft-dspark"],
                default="draft-dflash",
                tooltip="Native speculative draft implementation provided by the wheel.",
            ),
            io.Int.Input(
                "spec_n_max",
                default=8,
                min=1,
                max=64,
                step=1,
                advanced=True,
                tooltip="Maximum draft tokens proposed in one speculative cycle.",
            ),
            io.Int.Input(
                "spec_n_min",
                default=0,
                min=0,
                max=64,
                step=1,
                advanced=True,
                tooltip="Minimum draft tokens proposed in one speculative cycle.",
            ),
            io.Float.Input(
                "spec_p_min",
                default=0.0,
                min=0.0,
                max=1.0,
                step=0.01,
                advanced=True,
                tooltip="Draft confidence threshold.",
            ),
        ]
        inputs = [
            field
            for field in base_schema.inputs
            if field.id not in {"ngram_speculative", "reasoning_strength"}
        ]
        inputs[2:2] = speculative_inputs
        reasoning_strength_input = next(
            field for field in base_schema.inputs if field.id == "reasoning_strength"
        )
        thinking_index = next(
            index for index, field in enumerate(inputs) if field.id == "thinking"
        )
        inputs[thinking_index + 1 : thinking_index + 1] = [reasoning_strength_input]
        return io.Schema(
            node_id="OllamaImageList_LlamaCppSpeculativeGenerate",
            display_name="Llama.cpp Speculative Generate (Experimental)",
            category="Ollama/llama_cpp/experimental",
            description=(
                "Experimental native speculative decoding for compatible DFlash or DSpark "
                "draft GGUFs. Runs one text or initial multimodal request, reports draft "
                "acceptance statistics in metrics, then unloads target and draft resources. "
                "Additional VRAM is required and a speedup is not guaranteed."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=inputs,
            outputs=list(base_schema.outputs),
        )


__all__ = ["LlamaCppSpeculativeGenerateNode"]
