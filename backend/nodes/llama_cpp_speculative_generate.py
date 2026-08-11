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
                    "Experimental DFlash/DSpark draft or Gemma 4 MTP assistant GGUF from "
                    "ComfyUI's registered LLM paths. Qwen 3.5 internal MTP must leave this "
                    "unselected. Compatibility is validated by the native runtime."
                ),
            ),
            io.Combo.Input(
                "spec_type",
                options=["none", "draft-dflash", "draft-dspark", "draft-mtp"],
                default="none",
                tooltip=(
                    "Native speculative implementation. Select draft-mtp together with "
                    "external_gemma4 or internal_qwen35 in mtp_provider."
                ),
            ),
            io.Int.Input(
                "spec_n_max",
                default=2,
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
        mtp_inputs = [
            io.Combo.Input(
                "mtp_provider",
                options=["off", "external_gemma4", "internal_qwen35"],
                default="off",
                tooltip=(
                    "Native MTP provider. external_gemma4 uses the selected draft_model "
                    "as a matching gemma4-assistant GGUF. internal_qwen35 uses embedded "
                    "NextN/MTP layers and requires draft_model to remain unselected."
                ),
            ),
        ]
        inputs = [
            field
            for field in base_schema.inputs
            if field.id
            not in {"ngram_speculative", "reasoning_strength", "reasoning_budget"}
        ]
        inputs[2:2] = [*speculative_inputs, *mtp_inputs]
        reasoning_inputs = [
            field
            for field in base_schema.inputs
            if field.id in {"reasoning_strength", "reasoning_budget"}
        ]
        thinking_index = next(
            index for index, field in enumerate(inputs) if field.id == "thinking"
        )
        inputs[thinking_index + 1 : thinking_index + 1] = reasoning_inputs
        return io.Schema(
            node_id="OllamaImageList_LlamaCppSpeculativeGenerate",
            display_name="Llama.cpp Speculative Generate (Experimental)",
            category="Ollama/llama_cpp/experimental",
            description=(
                "Experimental native speculative decoding for DFlash/DSpark drafts, Gemma 4 "
                "external MTP assistants, and Qwen 3.5 embedded MTP. MTP is text-only and "
                "requires all-layer GPU offload. Reports request-local draft acceptance "
                "statistics, then unloads all native resources."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=inputs,
            outputs=list(base_schema.outputs),
        )


__all__ = ["LlamaCppSpeculativeGenerateNode"]
