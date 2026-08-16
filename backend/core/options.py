from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import InputNormalizationError

OLLAMA_OPTION_NAMES = (
    "num_ctx",
    "num_predict",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "repeat_last_n",
    "seed",
    "stop",
    "draft_num_predict",
)


def build_ollama_options(values: Mapping[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for name in OLLAMA_OPTION_NAMES:
        if not values.get(f"use_{name}", False):
            continue
        value = values[name]
        options[name] = [str(value)] if name == "stop" else value
    return options


def parse_ollama_options_json(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InputNormalizationError(f"options_json is invalid JSON: {exc.msg}.") from exc
    if not isinstance(parsed, dict):
        raise InputNormalizationError("options_json must contain a JSON object.")
    return parsed


def resolve_ollama_options(
    options: Mapping[str, Any] | None,
    options_json: str,
) -> dict[str, Any]:
    if options is None:
        return parse_ollama_options_json(options_json)
    if not isinstance(options, Mapping):
        raise InputNormalizationError("options must be a dictionary.")

    resolved = dict(options)
    if any(not isinstance(name, str) for name in resolved):
        raise InputNormalizationError("options keys must be strings.")
    try:
        json.dumps(resolved, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise InputNormalizationError("options must contain JSON-serializable values.") from exc
    return resolved


__all__ = [
    "OLLAMA_OPTION_NAMES",
    "build_ollama_options",
    "parse_ollama_options_json",
    "resolve_ollama_options",
]
