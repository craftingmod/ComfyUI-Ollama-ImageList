from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:
    from comfy_api.v0_0_2 import io
except (
    ImportError
):  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..backends.llama_cpp import (
    HANDLER_NAMES,
    REASONING_STRENGTHS,
    require_native_speculative,
    run_chat,
    run_chat_sequential,
)
from ..core import (
    InputNormalizationError,
    MediaBundle,
    normalize_audio,
    normalize_images,
    normalize_media,
    unwrap_optional_scalar,
    unwrap_required_scalar,
)
from .llama_cpp_diagnostics import LlamaCppMediaDiagnosticsType
from .llama_cpp_generate import (
    NO_DRAFT_OPTION,
    NO_MMPROJ_OPTION,
    _gguf_options,
    _resolve_gguf_selection,
)
from .llama_cpp_ngram_speculative import normalize_ngram_speculative
from .llama_cpp_speculative_generate import _draft_gguf_options

LlamaCppModelProfileType = io.Custom("OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE")
LlamaCppHardwareRuntimeProfileType = io.Custom(
    "OLLAMA_IMAGE_LIST_LLAMA_CPP_HARDWARE_RUNTIME_PROFILE"
)
LlamaCppReasoningConfigType = io.Custom("OLLAMA_IMAGE_LIST_LLAMA_CPP_REASONING_CONFIG")
LlamaCppSpeculativeConfigType = io.Custom(
    "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
)
LlamaCppSequentialResponseType = io.Custom("LLAMA_SEQUENTIAL_RESPONSE")

BASE_CATEGORY = "llama_cpp"
PROFILE_CATEGORY = f"{BASE_CATEGORY}/profile"
COMPACT_CATEGORY = f"{BASE_CATEGORY}/compact"
MODEL_PRESETS_DIRECTORY = Path(__file__).resolve().parents[2] / "presets" / "model"

_BASE_MODEL_PROFILE: dict[str, Any] = {
    "handler": "auto",
    "recommended_reasoning_mode": "auto",
    "temperature": 0.2,
    "top_p": 0.95,
    "top_k": 40,
    "min_p": 0.05,
    "presence_penalty": 0.0,
    "repeat_penalty": 1.0,
    "custom_chat_template": "",
}

_BASE_HARDWARE_PROFILE: dict[str, Any] = {
    "n_batch": 512,
    "n_ubatch": 0,
    "gpu_layers": "all",
    "main_gpu": 0,
    "n_threads": 0,
    "flash_attention": "auto",
    "use_mmap": True,
}


def _load_model_profiles() -> dict[str, dict[str, Any]]:
    profiles = {}
    if not MODEL_PRESETS_DIRECTORY.is_dir():
        return profiles
    for path in sorted(MODEL_PRESETS_DIRECTORY.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read model profile preset: {path}") from exc
        if not isinstance(profile, dict):
            raise ValueError(f"Model profile preset must contain a JSON object: {path}")
        name = profile.pop("name", path.stem)
        if not isinstance(name, str) or not name.strip() or name in profiles:
            raise ValueError(f"Model profile preset has an invalid or duplicate name: {path}")
        profiles[name] = {**_BASE_MODEL_PROFILE, **profile}
    return profiles


COMPACT_MODEL_PROFILES = _load_model_profiles()

COMPACT_HARDWARE_PROFILES: dict[str, dict[str, Any]] = {
    "GPU Full Offload": dict(_BASE_HARDWARE_PROFILE),
    "GPU Vision 512": {
        **_BASE_HARDWARE_PROFILE,
        "n_ubatch": 512,
    },
    "Qwen Vision 1024": {
        **_BASE_HARDWARE_PROFILE,
        "n_batch": 1024,
        "n_ubatch": 1024,
    },
    "Automatic Offload": {
        **_BASE_HARDWARE_PROFILE,
        "gpu_layers": "auto",
    },
    "CPU": {
        **_BASE_HARDWARE_PROFILE,
        "gpu_layers": "cpu",
    },
}

NATIVE_DRAFT_PRESETS: dict[str, dict[str, Any]] = {
    "Off": {
        "spec_type": "none",
        "mtp_provider": "off",
    },
    "External MTP": {
        "spec_type": "draft-mtp",
        "mtp_provider": "external",
    },
    "Internal MTP": {
        "spec_type": "draft-mtp",
        "mtp_provider": "internal",
    },
    "DFlash": {
        "spec_type": "draft-dflash",
        "mtp_provider": "off",
    },
    "DSpark": {
        "spec_type": "draft-dspark",
        "mtp_provider": "off",
    },
}


def normalize_compact_model_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "model_profile must be a [llama.cpp] Model Profile object."
        )

    missing = [
        name
        for name in _BASE_MODEL_PROFILE
        if name != "custom_chat_template" and name not in value
    ]
    if missing:
        raise InputNormalizationError(
            f"model_profile is missing required field(s): {', '.join(missing)}."
        )
    normalized = {
        name: value.get(name, _BASE_MODEL_PROFILE[name]) for name in _BASE_MODEL_PROFILE
    }
    handler = normalized.get("handler")
    if handler not in HANDLER_NAMES:
        raise InputNormalizationError(
            f"model_profile.handler must be one of {', '.join(HANDLER_NAMES)}."
        )
    recommended_reasoning_mode = normalized.get("recommended_reasoning_mode")
    if recommended_reasoning_mode not in {"auto", "off", "on"}:
        raise InputNormalizationError(
            "model_profile.recommended_reasoning_mode must be auto, off, or on."
        )

    custom_chat_template = normalized.get("custom_chat_template", "")
    if not isinstance(custom_chat_template, str):
        raise InputNormalizationError(
            "model_profile.custom_chat_template must be a string."
        )
    normalized["custom_chat_template"] = custom_chat_template

    integer_ranges = {
        "top_k": (0, 10_000),
    }
    for name, (minimum, maximum) in integer_ranges.items():
        candidate = normalized.get(name)
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise InputNormalizationError(f"model_profile.{name} must be an integer.")
        if not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"model_profile.{name} must be between {minimum} and {maximum}."
            )

    float_ranges = {
        "temperature": (0.0, 5.0),
        "top_p": (0.0, 1.0),
        "min_p": (0.0, 1.0),
        "presence_penalty": (-2.0, 2.0),
        "repeat_penalty": (0.0, 5.0),
    }
    for name, (minimum, maximum) in float_ranges.items():
        candidate = normalized.get(name)
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            raise InputNormalizationError(f"model_profile.{name} must be a number.")
        candidate = float(candidate)
        if not math.isfinite(candidate) or not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"model_profile.{name} must be between {minimum} and {maximum}."
            )
        normalized[name] = candidate

    return normalized


