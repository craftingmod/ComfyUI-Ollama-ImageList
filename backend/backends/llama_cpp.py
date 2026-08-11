from __future__ import annotations

import base64
import gc
import importlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from ..core import BackendError, InputNormalizationError, MediaBundle


HANDLER_NAMES = (
    "auto",
    "generic",
    "gemma4",
    "qwen3_vl",
    "qwen25_vl",
    "qwen3_asr",
)
REASONING_STRENGTHS = ("low", "medium", "high", "xhigh")
_HANDLER_CLASSES = {
    "generic": "GenericMTMDChatHandler",
    "gemma4": "Gemma4ChatHandler",
    "qwen3_vl": "Qwen3VLChatHandler",
    "qwen25_vl": "Qwen25VLChatHandler",
    "qwen3_asr": "Qwen3ASRChatHandler",
}
_FLASH_ATTN_TYPES = {"auto": -1, "disabled": 0, "enabled": 1}
_SPECULATIVE_TYPES = {"draft-dflash", "draft-dspark"}
_DEFAULT_N_UBATCH = 512
_NATIVE_EXECUTION_LOCK = Lock()
_LOGGER = logging.getLogger(__name__)
_JAMEPENG_RELEASES_URL = "https://github.com/JamePeng/llama-cpp-python/releases/"
_VISION_INSTALL_GUIDE_URL = (
    "https://github.com/goodguy1963/ComfyUI-ThinkingLLM/blob/main/docs/"
    "LLAMA_CPP_PYTHON_VISION_INSTALL.md"
)
_NATIVE_SPECULATIVE_RELEASE_URL = (
    "https://github.com/craftingmod/llama-cpp-python/releases/tag/"
    "v0.3.46-native-speculative.1"
)
_NATIVE_SPECULATIVE_WHEEL_URL = (
    "https://github.com/craftingmod/llama-cpp-python/releases/download/"
    "v0.3.46-native-speculative.1/"
    "llama_cpp_python-0.3.46-speculative-cp313-cu132-win_amd64.whl"
)


def _fork_install_hint() -> str:
    return (
        "This node targets JamePeng's multimodal llama-cpp-python fork.\n"
        f"Installation guide: {_VISION_INSTALL_GUIDE_URL}\n"
        f"Prebuilt wheels: {_JAMEPENG_RELEASES_URL}"
    )


@dataclass(frozen=True, slots=True)
class LlamaCppBindings:
    llama_class: type
    handlers: dict[str, type]


@dataclass(frozen=True, slots=True)
class LlamaCppResult:
    response: str
    thinking: str
    raw: dict[str, Any]
    metrics: dict[str, Any]
    media_diagnostics: dict[str, Any]


def _import_bindings() -> LlamaCppBindings:
    try:
        llama_cpp = importlib.import_module("llama_cpp")
    except (ImportError, OSError) as exc:
        raise BackendError(
            "llama-cpp-python could not be imported. Install a wheel compatible with "
            "ComfyUI's Python, platform, and native backend, then restart ComfyUI. "
            + _fork_install_hint()
        ) from exc

    handler_module = None
    for module_name in (
        "llama_cpp.llama_multimodal",
        "llama_cpp.llama_chat_format",
    ):
        try:
            handler_module = importlib.import_module(module_name)
            break
        except (ImportError, OSError):
            continue

    handlers: dict[str, type] = {}
    if handler_module is not None:
        for name, class_name in _HANDLER_CLASSES.items():
            handler_class = getattr(handler_module, class_name, None)
            if handler_class is not None:
                handlers[name] = handler_class

    llama_class = getattr(llama_cpp, "Llama", None)
    if llama_class is None:
        raise BackendError(
            "The installed llama-cpp-python package does not expose Llama. "
            + _fork_install_hint()
        )
    return LlamaCppBindings(llama_class=llama_class, handlers=handlers)


