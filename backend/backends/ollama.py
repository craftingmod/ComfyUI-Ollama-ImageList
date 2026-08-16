from __future__ import annotations

import base64
import json
import re
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..core import resolve_ollama_options
from ..core.errors import BackendError, InputNormalizationError
from ..core.media import MediaBundle

JsonObject = dict[str, Any]
Transport = Callable[[str, bytes, float], tuple[int, bytes]]
ModelsTransport = Callable[[str, float], tuple[int, bytes]]
_BASE64_RUN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{128,}={0,2}(?![A-Za-z0-9+/])")
_METRIC_FIELDS = (
    "model",
    "created_at",
    "done",
    "done_reason",
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
)


@dataclass(frozen=True, slots=True)
class OllamaResult:
    response: str
    thinking: str
    raw: JsonObject
    metrics: JsonObject
    request_manifest: JsonObject


def _redact_text(value: str) -> str:
    return _BASE64_RUN.sub("<redacted-base64>", value)[:1000]


def _validated_url(value: str) -> SplitResult:
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise InputNormalizationError("Ollama URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"}:
        raise InputNormalizationError("Ollama URL must use http or https.")
    if not hostname:
        raise InputNormalizationError("Ollama URL must include a hostname.")
    if parsed.query or parsed.fragment:
        raise InputNormalizationError("Ollama URL cannot include a query string or fragment.")
    return parsed


def _endpoint_url(value: str) -> str:
    parsed = _validated_url(value)
    path = parsed.path.rstrip("/") + "/api/chat"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _models_url(value: str) -> str:
    parsed = _validated_url(value)
    path = parsed.path.rstrip("/") + "/api/tags"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _safe_url(value: str) -> str:
    parsed = _validated_url(value)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def parse_format_json(value: str) -> str | JsonObject | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped == "json":
        return "json"
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise InputNormalizationError(
            "format_json must be empty, the literal json, or a valid JSON Schema object."
        ) from exc
    if not isinstance(parsed, dict):
        raise InputNormalizationError("format_json must contain a JSON Schema object.")
    return parsed


def parse_think(value: str) -> bool | str:
    mapping: dict[str, bool | str] = {
        "off": False,
        "on": True,
        "low": "low",
        "medium": "medium",
        "high": "high",
        "max": "max",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise InputNormalizationError(f"Unsupported think value {value!r}.") from exc


def build_chat_request(
    *,
    model: str,
    system: str,
    prompt: str,
    media: MediaBundle,
    options: JsonObject,
    format_value: str | JsonObject | None,
    think: bool | str,
    keep_alive: str,
    unload_after_response: bool,
    audio_transport: str,
) -> JsonObject:
    if not model.strip():
        raise InputNormalizationError("model cannot be empty.")

    images = [item for item in media.items if item.kind == "image"]
    audio = [item for item in media.items if item.kind == "audio"]
    if audio:
        if audio_transport == "disabled":
            raise InputNormalizationError(
                "AUDIO input is present, but Ollama has no documented native audio field. "
                "Select experimental_wav_in_images explicitly to try the unofficial transport."
            )
        if audio_transport == "native":
            raise InputNormalizationError(
                "Ollama native audio transport is not available in the documented API."
            )
        if audio_transport != "experimental_wav_in_images":
            raise InputNormalizationError(f"Unsupported audio_transport value {audio_transport!r}.")

    encoded_media = (
        list(media.items)
        if audio_transport == "experimental_wav_in_images"
        else images
    )
    user_message: JsonObject = {"role": "user", "content": prompt}
    if encoded_media:
        user_message["images"] = [base64.b64encode(item.payload).decode("ascii") for item in encoded_media]

    messages: list[JsonObject] = [
        {"role": "system", "content": system},
        user_message,
    ]
    request: JsonObject = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": think,
        "options": options,
        "keep_alive": 0 if unload_after_response else keep_alive,
    }
    if format_value is not None:
        request["format"] = format_value
    return request