def normalize_compact_hardware_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "hardware_profile must be a Llama.cpp Compact Hardware Profile object."
        )
    missing = [name for name in _BASE_HARDWARE_PROFILE if name not in value]
    if missing:
        raise InputNormalizationError(
            f"hardware_profile is missing required field(s): {', '.join(missing)}."
        )
    normalized = {name: value[name] for name in _BASE_HARDWARE_PROFILE}
    integer_ranges = {
        "n_batch": (1, 65_536),
        "n_ubatch": (0, 65_536),
        "main_gpu": (0, 31),
        "n_threads": (0, 1_024),
    }
    for name, (minimum, maximum) in integer_ranges.items():
        candidate = normalized.get(name)
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise InputNormalizationError(
                f"hardware_profile.{name} must be an integer."
            )
        if not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"hardware_profile.{name} must be between {minimum} and {maximum}."
            )
    if normalized["n_ubatch"] > normalized["n_batch"]:
        raise InputNormalizationError(
            "hardware_profile.n_ubatch cannot exceed hardware_profile.n_batch."
        )
    if normalized["gpu_layers"] not in {"all", "auto", "cpu"}:
        raise InputNormalizationError(
            "hardware_profile.gpu_layers must be all, auto, or cpu."
        )
    if normalized["flash_attention"] not in {"auto", "enabled", "disabled"}:
        raise InputNormalizationError(
            "hardware_profile.flash_attention must be auto, enabled, or disabled."
        )
    if not isinstance(normalized["use_mmap"], bool):
        raise InputNormalizationError("hardware_profile.use_mmap must be a boolean.")
    return normalized


def normalize_reasoning_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "reasoning must be a [llama.cpp] Thinking / Reasoning Profile object."
        )
    mode = value.get("reasoning_mode")
    if mode not in {"auto", "off", "on"}:
        raise InputNormalizationError("reasoning_mode must be auto, off, or on.")
    effort = value.get("reasoning_effort")
    if effort not in REASONING_STRENGTHS:
        raise InputNormalizationError(
            f"reasoning_effort must be one of {', '.join(REASONING_STRENGTHS)}."
        )
    maximum = value.get("max_reasoning_tokens")
    if isinstance(maximum, bool) or not isinstance(maximum, int):
        raise InputNormalizationError("max_reasoning_tokens must be an integer.")
    if not 0 <= maximum <= 65_536:
        raise InputNormalizationError(
            "max_reasoning_tokens must be between 0 and 65536."
        )
    preserve_thinking = value.get("preserve_thinking")
    if not isinstance(preserve_thinking, bool):
        raise InputNormalizationError("preserve_thinking must be a boolean.")
    if mode != "on":
        effort = "auto"
        maximum = 0
    return {
        "reasoning_mode": mode,
        "reasoning_effort": effort,
        "max_reasoning_tokens": maximum,
        "preserve_thinking": preserve_thinking,
    }


def normalize_native_draft_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "native_speculative must be a [llama.cpp] "
            "Native Speculative Profile object."
        )
    spec_type = value.get("spec_type")
    if spec_type not in {
        "none",
        "draft-dflash",
        "draft-dspark",
        "draft-mtp",
    }:
        raise InputNormalizationError(
            "native_speculative.spec_type must be none, draft-dflash, draft-dspark, "
            "or draft-mtp."
        )
    provider = value.get("mtp_provider")
    if provider not in {"off", "external", "internal"}:
        raise InputNormalizationError(
            "native_speculative.mtp_provider must be off, external, or internal."
        )
    n_max = value.get("draft_n_max")
    p_min = value.get("draft_p_min")
    if isinstance(n_max, bool) or not isinstance(n_max, int) or not 1 <= n_max <= 64:
        raise InputNormalizationError(
            "native_speculative.draft_n_max must be an integer between 1 and 64."
        )
    if isinstance(p_min, bool) or not isinstance(p_min, (int, float)):
        raise InputNormalizationError(
            "native_speculative.draft_p_min must be a number."
        )
    p_min = float(p_min)
    if not math.isfinite(p_min) or not 0.0 <= p_min <= 1.0:
        raise InputNormalizationError(
            "native_speculative.draft_p_min must be between 0.0 and 1.0."
        )
    draft_n_gpu_layers = value.get("draft_n_gpu_layers")
    if (
        isinstance(draft_n_gpu_layers, bool)
        or not (
            (
                isinstance(draft_n_gpu_layers, str)
                and draft_n_gpu_layers in {"all", "auto"}
            )
            or isinstance(draft_n_gpu_layers, int)
        )
        or (isinstance(draft_n_gpu_layers, int) and draft_n_gpu_layers < -2)
    ):
        raise InputNormalizationError(
            "native_speculative.draft_n_gpu_layers must be all, auto, or an integer >= -2."
        )
    draft_backend_sampling = value.get("draft_backend_sampling")
    if not isinstance(draft_backend_sampling, bool):
        raise InputNormalizationError(
            "native_speculative.draft_backend_sampling must be a boolean."
        )
    draft_model = value.get("draft_model", NO_DRAFT_OPTION)
    if not isinstance(draft_model, str):
        raise InputNormalizationError(
            "native_speculative.draft_model must be a string."
        )
    if spec_type == "none":
        provider = "off"
        draft_model = NO_DRAFT_OPTION
    elif spec_type == "draft-mtp":
        if provider == "off":
            raise InputNormalizationError(
                "native_speculative draft-mtp requires an external or internal MTP provider."
            )
        if provider == "internal":
            draft_model = NO_DRAFT_OPTION
    elif provider != "off":
        raise InputNormalizationError(
            "native_speculative.mtp_provider must be off for DFlash and DSpark."
        )
    return {
        "spec_type": spec_type,
        "mtp_provider": provider,
        "draft_model": draft_model,
        "draft_n_max": n_max,
        "draft_p_min": p_min,
        "draft_n_gpu_layers": draft_n_gpu_layers,
        "draft_backend_sampling": draft_backend_sampling,
    }


