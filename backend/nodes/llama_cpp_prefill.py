from __future__ import annotations

from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI builds
    from comfy_api.latest import io

from ..core import InputNormalizationError

LlamaCppPrefillProfileType = io.Custom("OLLAMA_IMAGE_LIST_LLAMA_CPP_PREFILL_PROFILE")

_PREFILL_RANGES = {
    "n_batch": (0, 65_536),
    "n_ubatch": (0, 65_536),
    "image_min_tokens": (0, 65_536),
    "image_max_tokens": (0, 65_536),
}
PREFILL_PROFILES = {
    "Gemma4 Medium": {
        "n_batch": 1024,
        "n_ubatch": 768,
        "image_min_tokens": 280,
        "image_max_tokens": 560,
    },
    "Gemma4 High": {
        "n_batch": 1536,
        "n_ubatch": 1280,
        "image_min_tokens": 560,
        "image_max_tokens": 1120,
    },
    "Qwen3.8 Medium": {
        "n_batch": 2048,
        "n_ubatch": 1024,
        "image_min_tokens": 1024,
        "image_max_tokens": 2048,
    },
    "Qwen3.8 High": {
        "n_batch": 4096,
        "n_ubatch": 1024,
        "image_min_tokens": 1024,
        "image_max_tokens": 4096,
    },
}
PREFILL_PROFILE_OPTIONS = ["Custom", *PREFILL_PROFILES]


def normalize_prefill_profile(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "prefill_profile must be a [llama.cpp] Prefill Profile object."
        )
    missing = [name for name in _PREFILL_RANGES if name not in value]
    if missing:
        raise InputNormalizationError(
            f"prefill_profile is missing required field(s): {', '.join(missing)}."
        )
    normalized = {}
    for name, (minimum, maximum) in _PREFILL_RANGES.items():
        candidate = value[name]
        if type(candidate) is not int or not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"prefill_profile.{name} must be an integer between "
                f"{minimum} and {maximum}."
            )
        normalized[name] = candidate
    if normalized["n_ubatch"] > normalized["n_batch"]:
        raise InputNormalizationError(
            "prefill_profile.n_ubatch cannot exceed n_batch."
        )
    if (
        normalized["image_min_tokens"] > 0
        and normalized["image_max_tokens"] > 0
        and normalized["image_min_tokens"] > normalized["image_max_tokens"]
    ):
        raise InputNormalizationError(
            "prefill_profile.image_min_tokens cannot exceed image_max_tokens."
        )
    return normalized


class LlamaCppPrefillProfileNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppPrefillProfile",
            display_name="[llama.cpp] Prefill Profile",
            category="llama_cpp/profile",
            description=(
                "Sets batch and image-token limits shared by llama.cpp Generate and "
                "Create Session nodes. Context size remains on each consumer. Named "
                "profiles override the editable Custom values."
            ),
            inputs=[
                io.Combo.Input(
                    "profile", options=PREFILL_PROFILE_OPTIONS, default="Custom"
                ),
                io.Int.Input("n_batch", default=512, min=0, max=65_536, step=1),
                io.Int.Input(
                    "n_ubatch",
                    default=0,
                    min=0,
                    max=65_536,
                    step=1,
                    tooltip="0 uses llama.cpp's default physical batch size.",
                ),
                io.Int.Input(
                    "image_min_tokens", default=0, min=0, max=65_536, step=1
                ),
                io.Int.Input(
                    "image_max_tokens",
                    default=0,
                    min=0,
                    max=65_536,
                    step=1,
                    tooltip="0 uses the mmproj or handler default.",
                ),
            ],
            outputs=[
                LlamaCppPrefillProfileType.Output(
                    "prefill_profile", display_name="prefill profile"
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        profile: str,
        n_batch: int,
        n_ubatch: int,
        image_min_tokens: int,
        image_max_tokens: int,
    ) -> io.NodeOutput:
        if profile == "Custom":
            value = {
                "n_batch": n_batch,
                "n_ubatch": n_ubatch,
                "image_min_tokens": image_min_tokens,
                "image_max_tokens": image_max_tokens,
            }
        else:
            try:
                value = PREFILL_PROFILES[profile]
            except KeyError as exc:
                raise InputNormalizationError(
                    f"Unknown Llama.cpp Prefill Profile: {profile}"
                ) from exc
        return io.NodeOutput(
            normalize_prefill_profile(value)
        )


__all__ = [
    "LlamaCppPrefillProfileNode",
    "LlamaCppPrefillProfileType",
    "PREFILL_PROFILE_OPTIONS",
    "PREFILL_PROFILES",
    "normalize_prefill_profile",
]