def build_request_manifest(
    *,
    url: str,
    request: JsonObject,
    media: MediaBundle,
    audio_transport: str,
) -> JsonObject:
    messages = request.get("messages", [])
    return {
        "url": _safe_url(url),
        "endpoint": "/api/chat",
        "model": request.get("model"),
        "stream": False,
        "think": request.get("think"),
        "keep_alive": request.get("keep_alive"),
        "format": request.get("format"),
        "options": request.get("options", {}),
        "messages": [
            {
                "role": message.get("role"),
                "content_characters": len(str(message.get("content", ""))),
            }
            for message in messages
        ],
        "audio_transport": audio_transport,
        "media": media.manifest(),
    }


def _default_transport(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        detail = exc.read()
        raise BackendError(_http_error_message(exc.code, detail)) from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        raise BackendError(f"Could not reach Ollama: {_redact_text(str(reason))}") from exc


def _default_models_transport(url: str, timeout: float) -> tuple[int, bytes]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        detail = exc.read()
        raise BackendError(_http_error_message(exc.code, detail)) from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        raise BackendError(f"Could not reach Ollama: {_redact_text(str(reason))}") from exc


def _http_error_message(status: int, body: bytes) -> str:
    detail = ""
    try:
        parsed = json.loads(body.decode("utf-8"))
        if isinstance(parsed, dict):
            detail = str(parsed.get("error", ""))
    except (UnicodeDecodeError, json.JSONDecodeError):
        detail = body.decode("utf-8", errors="replace")
    detail = _redact_text(detail.strip())
    return f"Ollama returned HTTP {status}" + (f": {detail}" if detail else ".")


def list_models(
    *,
    url: str,
    timeout_seconds: float = 10,
    transport: ModelsTransport | None = None,
) -> list[str]:
    if timeout_seconds <= 0:
        raise InputNormalizationError("timeout_seconds must be greater than zero.")

    call = transport or _default_models_transport
    status, response_body = call(_models_url(url), float(timeout_seconds))
    if status < 200 or status >= 300:
        raise BackendError(_http_error_message(status, response_body))

    try:
        parsed = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackendError("Ollama returned an invalid model-list response.") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("models"), list):
        raise BackendError("Ollama model-list response did not contain a models array.")

    names: list[str] = []
    seen: set[str] = set()
    for item in parsed["models"]:
        if not isinstance(item, dict):
            continue
        value = item.get("model") or item.get("name")
        if not isinstance(value, str):
            continue
        name = value.strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def chat(
    *,
    url: str,
    model: str,
    system: str,
    prompt: str,
    media: MediaBundle,
    options: JsonObject | None = None,
    options_json: str = "",
    format_json: str = "",
    think: str = "off",
    keep_alive: str = "5m",
    unload_after_response: bool = False,
    timeout_seconds: float = 300,
    audio_transport: str = "disabled",
    transport: Transport | None = None,
) -> OllamaResult:
    if timeout_seconds <= 0:
        raise InputNormalizationError("timeout_seconds must be greater than zero.")
    request = build_chat_request(
        model=model,
        system=system,
        prompt=prompt,
        media=media,
        options=resolve_ollama_options(options, options_json),
        format_value=parse_format_json(format_json),
        think=parse_think(think),
        keep_alive=keep_alive,
        unload_after_response=unload_after_response,
        audio_transport=audio_transport,
    )
    manifest = build_request_manifest(
        url=url,
        request=request,
        media=media,
        audio_transport=audio_transport,
    )
    body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    call = transport or _default_transport
    status, response_body = call(_endpoint_url(url), body, float(timeout_seconds))
    if status < 200 or status >= 300:
        raise BackendError(_http_error_message(status, response_body))
    try:
        parsed = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackendError("Ollama returned a successful response with invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise BackendError("Ollama returned a JSON value that was not an object.")
    message = parsed.get("message", {})
    if not isinstance(message, dict):
        raise BackendError("Ollama response did not contain a valid message object.")
    metrics = {field: parsed[field] for field in _METRIC_FIELDS if field in parsed}
    return OllamaResult(
        response=str(message.get("content", "")),
        thinking=str(message.get("thinking", "")),
        raw=parsed,
        metrics=metrics,
        request_manifest=manifest,
    )
