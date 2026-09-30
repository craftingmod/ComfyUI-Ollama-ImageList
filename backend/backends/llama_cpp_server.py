from __future__ import annotations

import base64
import json
import math
import re
import socket
import time
from threading import Lock
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..core import BackendError, InputNormalizationError, MediaBundle
from ..llama_cpp_session_cleanup import track_session, untrack_session
from .llama_cpp import (
    LlamaCppDecisionResult,
    LlamaCppResult,
    _data_uri,
    _extract_response,
)

Transport = Callable[[str, str, bytes | None, float], tuple[int, bytes]]
_BASE64_RUN = re.compile(
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{128,}={0,2}(?![A-Za-z0-9+/])"
)
_REQUEST_TIMEOUT_SECONDS = 300.0


class _ClosableProcess(Protocol):
    def close(self) -> None: ...


def _validated_url(value: str) -> SplitResult:
    if not isinstance(value, str) or not value.strip():
        raise InputNormalizationError("llama.cpp server URL must be a nonempty string.")
    text = value.strip()
    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise InputNormalizationError("llama.cpp server URL is invalid.") from exc
    if any(character.isspace() for character in text):
        raise InputNormalizationError("llama.cpp server URL cannot contain whitespace.")
    if parsed.scheme not in {"http", "https"}:
        raise InputNormalizationError("llama.cpp server URL must use http or https.")
    if not hostname:
        raise InputNormalizationError("llama.cpp server URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise InputNormalizationError(
            "llama.cpp server URL cannot include credentials."
        )
    if parsed.query or parsed.fragment:
        raise InputNormalizationError(
            "llama.cpp server URL cannot include a query string or fragment."
        )
    return parsed


def _endpoint_url(value: str, endpoint: str) -> str:
    parsed = _validated_url(value)
    path = parsed.path.rstrip("/") + endpoint
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _redact_text(value: str) -> str:
    return _BASE64_RUN.sub("<redacted-base64>", value)[:1000]


def _http_error_message(status: int, body: bytes) -> str:
    detail = ""
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message", ""))
        elif isinstance(error, str):
            detail = error
    elif body:
        detail = body.decode("utf-8", errors="replace")
    detail = _redact_text(detail.strip())
    return f"llama.cpp server returned HTTP {status}" + (
        f": {detail}" if detail else "."
    )