def _import_native_speculative_class() -> type:
    try:
        speculative_module = importlib.import_module("llama_cpp.llama_speculative")
    except (ImportError, OSError) as exc:
        raise BackendError(
            "Native speculative decoding is not installed in the Python environment "
            "that runs ComfyUI. This experimental node requires "
            "llama_cpp.llama_speculative.LlamaNativeSpeculativeDecoding. No model was "
            "loaded.\n"
            f"Release and installation notes: {_NATIVE_SPECULATIVE_RELEASE_URL}\n"
            "CPython 3.13 / CUDA 13.2 / Windows x64 wheel: "
            f"{_NATIVE_SPECULATIVE_WHEEL_URL}\n"
            "Install a wheel compatible with ComfyUI's exact Python, platform, and CUDA "
            "environment, then restart ComfyUI."
        ) from exc

    speculative_class = getattr(
        speculative_module,
        "LlamaNativeSpeculativeDecoding",
        None,
    )
    if speculative_class is None:
        raise BackendError(
            "The installed experimental llama-cpp-python package does not expose "
            "LlamaNativeSpeculativeDecoding. No model was loaded.\n"
            f"Release and installation notes: {_NATIVE_SPECULATIVE_RELEASE_URL}\n"
            "CPython 3.13 / CUDA 13.2 / Windows x64 wheel: "
            f"{_NATIVE_SPECULATIVE_WHEEL_URL}"
        )
    return speculative_class


def require_native_speculative() -> type:
    """Fail the experimental node before request normalization or native model loading."""
    return _import_native_speculative_class()


def _import_ngram_speculative_class() -> type:
    try:
        speculative_module = importlib.import_module("llama_cpp.llama_speculative")
    except (ImportError, OSError) as exc:
        raise BackendError(
            "N-gram speculative decoding is unavailable in the installed "
            "llama-cpp-python package. Upgrade the package or use an N-gram Speculative "
            "Preset with speculative_mode set to off. Native DFlash/DSpark support is not "
            "required for this mode."
        ) from exc

    ngram_class = getattr(speculative_module, "LlamaNGramMapDecoding", None)
    if ngram_class is None:
        raise BackendError(
            "The installed llama-cpp-python package does not expose "
            "LlamaNGramMapDecoding. Upgrade the package or set speculative_mode to off."
        )
    return ngram_class


def normalize_ngram_speculative(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {"speculative_mode": "off"}
    if not isinstance(value, dict):
        raise InputNormalizationError(
            "ngram_speculative must be a Llama.cpp N-gram Speculative Preset object."
        )

    speculative_mode = value.get("speculative_mode")
    if speculative_mode not in {"off", "ngram"}:
        raise InputNormalizationError(
            "ngram_speculative.speculative_mode must be off or ngram."
        )
    if speculative_mode == "off":
        return {"speculative_mode": "off"}

    integer_ranges = {
        "ngram_size": (1, 8),
        "num_pred_tokens": (1, 32),
        "ngram_min_hits": (1, 16),
        "ngram_max_entries_per_key": (0, 1024),
        "ngram_sync_check_tokens": (1, 256),
    }
    normalized: dict[str, Any] = {"speculative_mode": "ngram"}
    for name, (minimum, maximum) in integer_ranges.items():
        candidate = value.get(name)
        if name == "ngram_max_entries_per_key" and candidate is None:
            normalized[name] = None
            continue
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise InputNormalizationError(f"ngram_speculative.{name} must be an integer.")
        if not minimum <= candidate <= maximum:
            raise InputNormalizationError(
                f"ngram_speculative.{name} must be between {minimum} and {maximum}."
            )
        normalized[name] = candidate

    ngram_mode = value.get("ngram_mode")
    if ngram_mode not in {"k", "k4v"}:
        raise InputNormalizationError(
            "ngram_speculative.ngram_mode must be k or k4v."
        )
    normalized["ngram_mode"] = ngram_mode
    if normalized["ngram_max_entries_per_key"] == 0:
        normalized["ngram_max_entries_per_key"] = None
    return normalized


def _resolve_file(value: str, *, label: str, required: bool) -> str | None:
    normalized = value.strip()
    if not normalized:
        if required:
            raise InputNormalizationError(f"{label} is required.")
        return None

    path = Path(normalized).expanduser()
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputNormalizationError(f"{label} does not exist: {normalized}") from exc
    if not path.is_file():
        raise InputNormalizationError(f"{label} is not a file: {normalized}")
    if path.suffix.lower() != ".gguf":
        raise InputNormalizationError(f"{label} must be a GGUF file.")
    return str(path)


def _data_uri(mime_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _build_messages(system: str, prompt: str, media: MediaBundle) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})

    if media.items:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for item in media.items:
            if item.kind == "image":
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _data_uri(item.mime_type, item.payload),
                        },
                    }
                )
            elif item.kind == "audio":
                content.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(item.payload).decode("ascii"),
                            "format": "wav",
                        },
                    }
                )
            elif item.kind == "video":
                content.append(
                    {
                        "type": "video",
                        "video": {
                            "url": _data_uri(item.mime_type, item.payload),
                        },
                    }
                )
            else:  # pragma: no cover - MediaKind prevents this
                raise InputNormalizationError(
                    f"The llama.cpp multimodal node does not support {item.kind} media."
                )
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})
    return messages