def normalize_compact_speculative(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "speculative must be a Compact N-gram or [llama.cpp] "
            "Native Speculative Profile object."
        )
    kind = value.get("kind")
    if kind == "off":
        return {"kind": "off"}
    if kind == "ngram":
        return {
            "kind": "ngram",
            "config": normalize_ngram_speculative(value.get("config")),
        }
    if kind == "native":
        return {
            "kind": "native",
            "config": normalize_native_draft_config(value.get("config")),
        }
    raise InputNormalizationError("speculative.kind must be off, ngram, or native.")


class LlamaCppModelProfileNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        names = list(COMPACT_MODEL_PROFILES)
        return io.Schema(
            node_id="OllamaImageList_LlamaCppModelProfile",
            display_name="[llama.cpp] Model Profile",
            category=PROFILE_CATEGORY,
            description=(
                "Bundles model-dependent handler and sampling defaults into one typed "
                "connection."
            ),
            inputs=[
                io.Combo.Input(
                    "profile", options=[*names, "Custom"], default="General"
                ),
                io.String.Input(
                    "custom_chat_template",
                    optional=True,
                    force_input=True,
                    tooltip=(
                        "Optional custom Jinja chat template connected as an input socket. "
                        "When provided, it overrides the GGUF metadata chat template."
                    ),
                ),
                io.Combo.Input(
                    "custom_handler",
                    options=list(HANDLER_NAMES),
                    default="auto",
                    advanced=True,
                ),
                io.Float.Input(
                    "temperature",
                    default=0.2,
                    min=0.0,
                    max=5.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Float.Input(
                    "top_p",
                    default=0.95,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Int.Input(
                    "top_k", default=40, min=0, max=10_000, step=1, advanced=True
                ),
                io.Float.Input(
                    "min_p",
                    default=0.05,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Float.Input(
                    "repeat_penalty",
                    default=1.0,
                    min=0.0,
                    max=5.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Float.Input(
                    "presence_penalty",
                    default=0.0,
                    min=-2.0,
                    max=2.0,
                    step=0.01,
                    advanced=True,
                ),
            ],
            outputs=[
                LlamaCppModelProfileType.Output(
                    "model_profile", display_name="model profile"
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        profile: str,
        custom_handler: str,
        temperature: float,
        top_p: float,
        top_k: int,
        min_p: float,
        repeat_penalty: float,
        presence_penalty: float,
        custom_chat_template: str = "",
    ) -> io.NodeOutput:
        resolved_template = str(
            unwrap_optional_scalar("custom_chat_template", custom_chat_template, "")
        )
        if profile == "Custom":
            value = {
                "handler": custom_handler,
                "recommended_reasoning_mode": "auto",
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "min_p": min_p,
                "presence_penalty": presence_penalty,
                "repeat_penalty": repeat_penalty,
                "custom_chat_template": resolved_template,
            }
        else:
            try:
                base = COMPACT_MODEL_PROFILES[profile]
            except KeyError as exc:
                raise InputNormalizationError(
                    f"Unknown Llama.cpp Compact profile: {profile}"
                ) from exc
            value = {**base, "custom_chat_template": resolved_template}
        return io.NodeOutput(normalize_compact_model_profile(value))


class LlamaCppHardwareRuntimeProfileNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppHardwareRuntimeProfile",
            display_name="[llama.cpp] Hardware Runtime Profile",
            category=PROFILE_CATEGORY,
            description=(
                "Bundles hardware-dependent batch, offload, CPU, attention, and mmap "
                "settings. n_ubatch=0 uses the backend default."
            ),
            inputs=[
                io.Combo.Input(
                    "profile",
                    options=[*COMPACT_HARDWARE_PROFILES, "Custom"],
                    default="Automatic Offload",
                ),
                io.Int.Input(
                    "n_batch", default=512, min=1, max=65_536, step=1, advanced=True
                ),
                io.Int.Input(
                    "n_ubatch",
                    default=0,
                    min=0,
                    max=65_536,
                    step=1,
                    advanced=True,
                    tooltip="0 uses the llama.cpp backend default.",
                ),
                io.Combo.Input(
                    "gpu_layers",
                    options=["all", "auto", "cpu"],
                    default="auto",
                    advanced=True,
                ),
                io.Int.Input(
                    "main_gpu", default=0, min=0, max=31, step=1, advanced=True
                ),
                io.Int.Input(
                    "n_threads", default=0, min=0, max=1_024, step=1, advanced=True
                ),
                io.Combo.Input(
                    "flash_attention",
                    options=["auto", "enabled", "disabled"],
                    default="auto",
                    advanced=True,
                ),
                io.Boolean.Input("use_mmap", default=True, advanced=True),
            ],
            outputs=[
                LlamaCppHardwareRuntimeProfileType.Output(
                    "hardware_profile", display_name="hardware profile"
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        profile: str,
        n_batch: int,
        n_ubatch: int,
        gpu_layers: str,
        main_gpu: int,
        n_threads: int,
        flash_attention: str,
        use_mmap: bool,
    ) -> io.NodeOutput:
        if profile == "Custom":
            value = {
                "n_batch": n_batch,
                "n_ubatch": n_ubatch,
                "gpu_layers": gpu_layers,
                "main_gpu": main_gpu,
                "n_threads": n_threads,
                "flash_attention": flash_attention,
                "use_mmap": use_mmap,
            }
        else:
            try:
                value = COMPACT_HARDWARE_PROFILES[profile]
            except KeyError as exc:
                raise InputNormalizationError(
                    f"Unknown Llama.cpp Compact hardware profile: {profile}"
                ) from exc
        return io.NodeOutput(normalize_compact_hardware_profile(value))


class LlamaCppReasoningConfigNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppReasoningConfig",
            display_name="[llama.cpp] Thinking / Reasoning Profile",
            category=PROFILE_CATEGORY,
            description=(
                "Controls thinking/reasoning mode, effort, and token budget for "
                "supported model templates. A zero token limit applies no separate "
                "reasoning budget."
            ),
            search_aliases=["thinking", "reasoning"],
            inputs=[
                io.Combo.Input(
                    "reasoning_mode",
                    options=["auto", "off", "on"],
                    default="auto",
                    tooltip=(
                        "auto leaves template controls untouched; off and on explicitly "
                        "disable or enable reasoning."
                    ),
                ),
                io.Combo.Input(
                    "reasoning_effort",
                    options=list(REASONING_STRENGTHS),
                    default="auto",
                    tooltip="Used only when reasoning_mode is on.",
                ),
                io.Int.Input(
                    "max_reasoning_tokens",
                    default=0,
                    min=0,
                    max=65_536,
                    step=1,
                    tooltip=(
                        "0 applies no separate reasoning limit. Reasoning and final "
                        "output still share Generate's max_tokens."
                    ),
                ),
                io.Boolean.Input(
                    "preserve_thinking",
                    default=False,
                    tooltip=(
                        "Preserve thinking/reasoning content in the chat history "
                        "passed to the model."
                        "Currently, Qwen3.5+ only and may not work."
                    ),
                ),
            ],
            outputs=[
                LlamaCppReasoningConfigType.Output(
                    "reasoning", display_name="reasoning"
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        reasoning_mode: str,
        reasoning_effort: str,
        max_reasoning_tokens: int,
        preserve_thinking: bool = False,
    ) -> io.NodeOutput:
        return io.NodeOutput(
            normalize_reasoning_config(
                {
                    "reasoning_mode": reasoning_mode,
                    "reasoning_effort": reasoning_effort,
                    "max_reasoning_tokens": max_reasoning_tokens,
                    "preserve_thinking": preserve_thinking,
                }
            )
        )


class LlamaCppNGramSpeculativeConfigNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppNGramSpeculativeConfig",
            display_name="[llama.cpp] N-gram Speculative Config",
            category=COMPACT_CATEGORY,
            description=(
                "Produces the shared Compact speculative input using model-free "
                "prompt-history N-gram drafting."
            ),
            inputs=[
                io.Combo.Input(
                    "speculative_mode", options=["off", "ngram"], default="off"
                ),
                io.Int.Input("ngram_size", default=3, min=1, max=8, step=1),
                io.Int.Input("num_pred_tokens", default=10, min=1, max=32, step=1),
                io.Combo.Input("ngram_mode", options=["k", "k4v"], default="k"),
                io.Int.Input("ngram_min_hits", default=2, min=1, max=16, step=1),
                io.Int.Input(
                    "ngram_max_entries_per_key",
                    default=8,
                    min=0,
                    max=1024,
                    step=1,
                ),
            ],
            outputs=[
                LlamaCppSpeculativeConfigType.Output(
                    "speculative", display_name="speculative"
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
    ) -> io.NodeOutput:
        config = normalize_ngram_speculative(
            {
                "speculative_mode": speculative_mode,
                "ngram_size": ngram_size,
                "num_pred_tokens": num_pred_tokens,
                "ngram_mode": ngram_mode,
                "ngram_min_hits": ngram_min_hits,
                "ngram_max_entries_per_key": ngram_max_entries_per_key,
            }
        )
        if config["speculative_mode"] == "off":
            return io.NodeOutput({"kind": "off"})
        return io.NodeOutput({"kind": "ngram", "config": config})


class LlamaCppNativeSpeculativeConfigNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        draft_options = _draft_gguf_options()
        return io.Schema(
            node_id="OllamaImageList_LlamaCppNativeSpeculativeConfig",
            display_name="[llama.cpp] Native Speculative Profile",
            category=PROFILE_CATEGORY,
            description=(
                "Bundles DFlash, DSpark, or Native MTP configuration and its optional "
                "draft GGUF into one typed connection."
            ),
            inputs=[
                io.Combo.Input(
                    "preset",
                    options=[*NATIVE_DRAFT_PRESETS, "Custom"],
                    default="Off",
                ),
                io.Combo.Input(
                    "draft_model",
                    options=draft_options,
                    default=draft_options[0],
                    tooltip=(
                        "Used by External MTP, DFlash, and DSpark. Internal MTP "
                        "does not use a draft GGUF."
                    ),
                ),
                io.Int.Input("draft_n_max", default=2, min=1, max=64, step=1),
                io.Combo.Input(
                    "custom_spec_type",
                    options=[
                        "none",
                        "draft-dflash",
                        "draft-dspark",
                        "draft-mtp",
                    ],
                    default="draft-dflash",
                    advanced=True,
                ),
                io.Combo.Input(
                    "custom_mtp_provider",
                    options=["off", "external", "internal"],
                    default="off",
                    advanced=True,
                ),
                io.Float.Input(
                    "draft_p_min",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Combo.Input(
                    "draft_n_gpu_layers",
                    options=["auto", "all"],
                    default="all",
                    advanced=True,
                ),
                io.Boolean.Input(
                    "draft_backend_sampling",
                    default=True,
                    advanced=True,
                ),
            ],
            outputs=[
                LlamaCppSpeculativeConfigType.Output(
                    "speculative", display_name="speculative"
                ),
            ],
            is_experimental=True,
        )

    @classmethod
    def execute(
        cls,
        preset: str,
        draft_model: str,
        draft_n_max: int,
        custom_spec_type: str,
        custom_mtp_provider: str,
        draft_p_min: float,
        draft_n_gpu_layers: str | int,
        draft_backend_sampling: bool,
    ) -> io.NodeOutput:
        if preset == "Off":
            return io.NodeOutput({"kind": "off"})
        if preset == "Custom":
            value = {
                "spec_type": custom_spec_type,
                "mtp_provider": custom_mtp_provider,
            }
        else:
            try:
                value = dict(NATIVE_DRAFT_PRESETS[preset])
            except KeyError as exc:
                raise InputNormalizationError(
                    f"Unknown Llama.cpp Native Speculative preset: {preset}"
                ) from exc
        value.update(
            draft_model=draft_model,
            draft_n_max=draft_n_max,
            draft_p_min=draft_p_min,
            draft_n_gpu_layers=draft_n_gpu_layers,
            draft_backend_sampling=draft_backend_sampling,
        )
        config = normalize_native_draft_config(value)
        if config["spec_type"] == "none":
            return io.NodeOutput({"kind": "off"})
        return io.NodeOutput({"kind": "native", "config": config})


def _compact_outputs(result: Any, *, as_lists: bool = False) -> io.NodeOutput:
    values = (
        result.response,
        result.thinking,
        json.dumps(result.raw, ensure_ascii=False, indent=2),
        json.dumps(result.metrics, ensure_ascii=False, indent=2),
        result.media_diagnostics,
    )
    if as_lists:
        return io.NodeOutput(*([value] for value in values))
    return io.NodeOutput(*values)


def _compact_sequential_outputs(
    results: list[Any], task_kinds: list[str | None]
) -> io.NodeOutput:
    if len(results) != len(task_kinds):
        raise InputNormalizationError(
            "Sequential output requires one media kind per result."
        )
    modality_indices = {"image": 0, "audio": 0, "video": 0, "text": 0}
    response_seq = []
    for request_index, (result, kind) in enumerate(
        zip(results, task_kinds, strict=True)
    ):
        response_kind = kind or "text"
        modality_index = modality_indices[response_kind]
        modality_indices[response_kind] += 1
        response_seq.append(
            {
                "request_index": request_index,
                "kind": response_kind,
                "modality_index": modality_index,
                "response": result.response,
            }
        )

    return io.NodeOutput(
        [result.response for result in results],
        response_seq,
        [result.thinking for result in results],
        [json.dumps(result.raw, ensure_ascii=False, indent=2) for result in results],
        [
            json.dumps(result.metrics, ensure_ascii=False, indent=2)
            for result in results
        ],
        [result.media_diagnostics for result in results],
    )


def _sequential_media_bundles(
    *,
    images: Any = None,
    audio: Any = None,
    video: Any = None,
    video_with_audio: bool = False,
) -> list[MediaBundle]:
    image_items = normalize_images(images).items
    audio_items = normalize_audio(
        audio,
        target_sample_rate=16_000,
        target_channels=1,
    ).items
    video_bundle = normalize_media(
        video=video,
        video_with_audio=video_with_audio,
        audio_sample_rate=16_000,
        audio_channels=1,
    )
    video_items = tuple(item for item in video_bundle.items if item.kind == "video")
    embedded_audio_items = tuple(
        item for item in video_bundle.items if item.kind == "audio"
    )
    if not image_items and not audio_items and not video_items:
        return [MediaBundle()]

    bundles: list[MediaBundle] = []
    bundles.extend(MediaBundle((item,)) for item in image_items)
    bundles.extend(MediaBundle((item,)) for item in audio_items)
    for index, video_item in enumerate(video_items):
        video_bundle_items = (embedded_audio_items[index],) if video_with_audio else ()
        bundles.append(MediaBundle(video_bundle_items + (video_item,)))
    return bundles


def _sequential_prompts(prompt: Any, item_count: int) -> list[str]:
    prompts = prompt if isinstance(prompt, (list, tuple)) else [prompt]
    prompts = [str(value) for value in prompts]
    if not prompts:
        raise InputNormalizationError(
            "Sequential Generate requires at least one prompt."
        )
    if item_count > 1 and len(prompts) not in (1, item_count):
        raise InputNormalizationError(
            "When sequential media is connected, prompt must contain exactly one "
            "prompt or one prompt for each execution item "
            f"(received {len(prompts)}, expected 1 or {item_count})."
        )
    if len(prompts) == 1:
        return prompts * item_count
    return prompts


def _compact_output_fields(*, is_output_list: bool = False) -> list[Any]:
    outputs = [
        io.String.Output(
            "response", display_name="response", is_output_list=is_output_list
        ),
        io.String.Output(
            "thinking", display_name="thinking", is_output_list=is_output_list
        ),
        io.String.Output(
            "raw_json", display_name="raw JSON", is_output_list=is_output_list
        ),
        io.String.Output(
            "metrics_json", display_name="metrics", is_output_list=is_output_list
        ),
        LlamaCppMediaDiagnosticsType.Output(
            "media_diagnostics",
            display_name="media diagnostics",
            is_output_list=is_output_list,
        ),
    ]
    if is_output_list:
        outputs[0:1] = [
            outputs[0],
            LlamaCppSequentialResponseType.Output(
                "response_seq",
                display_name="response sequence",
                is_output_list=True,
            ),
        ]
    return outputs


def _compact_common_inputs(*, include_video_with_audio: bool = True) -> list[Any]:
    model_options, mmproj_options = _gguf_options()
    inputs = [
        io.Combo.Input("model_path", options=model_options, default=model_options[0]),
        io.Combo.Input("mmproj_path", options=mmproj_options, default=NO_MMPROJ_OPTION),
        LlamaCppModelProfileType.Input(
            "model_profile",
            tooltip="Required output from [llama.cpp] Model Profile.",
        ),
        LlamaCppHardwareRuntimeProfileType.Input(
            "hardware_profile",
            optional=True,
            tooltip=(
                "Optional output from [llama.cpp] Hardware Runtime Profile. "
                "Disconnected uses Automatic Offload."
            ),
        ),
        io.String.Input("system", default="", multiline=True, dynamic_prompts=False),
        io.String.Input("prompt", default="", multiline=True, dynamic_prompts=False),
        io.Int.Input("n_ctx", default=8_192, min=512, max=1_048_576, step=512),
        io.Int.Input("max_tokens", default=512, min=1, max=131_072, step=1),
        io.Int.Input(
            "image_max_tokens",
            default=0,
            min=0,
            max=65_536,
            step=1,
            tooltip=(
                "0 uses the mmproj/handler default. A positive value overrides the "
                "per-image or per-video-frame token ceiling."
            ),
        ),
        io.Int.Input("seed", default=-1, min=-1, max=0xFFFFFFFF, step=1),
        io.String.Input("stop", default="", advanced=True),
        io.Image.Input("images", optional=True),
        io.Audio.Input(
            "audio",
            optional=True,
            tooltip="Standalone AUDIO items. Audio belonging to VIDEO stays in VIDEO.",
        ),
        io.Video.Input(
            "video",
            optional=True,
            tooltip="VIDEO items may contain their own AUDIO components.",
        ),
        io.Boolean.Input("verbose", default=False, advanced=True),
        io.Int.Input(
            "image_min_tokens",
            default=0,
            min=0,
            max=65_536,
            step=1,
            tooltip=(
                "0 keeps the projector default. Qwen-VL grounding tasks may require 1024."
            ),
        ),
    ]
    if include_video_with_audio:
        inputs.insert(
            14,
            io.Boolean.Input(
                "video_with_audio",
                default=False,
                tooltip=(
                    "When enabled, extract the first embedded video audio track with "
                    "PyAV and pass it through the AUDIO input path."
                ),
            ),
        )
    return inputs


def build_compact_session_kwargs(
    *,
    model_path: Any,
    mmproj_path: Any,
    model_profile: Any,
    hardware_profile: Any = None,
    reasoning: Any = None,
    speculative: Any = None,
    n_ctx: Any,
    image_min_tokens: Any,
    image_max_tokens: Any,
    verbose: Any,
    custom_handler: Any = "auto",
    custom_chat_template: Any = "",
) -> dict[str, Any]:
    """Resolve Compact node fields that must remain fixed for one session."""
    speculative_config = {"kind": "off"}
    if speculative is not None:
        speculative_config = normalize_compact_speculative(
            unwrap_required_scalar("speculative", speculative)
        )
    native_config = None
    speculative_api = None
    if speculative_config["kind"] == "native":
        native_config = speculative_config["config"]
        if native_config["spec_type"] != "none":
            speculative_api = require_native_speculative()

    reasoning_config = {
        "reasoning_mode": "auto",
        "reasoning_effort": "auto",
        "max_reasoning_tokens": 0,
        "preserve_thinking": False,
    }
    if reasoning is not None:
        reasoning_config = normalize_reasoning_config(
            unwrap_required_scalar("reasoning", reasoning)
        )
    compact_model_profile = normalize_compact_model_profile(
        unwrap_required_scalar("model_profile", model_profile)
    )
    profile_reasoning_mode = compact_model_profile.pop("recommended_reasoning_mode")
    selected_handler = unwrap_optional_scalar(
        "custom_handler", custom_handler, "auto"
    )
    if selected_handler not in HANDLER_NAMES:
        raise InputNormalizationError(
            f"custom_handler must be one of {', '.join(HANDLER_NAMES)}."
        )
    compact_model_profile["handler"] = selected_handler
    selected_template = unwrap_optional_scalar(
        "custom_chat_template", custom_chat_template, ""
    )
    if not isinstance(selected_template, str):
        raise InputNormalizationError("custom_chat_template must be a string.")
    compact_model_profile["custom_chat_template"] = selected_template
    compact_hardware_profile = normalize_compact_hardware_profile(
        COMPACT_HARDWARE_PROFILES["Automatic Offload"]
        if hardware_profile is None
        else unwrap_required_scalar("hardware_profile", hardware_profile)
    )
    n_ubatch = compact_hardware_profile.pop("n_ubatch")
    reasoning_mode = reasoning_config["reasoning_mode"]
    if (
        profile_reasoning_mode != "auto"
        and reasoning_mode != "auto"
        and reasoning_mode != profile_reasoning_mode
    ):
        raise InputNormalizationError(
            "The selected [llama.cpp] Model Profile requires reasoning_mode="
            f"{profile_reasoning_mode}, but "
            "[llama.cpp] Thinking / Reasoning Profile requests "
            f"reasoning_mode={reasoning_mode}."
        )
    if reasoning_mode == "auto" and profile_reasoning_mode != "auto":
        reasoning_mode = profile_reasoning_mode
    thinking_value = None if reasoning_mode == "auto" else reasoning_mode == "on"
    image_token_floor = int(
        unwrap_optional_scalar("image_min_tokens", image_min_tokens, 0)
    )
    image_token_limit = int(
        unwrap_optional_scalar("image_max_tokens", image_max_tokens, 0)
    )
    extra: dict[str, Any] = {}
    if speculative_config["kind"] == "ngram":
        extra["ngram_speculative"] = speculative_config["config"]
    if native_config is not None:
        spec_type = native_config["spec_type"]
        draft_required = spec_type in {"draft-dflash", "draft-dspark"} or (
            spec_type == "draft-mtp" and native_config["mtp_provider"] == "external"
        )
        extra.update(
            draft_model_path=(
                _resolve_gguf_selection(
                    native_config["draft_model"],
                    label="draft model GGUF",
                    required=draft_required,
                )
                if spec_type != "none"
                else ""
            ),
            spec_type=spec_type,
            spec_n_max=native_config["draft_n_max"],
            spec_n_min=0,
            spec_p_min=native_config["draft_p_min"],
            mtp_provider=native_config["mtp_provider"],
            draft_n_gpu_layers=native_config["draft_n_gpu_layers"],
            draft_backend_sampling=native_config["draft_backend_sampling"],
        )
        if speculative_api is not None:
            extra["speculative_api"] = speculative_api
    return {
        "model_path": _resolve_gguf_selection(
            str(unwrap_required_scalar("model_path", model_path)),
            label="model GGUF",
            required=True,
        ),
        "mmproj_path": _resolve_gguf_selection(
            str(unwrap_optional_scalar("mmproj_path", mmproj_path, NO_MMPROJ_OPTION)),
            label="mmproj GGUF",
            required=False,
        ),
        "n_ctx": int(unwrap_optional_scalar("n_ctx", n_ctx, 8_192)),
        "override_image_min_tokens": image_token_floor > 0,
        "image_min_tokens": image_token_floor if image_token_floor > 0 else 1_024,
        "override_image_max_tokens": image_token_limit > 0,
        "image_max_tokens": image_token_limit if image_token_limit > 0 else 1_120,
        "override_n_ubatch": n_ubatch > 0,
        "n_ubatch": n_ubatch if n_ubatch > 0 else 512,
        "thinking": thinking_value,
        "reasoning_strength": reasoning_config["reasoning_effort"],
        "reasoning_budget": reasoning_config["max_reasoning_tokens"],
        "preserve_thinking": reasoning_config["preserve_thinking"],
        "verbose": bool(unwrap_optional_scalar("verbose", verbose, False)),
        **compact_model_profile,
        **compact_hardware_profile,
        **extra,
    }


def _execute_compact(
    *,
    model_path: Any,
    mmproj_path: Any,
    model_profile: Any,
    hardware_profile: Any,
    system: Any,
    prompt: Any,
    n_ctx: Any,
    max_tokens: Any,
    image_min_tokens: Any,
    image_max_tokens: Any,
    seed: Any,
    stop: Any,
    images: Any,
    audio: Any,
    video: Any,
    video_with_audio: Any,
    verbose: Any,
    reasoning: Any = None,
    speculative: Any = None,
    outputs_as_lists: bool = False,
    sequential: bool = False,
) -> io.NodeOutput:
    native_config = None
    speculative_api = None
    speculative_config = {"kind": "off"}
    if speculative is not None:
        speculative_config = normalize_compact_speculative(
            unwrap_required_scalar("speculative", speculative)
        )
    # if sequential and speculative_config["kind"] != "off":
    #     raise InputNormalizationError(
    #         "Sequential Generate requires speculative=off so decoder history cannot "
    #         "carry between independent items."
    #     )
    if speculative_config["kind"] == "native":
        native_config = speculative_config["config"]
        if native_config["spec_type"] != "none":
            speculative_api = require_native_speculative()

    reasoning_config = {
        "reasoning_mode": "auto",
        "reasoning_effort": "auto",
        "max_reasoning_tokens": 0,
        "preserve_thinking": False,
    }
    if reasoning is not None:
        reasoning_config = normalize_reasoning_config(
            unwrap_required_scalar("reasoning", reasoning)
        )

    compact_model_profile = normalize_compact_model_profile(
        unwrap_required_scalar("model_profile", model_profile)
    )
    profile_reasoning_mode = compact_model_profile.pop("recommended_reasoning_mode")
    compact_hardware_profile = normalize_compact_hardware_profile(
        COMPACT_HARDWARE_PROFILES["Automatic Offload"]
        if hardware_profile is None
        else unwrap_required_scalar("hardware_profile", hardware_profile)
    )
    n_ubatch = compact_hardware_profile.pop("n_ubatch")
    image_token_floor = int(
        unwrap_optional_scalar("image_min_tokens", image_min_tokens, 0)
    )
    image_token_limit = int(
        unwrap_optional_scalar("image_max_tokens", image_max_tokens, 0)
    )
    output_token_limit = int(unwrap_optional_scalar("max_tokens", max_tokens, 512))
    reasoning_token_limit = reasoning_config["max_reasoning_tokens"]
    if reasoning_token_limit > output_token_limit:
        raise InputNormalizationError(
            "max_reasoning_tokens cannot exceed Generate max_tokens."
        )
    reasoning_mode = reasoning_config["reasoning_mode"]
    if (
        profile_reasoning_mode != "auto"
        and reasoning_mode != "auto"
        and reasoning_mode != profile_reasoning_mode
    ):
        raise InputNormalizationError(
            "The selected [llama.cpp] Model Profile requires reasoning_mode="
            f"{profile_reasoning_mode}, but "
            "[llama.cpp] Thinking / Reasoning Profile requests "
            f"reasoning_mode={reasoning_mode}."
        )
    if reasoning_mode == "auto" and profile_reasoning_mode != "auto":
        reasoning_mode = profile_reasoning_mode
    thinking_value = None if reasoning_mode == "auto" else reasoning_mode == "on"
    video_with_audio_value = bool(
        unwrap_optional_scalar("video_with_audio", video_with_audio, False)
    )
    bundles = (
        _sequential_media_bundles(
            images=images,
            audio=audio,
            video=video,
            video_with_audio=video_with_audio_value,
        )
        if sequential
        else [
            normalize_media(
                images=images,
                audio=audio,
                video=video,
                video_with_audio=video_with_audio_value,
                audio_sample_rate=16_000,
                audio_channels=1,
            )
        ]
    )
    prompt_items = None
    if sequential:
        raw_prompts = prompt if isinstance(prompt, (list, tuple)) else [prompt]
        if not any(bundle.items for bundle in bundles) and len(raw_prompts) > 1:
            bundles = [normalize_media() for _ in raw_prompts]
        prompt_items = _sequential_prompts(prompt, len(bundles))
    resolved_mmproj = (
        _resolve_gguf_selection(
            str(unwrap_optional_scalar("mmproj_path", mmproj_path, NO_MMPROJ_OPTION)),
            label="mmproj GGUF",
            required=False,
        )
        if any(bundle.items for bundle in bundles)
        else ""
    )
    extra: dict[str, Any] = {}
    if speculative_config["kind"] == "ngram":
        extra["ngram_speculative"] = speculative_config["config"]
    if native_config is not None:
        spec_type = native_config["spec_type"]
        draft_required = spec_type in {
            "draft-dflash",
            "draft-dspark",
        } or (spec_type == "draft-mtp" and native_config["mtp_provider"] == "external")
        extra.update(
            draft_model_path=(
                _resolve_gguf_selection(
                    native_config["draft_model"],
                    label="draft model GGUF",
                    required=draft_required,
                )
                if spec_type != "none"
                else ""
            ),
            spec_type=spec_type,
            spec_n_max=native_config["draft_n_max"],
            spec_n_min=0,
            spec_p_min=native_config["draft_p_min"],
            mtp_provider=native_config["mtp_provider"],
            draft_n_gpu_layers=native_config["draft_n_gpu_layers"],
            draft_backend_sampling=native_config["draft_backend_sampling"],
        )
        if speculative_api is not None:
            extra["speculative_api"] = speculative_api

    run_kwargs = dict(
        model_path=_resolve_gguf_selection(
            str(unwrap_required_scalar("model_path", model_path)),
            label="model GGUF",
            required=True,
        ),
        mmproj_path=resolved_mmproj,
        system=str(unwrap_required_scalar("system", system)),
        prompt=(
            prompt_items[0]
            if prompt_items is not None
            else str(unwrap_required_scalar("prompt", prompt))
        ),
        n_ctx=int(unwrap_optional_scalar("n_ctx", n_ctx, 8_192)),
        max_tokens=output_token_limit,
        override_image_min_tokens=image_token_floor > 0,
        image_min_tokens=image_token_floor if image_token_floor > 0 else 1_024,
        override_image_max_tokens=image_token_limit > 0,
        image_max_tokens=image_token_limit if image_token_limit > 0 else 1_120,
        override_n_ubatch=n_ubatch > 0,
        n_ubatch=n_ubatch if n_ubatch > 0 else 512,
        thinking=thinking_value,
        reasoning_strength=reasoning_config["reasoning_effort"],
        reasoning_budget=reasoning_token_limit,
        preserve_thinking=reasoning_config["preserve_thinking"],
        seed=int(unwrap_optional_scalar("seed", seed, -1)),
        stop=str(unwrap_optional_scalar("stop", stop, "")),
        verbose=bool(unwrap_optional_scalar("verbose", verbose, False)),
        **compact_model_profile,
        **compact_hardware_profile,
        **extra,
    )
    if sequential:
        task_kinds = [
            next((item.kind for item in bundle.items if item.kind == "video"), None)
            or (bundle.items[0].kind if bundle.items else None)
            for bundle in bundles
        ]
        return _compact_sequential_outputs(
            run_chat_sequential(
                media_items=bundles, prompt_items=prompt_items, **run_kwargs
            ),
            task_kinds,
        )
    result = run_chat(media=bundles[0], **run_kwargs)
    return _compact_outputs(result, as_lists=outputs_as_lists)


def _compact_profiled_generate_inputs(
    *, include_video_with_audio: bool = True
) -> list[Any]:
    inputs = _compact_common_inputs(include_video_with_audio=include_video_with_audio)
    inputs.insert(
        4,
        LlamaCppReasoningConfigType.Input(
            "reasoning",
            optional=True,
            tooltip=(
                "Optional output from [llama.cpp] Thinking / Reasoning Profile. "
                "Disconnected uses model-default reasoning behavior."
            ),
        ),
    )
    inputs.insert(
        5,
        LlamaCppSpeculativeConfigType.Input(
            "speculative",
            optional=True,
            tooltip=(
                "Optional shared output from a Compact N-gram or Native Speculative "
                "Config node."
            ),
        ),
    )
    return inputs


# Keep the registered Generate nodes as siblings: ComfyUI caches V3 output-list
# metadata on each class, so a registered subclass can inherit its parent's cache.
class _LlamaCppGenerateNodeBase(io.ComfyNode):
    outputs_as_lists = False
    sequential = False

    @classmethod
    def execute(
        cls,
        model_path,
        mmproj_path,
        model_profile,
        system,
        prompt,
        n_ctx,
        max_tokens,
        image_max_tokens,
        seed,
        stop,
        verbose,
        images=None,
        audio=None,
        video=None,
        video_with_audio=False,
        hardware_profile=None,
        reasoning=None,
        speculative=None,
        image_min_tokens=0,
    ) -> io.NodeOutput:
        return _execute_compact(
            model_path=model_path,
            mmproj_path=mmproj_path,
            model_profile=model_profile,
            hardware_profile=hardware_profile,
            system=system,
            prompt=prompt,
            n_ctx=n_ctx,
            max_tokens=max_tokens,
            image_min_tokens=image_min_tokens,
            image_max_tokens=image_max_tokens,
            seed=seed,
            stop=stop,
            images=images,
            audio=audio,
            video=video,
            video_with_audio=video_with_audio,
            verbose=verbose,
            reasoning=reasoning,
            speculative=speculative,
            outputs_as_lists=cls.outputs_as_lists,
            sequential=cls.sequential,
        )


class LlamaCppProfiledGenerateNode(_LlamaCppGenerateNodeBase):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppProfiledGenerate",
            display_name="[llama.cpp] Generate",
            category=COMPACT_CATEGORY,
            description=(
                "Runs one multimodal llama.cpp completion using separate Compact model "
                "and hardware profiles plus optional reasoning and speculative configs."
            ),
            is_input_list=True,
            not_idempotent=True,
            inputs=_compact_profiled_generate_inputs(),
            outputs=_compact_output_fields(),
        )


class LlamaCppSequentialGenerateNode(_LlamaCppGenerateNodeBase):
    outputs_as_lists = True
    sequential = True

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppSequentialGenerate",
            display_name="[llama.cpp] Sequential Generate",
            category=COMPACT_CATEGORY,
            description=(
                "Loads llama.cpp once, resets context before every independent item, "
                "runs the input list sequentially, and unloads once after the sequence."
            ),
            is_input_list=True,
            not_idempotent=True,
            inputs=_compact_profiled_generate_inputs(),
            outputs=_compact_output_fields(is_output_list=True),
        )


__all__ = [
    "COMPACT_HARDWARE_PROFILES",
    "COMPACT_MODEL_PROFILES",
    "LlamaCppHardwareRuntimeProfileNode",
    "LlamaCppHardwareRuntimeProfileType",
    "LlamaCppModelProfileNode",
    "LlamaCppModelProfileType",
    "LlamaCppNGramSpeculativeConfigNode",
    "LlamaCppProfiledGenerateNode",
    "LlamaCppSequentialGenerateNode",
    "LlamaCppSequentialResponseType",
    "LlamaCppReasoningConfigNode",
    "LlamaCppReasoningConfigType",
    "LlamaCppNativeSpeculativeConfigNode",
    "LlamaCppSpeculativeConfigType",
    "NATIVE_DRAFT_PRESETS",
    "normalize_compact_hardware_profile",
    "normalize_compact_model_profile",
    "normalize_compact_speculative",
    "normalize_native_draft_config",
    "normalize_reasoning_config",
]
