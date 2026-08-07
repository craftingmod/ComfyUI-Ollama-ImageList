from __future__ import annotations

import base64
import gc
import importlib
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
_HANDLER_CLASSES = {
    "generic": "GenericMTMDChatHandler",
    "gemma4": "Gemma4ChatHandler",
    "qwen3_vl": "Qwen3VLChatHandler",
    "qwen25_vl": "Qwen25VLChatHandler",
    "qwen3_asr": "Qwen3ASRChatHandler",
}
_FLASH_ATTN_TYPES = {"auto": -1, "disabled": 0, "enabled": 1}
_NATIVE_EXECUTION_LOCK = Lock()


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


def _import_bindings() -> LlamaCppBindings:
    try:
        llama_cpp = importlib.import_module("llama_cpp")
    except (ImportError, OSError) as exc:
        raise BackendError(
            "llama-cpp-python could not be imported. Install a wheel compatible with "
            "ComfyUI's Python, platform, and CUDA runtime, then restart ComfyUI."
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
        raise BackendError("The installed llama-cpp-python package does not expose Llama.")
    return LlamaCppBindings(llama_class=llama_class, handlers=handlers)


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
            else:  # pragma: no cover - MediaKind currently prevents this
                raise InputNormalizationError(
                    f"The llama.cpp multimodal node does not support {item.kind} media."
                )
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})
    return messages


def _create_handler(
    bindings: LlamaCppBindings,
    *,
    handler: str,
    mmproj_path: str | None,
    verbose: bool,
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
            f"The installed llama-cpp-python build does not provide {class_name}."
        )
    if handler == "generic":
        return handler_class(chat_format=None, mmproj_path=mmproj_path, verbose=verbose)
    return handler_class(mmproj_path=mmproj_path, verbose=verbose)


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
    gpu_layers: str = "all",
    main_gpu: int = 0,
    n_threads: int = 0,
    flash_attention: str = "auto",
    use_mmap: bool = True,
    max_tokens: int = 512,
    temperature: float = 0.2,
    top_p: float = 0.95,
    top_k: int = 40,
    min_p: float = 0.05,
    repeat_penalty: float = 1.0,
    seed: int = -1,
    stop: str = "",
    verbose: bool = False,
    bindings: LlamaCppBindings | None = None,
) -> LlamaCppResult:
    resolved_model = _resolve_file(model_path, label="model_path", required=True)
    resolved_mmproj = _resolve_file(mmproj_path, label="mmproj_path", required=False)
    if media.items and resolved_mmproj is None:
        raise InputNormalizationError(
            "mmproj_path is required when image or audio media are supplied."
        )
    if flash_attention not in _FLASH_ATTN_TYPES:
        raise InputNormalizationError("flash_attention must be auto, enabled, or disabled.")
    if gpu_layers not in {"auto", "all", "cpu"}:
        raise InputNormalizationError("gpu_layers must be auto, all, or cpu.")

    messages = _build_messages(system, prompt, media)
    native = bindings or _import_bindings()
    load_seconds = 0.0
    generation_seconds = 0.0
    cleanup_seconds = 0.0
    llm = None
    chat_handler = None
    raw: dict[str, Any] | None = None
    execution_error: Exception | None = None
    cleanup_error: Exception | None = None

    with _NATIVE_EXECUTION_LOCK:
        load_started = time.perf_counter()
        try:
            chat_handler = _create_handler(
                native,
                handler=handler,
                mmproj_path=resolved_mmproj,
                verbose=verbose,
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
            if chat_handler is not None:
                model_kwargs["chat_handler"] = chat_handler
            elif resolved_mmproj is not None:
                model_kwargs["mmproj_path"] = resolved_mmproj
                model_kwargs["chat_handler_kwargs"] = {
                    "verbose": bool(verbose),
                }

            llm = native.llama_class(**model_kwargs)
            load_seconds = time.perf_counter() - load_started
            generation_started = time.perf_counter()
            completion_kwargs: dict[str, Any] = {
                "messages": messages,
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
        except Exception as exc:  # preserve cleanup while presenting a stable node error
            execution_error = exc
        finally:
            cleanup_started = time.perf_counter()
            try:
                if llm is not None:
                    llm.close()
                elif chat_handler is not None and hasattr(chat_handler, "close"):
                    chat_handler.close()
            except Exception as exc:  # pragma: no cover - native cleanup failures are platform-specific
                cleanup_error = exc
            finally:
                llm = None
                chat_handler = None
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

    response, thinking = _extract_response(raw)
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    metrics = {
        "load_seconds": load_seconds,
        "generation_seconds": generation_seconds,
        "cleanup_seconds": cleanup_seconds,
        "total_seconds": load_seconds + generation_seconds + cleanup_seconds,
        "usage": usage,
        "model_unloaded": True,
    }
    return LlamaCppResult(response=response, thinking=thinking, raw=raw, metrics=metrics)


__all__ = [
    "HANDLER_NAMES",
    "LlamaCppBindings",
    "LlamaCppResult",
    "run_chat",
]