def _default_transport(
    url: str,
    method: str,
    body: bytes | None,
    timeout: float,
    *,
    api_key: str | None = None,
) -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        return int(exc.code), exc.read()
    except (URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        raise BackendError(
            f"Could not reach llama.cpp server: {_redact_text(str(reason))}"
        ) from exc


def _request(
    *,
    url: str,
    method: str,
    body: bytes | None = None,
    timeout_seconds: float,
    api_key: str | None = None,
    transport: Transport | None = None,
) -> bytes:
    if timeout_seconds <= 0:
        raise InputNormalizationError("timeout_seconds must be greater than zero.")
    if transport is None:
        status, response_body = _default_transport(
            url, method, body, float(timeout_seconds), api_key=api_key
        )
    else:
        status, response_body = transport(url, method, body, float(timeout_seconds))
    if status < 200 or status >= 300:
        raise BackendError(_http_error_message(status, response_body))
    return response_body


def parse_models_response(response_body: bytes) -> list[str]:
    try:
        parsed = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackendError(
            "llama.cpp returned an invalid model-list response."
        ) from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
        raise BackendError(
            "llama.cpp model-list response did not contain a data array."
        )

    models: list[str] = []
    seen: set[str] = set()
    for item in parsed["data"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise BackendError("llama.cpp model-list entries must contain a string id.")
        model = item["id"].strip()
        if not model:
            raise BackendError("llama.cpp model-list entries cannot have an empty id.")
        if model not in seen:
            models.append(model)
            seen.add(model)
    return models


def list_server_models(
    *,
    url: str,
    api_key: str | None = None,
    timeout_seconds: float = 10.0,
    transport: Transport | None = None,
) -> list[str]:
    body = _request(
        url=_endpoint_url(url, "/models"),
        method="GET",
        timeout_seconds=timeout_seconds,
        api_key=api_key,
        transport=transport,
    )
    return parse_models_response(body)


def _build_messages(
    system: str, prompt: str, media: MediaBundle
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    if not media.items:
        messages.append({"role": "user", "content": prompt})
        return messages

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for item in media.items:
        if item.kind == "image":
            part = {
                "type": "image_url",
                "image_url": {"url": _data_uri(item.mime_type, item.payload)},
            }
        elif item.kind == "audio":
            part = {
                "type": "input_audio",
                "input_audio": {
                    "data": base64.b64encode(item.payload).decode("ascii"),
                    "format": "wav",
                },
            }
        elif item.kind == "video":
            part = {
                "type": "input_video",
                "input_video": {"data": base64.b64encode(item.payload).decode("ascii")},
            }
        else:
            raise InputNormalizationError(
                f"The llama.cpp server node does not support {item.kind} media."
            )
        content.append(part)
    messages.append({"role": "user", "content": content})
    return messages


class LlamaCppServerSession:
    """A local handle for a model managed by a llama.cpp HTTP server."""

    def __init__(
        self,
        *,
        url: str,
        model: str,
        api_key: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        _endpoint_url(url, "/v1/chat/completions")
        if not isinstance(model, str) or not model.strip():
            raise InputNormalizationError("model cannot be empty.")

        health_body = _request(
            url=_endpoint_url(url, "/health"),
            method="GET",
            timeout_seconds=10.0,
            api_key=api_key,
            transport=transport,
        )
        try:
            health = json.loads(health_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendError(
                "llama.cpp server health check returned invalid JSON."
            ) from exc
        if not isinstance(health, dict) or health.get("status") != "ok":
            status = health.get("status") if isinstance(health, dict) else None
            raise BackendError(
                "llama.cpp server health check failed: expected status 'ok', "
                f"received {_redact_text(str(status))!r}."
            )

        self.url = url.strip()
        self.model = model
        self._api_key = api_key
        self._transport = transport
        self._closed = False
        self._close_lock = Lock()
        self._execution_count = 0
        self._decision_token_ids: dict[str, int] = {}
        track_session(self)

    @property
    def closed(self) -> bool:
        return self._closed

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        media: MediaBundle,
        max_tokens: int,
        seed: int,
        stop: str,
        model_profile: dict[str, Any] | None = None,
    ) -> LlamaCppResult:
        if self._closed:
            raise BackendError(
                "The llama.cpp server session has already been unloaded."
            )
        if not self.model.strip():
            raise InputNormalizationError("model cannot be empty.")
        if max_tokens <= 0:
            raise InputNormalizationError("max_tokens must be greater than zero.")

        request: dict[str, Any] = {
            "model": self.model,
            "messages": _build_messages(system, prompt, media),
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        if model_profile is not None:
            # ponytail: Handler/template are launch-bound; changes need a restart.
            request.update(
                temperature=model_profile["temperature"],
                top_p=model_profile["top_p"],
                top_k=model_profile["top_k"],
                min_p=model_profile["min_p"],
                presence_penalty=model_profile["presence_penalty"],
                repeat_penalty=model_profile["repeat_penalty"],
            )
            if model_profile["recommended_reasoning_mode"] != "auto":
                request["chat_template_kwargs"] = {
                    "enable_thinking": model_profile["recommended_reasoning_mode"]
                    == "on"
                }
        if seed >= 0:
            request["seed"] = int(seed)
        if stop:
            request["stop"] = [stop]
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

        started = time.perf_counter()
        response_body = _request(
            url=_endpoint_url(self.url, "/v1/chat/completions"),
            method="POST",
            body=body,
            timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            api_key=self._api_key,
            transport=self._transport,
        )
        elapsed = time.perf_counter() - started
        try:
            raw = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendError(
                "llama.cpp server returned an invalid chat-completion response."
            ) from exc
        if not isinstance(raw, dict):
            raise BackendError("llama.cpp server returned a non-object response.")
        try:
            response, thinking = _extract_response(raw)
        except BackendError as exc:
            message = str(exc).replace("llama-cpp-python", "llama.cpp server")
            raise BackendError(message) from None

        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        timings = raw.get("timings") if isinstance(raw.get("timings"), dict) else {}
        execution_index = self._execution_count
        self._execution_count += 1
        metrics = {
            "load_seconds": 0.0,
            "generation_seconds": elapsed,
            "cleanup_seconds": 0.0,
            "total_seconds": elapsed,
            "usage": usage,
            "server_timings": timings,
            "model_unloaded": False,
            "session": {
                "execution_index": execution_index,
                "model_reused": execution_index > 0,
                "unload_required": True,
                "remote": True,
            },
        }
        manifest = media.manifest()
        has_media = bool(media.items)
        media_diagnostics = {
            "schema_version": 1,
            "backend": "llama.cpp-server",
            "model": self.model,
            "handler": "server",
            "capabilities": {"vision": False, "audio": False, "video": False},
            "requested": manifest,
            "evaluated": {
                "media_count": 0,
                "image_count": 0,
                "audio_count": 0,
                "video_count": 0,
            },
            "mtmd": {
                "strict_pipeline": False,
                "completion_succeeded": True,
                "all_media_evaluated": not has_media,
                "verification": "unverified_remote" if has_media else "no_media",
            },
            "model_unloaded_after_response": False,
        }
        return LlamaCppResult(
            response=response,
            thinking=thinking,
            raw=raw,
            metrics=metrics,
            media_diagnostics=media_diagnostics,
        )

    def decide(
        self,
        *,
        question: str,
        context: str,
        answers: list[str],
        model_profile: dict[str, Any] | None = None,
        seed: int = -1,
        media: MediaBundle | None = None,
    ) -> LlamaCppDecisionResult:
        if self._closed:
            raise BackendError(
                "The llama.cpp server session has already been unloaded."
            )
        media = media or MediaBundle()
        if not isinstance(question, str) or not question.strip():
            raise InputNormalizationError("question must be a non-empty string.")
        if not isinstance(context, str):
            raise InputNormalizationError("context must be a string.")
        if not isinstance(answers, list) or not 2 <= len(answers) <= 26:
            raise InputNormalizationError(
                "answers must contain between 2 and 26 items."
            )
        if any(not isinstance(answer, str) or not answer.strip() for answer in answers):
            raise InputNormalizationError("answers must be non-empty strings.")
        if len(set(answers)) != len(answers):
            raise InputNormalizationError("answers must be unique.")

        try:
            from makoto_decision import Choices
        except ImportError as exc:
            raise BackendError(
                "makoto-decision is required for Llama.cpp decision sessions. "
                "Install the optional llama dependencies and restart ComfyUI."
            ) from exc

        try:
            choices = Choices.letters(*answers)
            token_to_answer: dict[int, str] = {}
            for choice in choices:
                token_id = self._decision_token_id(choice.target)
                if token_id in token_to_answer:
                    raise BackendError(
                        "Decision choice targets must map to distinct server token IDs."
                    )
                token_to_answer[token_id] = choice.value

            prompt_sections = [question]
            prompt_sections.extend(
                (
                    "Choices:\n"
                    + "\n".join(
                        f"{choice.target}: {choice.value}" for choice in choices
                    ),
                    "Respond with exactly one of: "
                    + ", ".join(choice.target for choice in choices),
                )
            )
            context_sections = [context] if context else []
            if media.items:
                context_sections.append(" ".join("<__media__>" for _ in media.items))
            context_sections.append("\n\n".join(prompt_sections))
            decision_prompt = "\n\n".join(context_sections)
            grammar = "root ::= " + " | ".join(
                f'"{choice.target}"' for choice in choices
            )
            template_request: dict[str, Any] = {
                "messages": [{"role": "user", "content": decision_prompt}]
            }
            if (
                model_profile is not None
                and model_profile["recommended_reasoning_mode"] != "auto"
            ):
                template_request["chat_template_kwargs"] = {
                    "enable_thinking": model_profile["recommended_reasoning_mode"]
                    == "on"
                }
            template_body = json.dumps(
                template_request, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            template_response = _request(
                url=_endpoint_url(self.url, "/apply-template"),
                method="POST",
                body=template_body,
                timeout_seconds=10.0,
                api_key=self._api_key,
                transport=self._transport,
            )
            try:
                template = json.loads(template_response.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BackendError(
                    "llama.cpp server returned an invalid decision template response."
                ) from exc
            prompt = template.get("prompt") if isinstance(template, dict) else None
            if not isinstance(prompt, str) or not prompt:
                raise BackendError(
                    "llama.cpp server did not return a formatted decision prompt."
                )

            request = {
                "prompt": prompt,
                "n_predict": 1,
                "temperature": 1.0,
                "top_k": 0,
                "top_p": 1.0,
                "min_p": 0.0,
                "typical_p": 1.0,
                "repeat_penalty": 1.0,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
                "dry_multiplier": 0.0,
                "xtc_probability": 0.0,
                "mirostat": 0,
                "n_probs": len(choices),
                "post_sampling_probs": True,
                "grammar": grammar,
            }
            if media.items:
                request["prompt"] = {
                    "prompt_string": prompt,
                    "multimodal_data": [
                        base64.b64encode(item.payload).decode("ascii")
                        for item in media.items
                    ],
                }
            if seed >= 0:
                request["seed"] = int(seed)
            if model_profile is not None:
                request.update(
                    temperature=model_profile["temperature"],
                    top_k=model_profile["top_k"],
                    top_p=model_profile["top_p"],
                    min_p=model_profile["min_p"],
                    repeat_penalty=model_profile["repeat_penalty"],
                    presence_penalty=model_profile["presence_penalty"],
                )
            started = time.perf_counter()
            response_body = _request(
                url=_endpoint_url(self.url, "/completion"),
                method="POST",
                body=json.dumps(
                    request, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8"),
                timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
                api_key=self._api_key,
                transport=self._transport,
            )
            elapsed = time.perf_counter() - started
            try:
                response = json.loads(response_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BackendError(
                    "llama.cpp server returned an invalid decision response."
                ) from exc
            if not isinstance(response, dict):
                raise BackendError(
                    "llama.cpp server returned a non-object decision response."
                )

            generated = response.get("content")
            if not isinstance(generated, str) or generated.strip() not in {
                choice.target for choice in choices
            }:
                raise BackendError(
                    "llama.cpp server did not generate a valid decision label."
                )

            probability_steps = response.get("probs")
            if probability_steps is None:
                probability_steps = response.get("completion_probabilities")
            if not isinstance(probability_steps, list) or len(probability_steps) != 1:
                raise BackendError(
                    "llama.cpp server decision response must contain one token "
                    "probability step."
                )
            top_probs = probability_steps[0]
            if isinstance(top_probs, dict):
                top_probs = top_probs.get("top_probs")
            if not isinstance(top_probs, list):
                raise BackendError(
                    "llama.cpp server decision response is missing top_probs."
                )

            probabilities = {answer: 0.0 for answer in answers}
            seen_token_ids: set[int] = set()
            for item in top_probs:
                if not isinstance(item, dict):
                    raise BackendError(
                        "llama.cpp server returned an invalid decision probability."
                    )
                token_id = item.get("id")
                probability = item.get("prob")
                if type(token_id) is not int or token_id not in token_to_answer:
                    raise BackendError(
                        "llama.cpp server returned a token outside the decision choices."
                    )
                if token_id in seen_token_ids:
                    raise BackendError(
                        "llama.cpp server returned a duplicate decision token."
                    )
                if (
                    isinstance(probability, bool)
                    or not isinstance(probability, (int, float))
                    or not math.isfinite(probability)
                    or not 0.0 <= probability <= 1.0
                ):
                    raise BackendError(
                        "llama.cpp server returned an invalid decision probability."
                    )
                seen_token_ids.add(token_id)
                probabilities[token_to_answer[token_id]] = float(probability)

            total = sum(probabilities.values())
            if total <= 0.0:
                raise BackendError(
                    "llama.cpp server returned no positive probability mass for "
                    "the decision choices."
                )
            probabilities = {
                answer: probability / total
                for answer, probability in probabilities.items()
            }
            selected = max(probabilities, key=probabilities.__getitem__)
            execution_index = self._execution_count
            self._execution_count += 1
            manifest = media.manifest()
            has_media = bool(media.items)
            return LlamaCppDecisionResult(
                selected=selected,
                probabilities=probabilities,
                metrics={
                    "decision_seconds": elapsed,
                    "server_timings": response.get("timings", {}),
                    "model_unloaded": False,
                    "session": {
                        "execution_index": execution_index,
                        "model_reused": execution_index > 0,
                        "unload_required": True,
                        "remote": True,
                    },
                },
                media_diagnostics={
                    "schema_version": 1,
                    "backend": "llama.cpp-server",
                    "model": self.model,
                    "handler": "server",
                    "capabilities": {
                        "vision": False,
                        "audio": False,
                        "video": False,
                    },
                    "requested": manifest,
                    "evaluated": {
                        "media_count": 0,
                        "image_count": 0,
                        "audio_count": 0,
                        "video_count": 0,
                    },
                    "mtmd": {
                        "strict_pipeline": False,
                        "completion_succeeded": True,
                        "all_media_evaluated": not has_media,
                        "verification": "unverified_remote"
                        if has_media
                        else "no_media",
                    },
                    "model_unloaded_after_response": False,
                },
            )
        except (BackendError, InputNormalizationError):
            raise
        except Exception as exc:
            raise BackendError(f"llama.cpp server decision failed: {exc}") from exc

    def _decision_token_id(self, target: str) -> int:
        cached = self._decision_token_ids.get(target)
        if cached is not None:
            return cached
        body = json.dumps(
            {"content": target, "add_special": False}, separators=(",", ":")
        ).encode("utf-8")
        response_body = _request(
            url=_endpoint_url(self.url, "/tokenize"),
            method="POST",
            body=body,
            timeout_seconds=10.0,
            api_key=self._api_key,
            transport=self._transport,
        )
        try:
            response = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendError(
                "llama.cpp server returned an invalid decision tokenization response."
            ) from exc
        tokens = response.get("tokens") if isinstance(response, dict) else None
        if (
            not isinstance(tokens, list)
            or len(tokens) != 1
            or type(tokens[0]) is not int
            or tokens[0] < 0
        ):
            raise BackendError(
                f"Decision choice target {target!r} must tokenize to exactly one "
                "valid server token."
            )
        self._decision_token_ids[target] = tokens[0]
        return tokens[0]

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            try:
                body = json.dumps({"model": self.model}, separators=(",", ":")).encode(
                    "utf-8"
                )
                response_body = _request(
                    url=_endpoint_url(self.url, "/models/unload"),
                    method="POST",
                    body=body,
                    timeout_seconds=30.0,
                    api_key=self._api_key,
                    transport=self._transport,
                )
                if response_body:
                    try:
                        response = json.loads(response_body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise BackendError(
                            "llama.cpp server returned an invalid model-unload response."
                        ) from exc
                    if not isinstance(response, dict):
                        raise BackendError(
                            "llama.cpp server returned an invalid model-unload response."
                        )
                    if response.get("success") is False or "error" in response:
                        raise BackendError(
                            "llama.cpp server rejected the model unload request."
                        )
            except Exception:
                # Prompt-end cleanup clears the registry before closing; retain failed
                # unloads so a later cleanup or explicit retry can try again.
                track_session(self)
                raise
            self._closed = True
            untrack_session(self)


class OwnedLlamaCppServerSession(LlamaCppServerSession):
    """A server session whose process lifetime is owned by this handle."""

    def __init__(
        self,
        *,
        url: str,
        model: str,
        api_key: str | None = None,
        process: _ClosableProcess,
        cleanup: Callable[[], None] | None = None,
        transport: Transport | None = None,
    ) -> None:
        if not callable(getattr(process, "close", None)):
            raise InputNormalizationError("process must provide a close() method.")
        self._process = process
        self._process_closed = False
        self._cleanup = cleanup
        super().__init__(url=url, model=model, api_key=api_key, transport=transport)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            try:
                if not self._process_closed:
                    self._process.close()
                    self._process_closed = True
                if self._cleanup is not None:
                    self._cleanup()
                    self._cleanup = None
            except Exception:
                track_session(self)
                raise
            self._closed = True
            untrack_session(self)


__all__ = [
    "LlamaCppServerSession",
    "OwnedLlamaCppServerSession",
    "list_server_models",
    "parse_models_response",
]