def _adapt_messages_for_model_template(
    messages: list[dict[str, Any]],
    *,
    handler: str,
    metadata: Any,
) -> list[dict[str, Any]]:
    """Adapt OpenAI media parts when an auto-selected model template requires it."""
    if handler != "auto" or not isinstance(metadata, dict):
        return messages

    architecture = str(metadata.get("general.architecture", "")).strip().lower()
    if architecture.replace("_", "-") != "muse-glimmer":
        return messages

    adapted_messages: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            adapted_messages.append(message)
            continue

        adapted_content: list[Any] = []
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                adapted_content.append(part)
                continue

            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                url = image_url.get("url")
            else:
                url = image_url
            if not isinstance(url, str) or not url:
                adapted_content.append(part)
                continue

            # Muse-Glimmer's embedded template emits <|patch|> only for
            # template-native image parts. GenericMTMDChatHandler accepts this
            # representation and still extracts the same data URI as media.
            adapted_content.append({"type": "image", "image": url})

        adapted_messages.append({**message, "content": adapted_content})

    return adapted_messages


def _create_handler(
    bindings: LlamaCppBindings,
    *,
    handler: str,
    mmproj_path: str | None,
    verbose: bool,
    thinking: bool,
    reasoning_strength: str,
    image_max_tokens: int | None,
) -> Any | None:
    if handler == "auto":
        return None
    if handler not in HANDLER_NAMES:
        raise InputNormalizationError(
            f"handler must be one of {', '.join(HANDLER_NAMES)}."
        )
    if mmproj_path is None:
        raise InputNormalizationError(f"mmproj_path is required for the {handler} handler.")
    handler_class = bindings.handlers.get(handler)
    if handler_class is None:
        class_name = _HANDLER_CLASSES[handler]
        raise BackendError(
            f"The installed llama-cpp-python build does not provide {class_name}. "
            + _fork_install_hint()
        )
    handler_kwargs: dict[str, Any] = {
        "mmproj_path": mmproj_path,
        "verbose": verbose,
    }
    if image_max_tokens is not None:
        handler_kwargs["image_max_tokens"] = image_max_tokens
    if handler == "gemma4":
        handler_kwargs["enable_thinking"] = thinking
    elif handler == "qwen3_vl":
        handler_kwargs["force_reasoning"] = thinking
    else:
        handler_kwargs["extra_template_arguments"] = {
            "enable_thinking": thinking,
            "force_reasoning": thinking,
            "reasoning_strength": reasoning_strength,
        }
    if handler == "generic":
        handler_kwargs["chat_format"] = None
    return handler_class(**handler_kwargs)


def _optional_positive_override(name: str, enabled: bool, value: int) -> int | None:
    if not enabled:
        return None
    normalized = int(value)
    if normalized < 1:
        raise InputNormalizationError(f"{name} must be at least 1 when its override is enabled.")
    return normalized


def _effective_reasoning_strength(thinking: bool, value: str) -> str:
    if not thinking:
        return "low"
    normalized = str(value).strip().lower()
    if normalized not in REASONING_STRENGTHS:
        raise InputNormalizationError(
            f"reasoning_strength must be one of {', '.join(REASONING_STRENGTHS)}."
        )
    return normalized


def _validate_multimodal_batch_settings(
    *,
    media: MediaBundle,
    n_ctx: int,
    n_batch: int,
    n_ubatch: int | None,
    image_max_tokens: int | None,
) -> None:
    if n_ubatch is not None and n_ubatch > min(n_ctx, n_batch):
        raise InputNormalizationError(
            "n_ubatch cannot exceed n_batch or n_ctx because llama-cpp-python clamps the "
            "physical batch to both values."
        )
    if image_max_tokens is None or not any(
        item.kind in {"image", "video"} for item in media.items
    ):
        return

    if image_max_tokens > n_ctx:
        raise InputNormalizationError(
            "image_max_tokens cannot exceed n_ctx for an image or video request."
        )
    if image_max_tokens > n_batch:
        raise InputNormalizationError(
            "n_batch must be at least image_max_tokens for an image or video request."
        )
    effective_n_ubatch = n_ubatch
    if effective_n_ubatch is None:
        effective_n_ubatch = min(n_ctx, n_batch, _DEFAULT_N_UBATCH)
    if image_max_tokens > effective_n_ubatch:
        raise InputNormalizationError(
            "The effective n_ubatch must be at least image_max_tokens for an image or video "
            "request. Enable the n_ubatch override and raise its value to avoid a native "
            "non-causal attention assertion."
        )


