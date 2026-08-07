from __future__ import annotations

import math
from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..core import InputNormalizationError


LlamaCppSamplingType = io.Custom("OLLAMA_IMAGE_LIST_LLAMA_CPP_SAMPLING")

SAMPLING_PRESETS: dict[str, dict[str, float | int]] = {
    "Image analysis": {
        "temperature": 0.2,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.0,
    },
    "Gemma 4": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
    },
    "Gemma 4 Uncensored": {
        "temperature": 0.6,
        "top_p": 0.90,
        "top_k": 64,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
    },
    "llama.cpp default": {
        "temperature": 0.8,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.0,
    },
}

_FLOAT_RANGES = {
    "temperature": (0.0, 5.0),
    "top_p": (0.0, 1.0),
    "min_p": (0.0, 1.0),
    "repeat_penalty": (0.0, 5.0),
}


def normalize_sampling(value: Any) -> dict[str, float | int]:
    if not isinstance(value, dict):
        raise InputNormalizationError("sampling must be a llama.cpp sampling preset object.")

    normalized: dict[str, float | int] = {}
    for name, (minimum, maximum) in _FLOAT_RANGES.items():
        candidate = value.get(name)
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            raise InputNormalizationError(f"sampling.{name} must be a number.")
        candidate = float(candidate)
        if not math.isfinite(candidate) or not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"sampling.{name} must be between {minimum} and {maximum}."
            )
        normalized[name] = candidate

    top_k = value.get("top_k")
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise InputNormalizationError("sampling.top_k must be an integer.")
    if not 0 <= top_k <= 10_000:
        raise InputNormalizationError("sampling.top_k must be between 0 and 10000.")
    normalized["top_k"] = top_k
    return normalized


class LlamaCppSamplingPresetNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        preset_names = list(SAMPLING_PRESETS)
        return io.Schema(
            node_id="OllamaImageList_LlamaCppSamplingPreset",
            display_name="Llama.cpp Sampling Preset",
            category="Ollama/llama_cpp",
            description=(
                "Outputs a compact llama.cpp sampling preset for temperature, top-p, "
                "top-k, min-p, and repeat penalty."
            ),
            inputs=[
                io.Combo.Input(
                    "preset",
                    options=preset_names,
                    default="Image analysis",
                    tooltip=(
                        "Image analysis favors stable descriptions; Gemma 4 follows the "
                        "model generation configuration; llama.cpp default uses CLI defaults."
                    ),
                ),
            ],
            outputs=[
                LlamaCppSamplingType.Output("sampling", display_name="sampling"),
            ],
        )

    @classmethod
    def execute(cls, preset: str) -> io.NodeOutput:
        try:
            sampling = SAMPLING_PRESETS[preset]
        except KeyError as exc:
            raise InputNormalizationError(f"Unknown llama.cpp sampling preset: {preset}") from exc
        return io.NodeOutput(dict(sampling))


__all__ = [
    "LlamaCppSamplingPresetNode",
    "LlamaCppSamplingType",
    "SAMPLING_PRESETS",
    "normalize_sampling",
]
