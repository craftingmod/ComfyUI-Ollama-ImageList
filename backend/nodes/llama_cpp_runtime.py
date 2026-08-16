from __future__ import annotations

from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..core import InputNormalizationError

LlamaCppGemma4RuntimeType = io.Custom(
    "OLLAMA_IMAGE_LIST_LLAMA_CPP_GEMMA4_RUNTIME"
)

GEMMA4_RUNTIME_PRESETS: dict[str, dict[str, bool | int]] = {
    "Text / Audio": {
        "n_ctx": 16_384,
        "max_tokens": 2_048,
        "n_batch": 512,
        "override_n_ubatch": False,
        "n_ubatch": 512,
        "override_image_max_tokens": False,
        "image_max_tokens": 512,
    },
    "Vision Standard": {
        "n_ctx": 16_384,
        "max_tokens": 1_024,
        "n_batch": 512,
        "override_n_ubatch": True,
        "n_ubatch": 512,
        "override_image_max_tokens": True,
        "image_max_tokens": 512,
    },
    "Vision Long / Thinking": {
        "n_ctx": 32_768,
        "max_tokens": 4_096,
        "n_batch": 512,
        "override_n_ubatch": True,
        "n_ubatch": 512,
        "override_image_max_tokens": True,
        "image_max_tokens": 512,
    },
    "Multi-image / Video": {
        "n_ctx": 32_768,
        "max_tokens": 2_048,
        "n_batch": 512,
        "override_n_ubatch": True,
        "n_ubatch": 512,
        "override_image_max_tokens": True,
        "image_max_tokens": 512,
    },
    "High Detail / OCR (Experimental)": {
        "n_ctx": 32_768,
        "max_tokens": 2_048,
        "n_batch": 1_120,
        "override_n_ubatch": True,
        "n_ubatch": 1_120,
        "override_image_max_tokens": True,
        "image_max_tokens": 1_120,
    },
}

_INTEGER_RANGES = {
    "n_batch": (1, 65_536),
    "n_ubatch": (1, 65_536),
    "image_max_tokens": (1, 65_536),
}
_BOOLEAN_NAMES = ("override_n_ubatch", "override_image_max_tokens")


def normalize_gemma4_runtime(value: Any) -> dict[str, bool | int]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "runtime must be a Llama.cpp Gemma 4 runtime preset object."
        )

    normalized: dict[str, bool | int] = {}
    for name, (minimum, maximum) in _INTEGER_RANGES.items():
        candidate = value.get(name)
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise InputNormalizationError(f"runtime.{name} must be an integer.")
        if not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"runtime.{name} must be between {minimum} and {maximum}."
            )
        normalized[name] = candidate

    for name in _BOOLEAN_NAMES:
        candidate = value.get(name)
        if not isinstance(candidate, bool):
            raise InputNormalizationError(f"runtime.{name} must be a boolean.")
        normalized[name] = candidate

    n_batch = int(normalized["n_batch"])
    n_ubatch = int(normalized["n_ubatch"])
    image_max_tokens = int(normalized["image_max_tokens"])
    if normalized["override_n_ubatch"] and n_ubatch > n_batch:
        raise InputNormalizationError(
            "runtime.n_ubatch cannot exceed runtime.n_batch."
        )
    if normalized["override_image_max_tokens"]:
        if image_max_tokens > n_batch:
            raise InputNormalizationError(
                "runtime.image_max_tokens cannot exceed runtime.n_batch."
            )
        effective_n_ubatch = n_ubatch if normalized["override_n_ubatch"] else 512
        if image_max_tokens > effective_n_ubatch:
            raise InputNormalizationError(
                "runtime.image_max_tokens cannot exceed the effective runtime.n_ubatch."
            )
    return normalized


class LlamaCppGemma4RuntimePresetNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        preset_names = list(GEMMA4_RUNTIME_PRESETS)
        return io.Schema(
            node_id="OllamaImageList_LlamaCppGemma4RuntimePreset",
            display_name="Llama.cpp Gemma 4 Runtime Preset",
            category="Ollama/llama_cpp/legacy",
            is_dev_only=True,
            description=(
                "Outputs one typed multimodal batch configuration plus separate "
                "Gemma 4-tuned context and generation-length integers."
            ),
            inputs=[
                io.Combo.Input(
                    "preset",
                    options=preset_names,
                    default="Vision Standard",
                    tooltip=(
                        "Vision Standard is the safe starting point. Long / Thinking reserves "
                        "more output context without enabling thinking. High Detail / OCR uses "
                        "1120 image tokens and may require more VRAM or backend-specific tuning."
                    ),
                ),
            ],
            outputs=[
                LlamaCppGemma4RuntimeType.Output("runtime", display_name="runtime"),
                io.Int.Output("n_ctx", display_name="n_ctx"),
                io.Int.Output("max_tokens", display_name="max_tokens"),
            ],
        )

    @classmethod
    def execute(cls, preset: str) -> io.NodeOutput:
        try:
            runtime = GEMMA4_RUNTIME_PRESETS[preset]
        except KeyError as exc:
            raise InputNormalizationError(
                f"Unknown Llama.cpp Gemma 4 runtime preset: {preset}"
            ) from exc
        advanced_runtime = {
            name: value
            for name, value in runtime.items()
            if name not in {"n_ctx", "max_tokens"}
        }
        return io.NodeOutput(
            advanced_runtime,
            int(runtime["n_ctx"]),
            int(runtime["max_tokens"]),
        )


__all__ = [
    "GEMMA4_RUNTIME_PRESETS",
    "LlamaCppGemma4RuntimePresetNode",
    "LlamaCppGemma4RuntimeType",
    "normalize_gemma4_runtime",
]