def _extract_response(raw: dict[str, Any]) -> tuple[str, str]:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise BackendError("llama-cpp-python returned a response without a choices array.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise BackendError("llama-cpp-python returned a response without an assistant message.")

    content = message.get("content")
    response = "" if content is None else str(content)
    thinking_value = message.get("reasoning_content", message.get("thinking", ""))
    thinking = "" if thinking_value is None else str(thinking_value)

    if not thinking:
        if response.startswith("<think>") and "</think>" in response:
            reasoning, response = response[len("<think>") :].split("</think>", 1)
            thinking = reasoning.strip()
            response = response.lstrip()
        elif response.startswith("<|channel>thought"):
            channel = response[len("<|channel>thought") :].lstrip("\r\n")
            if "<channel|>" in channel:
                reasoning, response = channel.split("<channel|>", 1)
                thinking = reasoning.strip()
                response = response.lstrip()
            else:
                thinking = channel.strip()
                response = ""
    return response, thinking


def _capture_media_diagnostics(
    *,
    llm: Any,
    fallback_handler: Any,
    media: MediaBundle,
    model_path: str,
    mmproj_path: str | None,
) -> dict[str, Any]:
    """Copy fork MTMD state while the native handler is still alive."""
    active_handler = getattr(llm, "chat_handler", None) or fallback_handler
    handler_name = type(active_handler).__name__ if active_handler is not None else "none"
    vision_available = bool(getattr(active_handler, "is_support_vision", False))
    audio_available = bool(getattr(active_handler, "is_support_audio", False))
    video_available = bool(getattr(active_handler, "is_support_video", False))
    strict_mtmd_pipeline = active_handler is not None and all(
        callable(getattr(active_handler, method_name, None))
        for method_name in (
            "_get_media_items",
            "_mtmd_tokenize",
            "_process_mtmd_prompt",
        )
    )

    manifest = media.manifest()
    requested_image_count = int(manifest["image_count"])
    requested_audio_count = int(manifest["audio_count"])
    requested_video_count = int(manifest["video_count"])
    modalities_available = (
        (requested_image_count == 0 or vision_available)
        and (requested_audio_count == 0 or audio_available)
        and (requested_video_count == 0 or video_available)
    )
    verified = strict_mtmd_pipeline and modalities_available
    evaluated_image_count = requested_image_count if verified else 0
    evaluated_audio_count = requested_audio_count if verified else 0
    evaluated_video_count = requested_video_count if verified else 0
    requested_media_count = (
        requested_image_count + requested_audio_count + requested_video_count
    )
    evaluated_media_count = (
        evaluated_image_count + evaluated_audio_count + evaluated_video_count
    )

    if requested_media_count == 0:
        verification = "no_media"
        all_media_evaluated = True
    elif verified and evaluated_media_count == requested_media_count:
        verification = "mtmd_evaluated"
        all_media_evaluated = True
    else:
        verification = "unavailable"
        all_media_evaluated = False

    return {
        "schema_version": 1,
        "backend": "llama-cpp-python",
        "model": Path(model_path).name,
        "mmproj": Path(mmproj_path).name if mmproj_path else None,
        "handler": handler_name,
        "capabilities": {
            "vision": vision_available,
            "audio": audio_available,
            "video": video_available,
        },
        "requested": manifest,
        "evaluated": {
            "media_count": evaluated_media_count,
            "image_count": evaluated_image_count,
            "audio_count": evaluated_audio_count,
            "video_count": evaluated_video_count,
        },
        "mtmd": {
            "strict_pipeline": strict_mtmd_pipeline,
            "completion_succeeded": True,
            "all_media_evaluated": all_media_evaluated,
            "verification": verification,
        },
    }


def run_chat(
    *,
    model_path: str,
    mmproj_path: str = "",
    handler: str = "auto",
    system: str,
    prompt: str,
    media: MediaBundle,
    n_ctx: int = 8192,
    n_batch: int = 512,
    override_n_ubatch: bool = False,
    n_ubatch: int = _DEFAULT_N_UBATCH,
    gpu_layers: str = "all",
    main_gpu: int = 0,
    n_threads: int = 0,
    flash_attention: str = "auto",
    use_mmap: bool = True,
    max_tokens: int = 512,
    thinking: bool = False,
    reasoning_strength: str = "high",
    override_image_max_tokens: bool = False,
    image_max_tokens: int = 1120,
    temperature: float = 0.2,
    top_p: float = 0.95,
    top_k: int = 40,
    min_p: float = 0.05,
    repeat_penalty: float = 1.0,
    seed: int = -1,
    stop: str = "",
    verbose: bool = False,
    draft_model_path: str = "",
    spec_type: str = "draft-dflash",
    spec_n_max: int = 8,
    spec_n_min: int = 0,
    spec_p_min: float = 0.0,
    ngram_speculative: dict[str, Any] | None = None,
    bindings: LlamaCppBindings | None = None,
    speculative_class: type | None = None,
    ngram_speculative_class: type | None = None,
) -> LlamaCppResult:
    effective_reasoning_strength = _effective_reasoning_strength(
        bool(thinking),
        reasoning_strength,
    )
    ngram_configuration = normalize_ngram_speculative(ngram_speculative)
    resolved_model = _resolve_file(model_path, label="model_path", required=True)
    has_media = bool(media.items)
    resolved_mmproj = (
        _resolve_file(mmproj_path, label="mmproj_path", required=False)
        if has_media
        else None
    )
    resolved_draft = _resolve_file(
        draft_model_path,
        label="draft_model_path",
        required=False,
    )
    if has_media and resolved_mmproj is None:
        raise InputNormalizationError(
            "mmproj_path is required when image, audio, or video media are supplied."
        )
    if flash_attention not in _FLASH_ATTN_TYPES:
        raise InputNormalizationError("flash_attention must be auto, enabled, or disabled.")
    if gpu_layers not in {"auto", "all", "cpu"}:
        raise InputNormalizationError("gpu_layers must be auto, all, or cpu.")
    if resolved_draft is not None:
        if spec_type not in _SPECULATIVE_TYPES:
            raise InputNormalizationError(
                "spec_type must be draft-dflash or draft-dspark."
            )
        if int(spec_n_max) < 1:
            raise InputNormalizationError("spec_n_max must be at least 1.")
        if int(spec_n_min) < 0 or int(spec_n_min) > int(spec_n_max):
            raise InputNormalizationError(
                "spec_n_min must be between 0 and spec_n_max."
            )
        if not 0.0 <= float(spec_p_min) <= 1.0:
            raise InputNormalizationError("spec_p_min must be between 0.0 and 1.0.")
    if (
        resolved_draft is not None
        and ngram_configuration["speculative_mode"] == "ngram"
    ):
        raise InputNormalizationError(
            "Native draft GGUF and N-gram speculative decoding cannot be enabled together."
        )

    n_ubatch_override = _optional_positive_override(
        "n_ubatch", override_n_ubatch, n_ubatch
    )
    image_max_tokens_override = _optional_positive_override(
        "image_max_tokens", override_image_max_tokens, image_max_tokens
    )
    _validate_multimodal_batch_settings(
        media=media,
        n_ctx=int(n_ctx),
        n_batch=int(n_batch),
        n_ubatch=n_ubatch_override,
        image_max_tokens=image_max_tokens_override,
    )

    messages = _build_messages(system, prompt, media)
    native = bindings or _import_bindings()
    native_speculative_class = None
    if resolved_draft is not None:
        native_speculative_class = (
            speculative_class or _import_native_speculative_class()
        )
    ngram_class = None
    if ngram_configuration["speculative_mode"] == "ngram":
        ngram_class = ngram_speculative_class or _import_ngram_speculative_class()
    load_seconds = 0.0
    generation_seconds = 0.0
    cleanup_seconds = 0.0
    llm = None
    chat_handler = None
    draft_model = None
    raw: dict[str, Any] | None = None
    media_diagnostics: dict[str, Any] | None = None
    speculative_stats: dict[str, Any] | None = None
    execution_error: Exception | None = None
    cleanup_error: Exception | None = None

    with _NATIVE_EXECUTION_LOCK:
        load_started = time.perf_counter()
        try:
            chat_handler = (
                _create_handler(
                    native,
                    handler=handler,
                    mmproj_path=resolved_mmproj,
                    verbose=verbose,
                    thinking=bool(thinking),
                    reasoning_strength=effective_reasoning_strength,
                    image_max_tokens=image_max_tokens_override,
                )
                if has_media
                else None
            )
            model_kwargs: dict[str, Any] = {
                "model_path": resolved_model,
                "n_ctx": int(n_ctx),
                "n_batch": int(n_batch),
                "n_gpu_layers": 0 if gpu_layers == "cpu" else gpu_layers,
                "main_gpu": int(main_gpu),
                "n_threads": None if int(n_threads) <= 0 else int(n_threads),
                "flash_attn_type": _FLASH_ATTN_TYPES[flash_attention],
                "use_mmap": bool(use_mmap),
                "verbose": bool(verbose),
            }
            if n_ubatch_override is not None:
                model_kwargs["n_ubatch"] = n_ubatch_override
            if chat_handler is not None:
                model_kwargs["chat_handler"] = chat_handler
            elif resolved_mmproj is not None:
                model_kwargs["mmproj_path"] = resolved_mmproj
                model_kwargs["chat_handler_kwargs"] = {
                    "verbose": bool(verbose),
                    "extra_template_arguments": {
                        "enable_thinking": bool(thinking),
                        "force_reasoning": bool(thinking),
                        "reasoning_strength": effective_reasoning_strength,
                    },
                }
                if image_max_tokens_override is not None:
                    model_kwargs["chat_handler_kwargs"]["image_max_tokens"] = (
                        image_max_tokens_override
                    )

            if resolved_draft is not None:
                draft_model = native_speculative_class(
                    model_path=resolved_draft,
                    spec_type=spec_type,
                    n_gpu_layers=model_kwargs["n_gpu_layers"],
                    n_max=int(spec_n_max),
                    n_min=int(spec_n_min),
                    p_min=float(spec_p_min),
                )
                model_kwargs["draft_model"] = draft_model
            elif ngram_configuration["speculative_mode"] == "ngram":
                try:
                    draft_model = ngram_class(
                        ngram_size=ngram_configuration["ngram_size"],
                        num_pred_tokens=ngram_configuration["num_pred_tokens"],
                        mode=ngram_configuration["ngram_mode"],
                        min_hits=ngram_configuration["ngram_min_hits"],
                        max_entries_per_key=ngram_configuration[
                            "ngram_max_entries_per_key"
                        ],
                        sync_check_tokens=ngram_configuration[
                            "ngram_sync_check_tokens"
                        ],
                    )
                except TypeError as exc:
                    raise BackendError(
                        "The installed LlamaNGramMapDecoding API is incompatible with "
                        "the required n-gram parameters. Upgrade llama-cpp-python or set "
                        "speculative_mode to off."
                    ) from exc
                model_kwargs["draft_model"] = draft_model
                _LOGGER.info(
                    "N-gram speculative decoding: ngram size=%s, max predicted tokens=%s, "
                    "mode=%s, minimum hits=%s.",
                    ngram_configuration["ngram_size"],
                    ngram_configuration["num_pred_tokens"],
                    ngram_configuration["ngram_mode"],
                    ngram_configuration["ngram_min_hits"],
                )

            llm = native.llama_class(**model_kwargs)
            load_seconds = time.perf_counter() - load_started
            generation_started = time.perf_counter()
            completion_messages = _adapt_messages_for_model_template(
                messages,
                handler=handler,
                metadata=getattr(llm, "metadata", None),
            )
            completion_kwargs: dict[str, Any] = {
                "messages": completion_messages,
                "stream": False,
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
                "top_p": float(top_p),
                "top_k": int(top_k),
                "min_p": float(min_p),
                "repeat_penalty": float(repeat_penalty),
                "seed": None if int(seed) < 0 else int(seed),
            }
            if stop:
                completion_kwargs["stop"] = [stop]
            completion = llm.create_chat_completion(**completion_kwargs)
            generation_seconds = time.perf_counter() - generation_started
            if not isinstance(completion, dict):
                raise BackendError(
                    "llama-cpp-python returned a streaming or non-object response unexpectedly."
                )
            raw = completion
            if resolved_draft is not None and draft_model is not None:
                try:
                    stats_value = getattr(draft_model, "stats", None)
                    speculative_stats = dict(stats_value or {})
                except Exception:  # native stats are diagnostic and must not mask a valid response
                    speculative_stats = {}
                try:
                    drafted_tokens = int(
                        speculative_stats.get("drafted_tokens", 0) or 0
                    )
                    draft_calls = int(speculative_stats.get("draft_calls", 0) or 0)
                except (TypeError, ValueError):
                    drafted_tokens = 0
                    draft_calls = 0
                if draft_calls <= 0 or drafted_tokens <= 0:
                    _LOGGER.warning(
                        "Native speculative decoding completed without draft activity; "
                        "draft_calls=%s, drafted_tokens=%s.",
                        draft_calls,
                        drafted_tokens,
                    )
                else:
                    _LOGGER.info(
                        "Native speculative decoding (%s): drafted tokens=%s, accepted "
                        "tokens=%s, acceptance rate=%s, mean accepted/call=%s.",
                        spec_type,
                        drafted_tokens,
                        speculative_stats.get("accepted_tokens", 0),
                        speculative_stats.get("acceptance_rate", 0.0),
                        speculative_stats.get("mean_accepted_tokens", 0.0),
                    )
            media_diagnostics = _capture_media_diagnostics(
                llm=llm,
                fallback_handler=chat_handler,
                media=media,
                model_path=resolved_model,
                mmproj_path=resolved_mmproj,
            )
        except Exception as exc:  # preserve cleanup while presenting a stable node error
            execution_error = exc
        finally:
            cleanup_started = time.perf_counter()
            cleanup_errors: list[Exception] = []
            if llm is not None:
                try:
                    llm.close()
                except Exception as exc:  # pragma: no cover - platform-specific native failure
                    cleanup_errors.append(exc)
            else:
                for resource in (draft_model, chat_handler):
                    if resource is None:
                        continue
                    try:
                        close_resource = getattr(resource, "close", None)
                        if callable(close_resource):
                            close_resource()
                    except Exception as exc:  # pragma: no cover - platform-specific native failure
                        cleanup_errors.append(exc)
            if cleanup_errors:
                cleanup_error = cleanup_errors[0]
            llm = None
            chat_handler = None
            draft_model = None
            gc.collect()
            cleanup_seconds = time.perf_counter() - cleanup_started

    if execution_error is not None:
        if isinstance(execution_error, (BackendError, InputNormalizationError)):
            raise execution_error
        raise BackendError(f"llama-cpp-python inference failed: {execution_error}") from execution_error
    if cleanup_error is not None:
        raise BackendError(
            f"llama-cpp-python completed, but the model could not be fully unloaded: {cleanup_error}"
        ) from cleanup_error
    if raw is None:  # pragma: no cover - defensive invariant
        raise BackendError("llama-cpp-python did not return a response.")
    if media_diagnostics is None:  # pragma: no cover - defensive invariant
        raise BackendError("llama-cpp-python did not produce media diagnostics.")

    response, thinking_output = _extract_response(raw)
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    metrics = {
        "load_seconds": load_seconds,
        "generation_seconds": generation_seconds,
        "cleanup_seconds": cleanup_seconds,
        "total_seconds": load_seconds + generation_seconds + cleanup_seconds,
        "usage": usage,
        "model_unloaded": True,
        "configuration": {
            "thinking": bool(thinking),
            "reasoning_strength": effective_reasoning_strength,
            "n_ctx": int(n_ctx),
            "n_batch": int(n_batch),
            "n_ubatch_override": n_ubatch_override,
            "image_max_tokens_override": image_max_tokens_override,
        },
    }
    if resolved_draft is not None:
        metrics["speculative"] = {
            "enabled": True,
            "implementation": spec_type,
            "draft_model": Path(resolved_draft).name,
            "n_max": int(spec_n_max),
            "n_min": int(spec_n_min),
            "p_min": float(spec_p_min),
            "stats": speculative_stats or {},
        }
    if ngram_configuration["speculative_mode"] == "ngram":
        metrics["ngram_speculative"] = dict(ngram_configuration)
    media_diagnostics["model_unloaded_after_response"] = True
    return LlamaCppResult(
        response=response,
        thinking=thinking_output,
        raw=raw,
        metrics=metrics,
        media_diagnostics=media_diagnostics,
    )


__all__ = [
    "HANDLER_NAMES",
    "REASONING_STRENGTHS",
    "LlamaCppBindings",
    "LlamaCppResult",
    "normalize_ngram_speculative",
    "require_native_speculative",
    "run_chat",
]
