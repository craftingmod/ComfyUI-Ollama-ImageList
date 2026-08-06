import pytest

from backend.core import (
    OLLAMA_OPTION_NAMES,
    InputNormalizationError,
    build_ollama_options,
    resolve_ollama_options,
)


def option_values() -> dict:
    values = {}
    for index, name in enumerate(OLLAMA_OPTION_NAMES):
        values[f"use_{name}"] = False
        values[name] = index
    return values


def test_only_enabled_options_are_emitted_in_documented_priority_order():
    values = option_values()
    values.update(
        use_num_ctx=True,
        num_ctx=32768,
        use_top_p=True,
        top_p=0.85,
        use_seed=True,
        seed=42,
    )

    assert build_ollama_options(values) == {
        "num_ctx": 32768,
        "top_p": 0.85,
        "seed": 42,
    }


def test_stop_string_is_converted_to_the_ollama_api_array_shape():
    values = option_values()
    values.update(use_stop=True, stop="user:")

    assert build_ollama_options(values) == {"stop": ["user:"]}


def test_no_enabled_options_produces_an_empty_dict():
    assert build_ollama_options(option_values()) == {}


def test_resolve_options_uses_json_only_when_dict_is_absent():
    assert resolve_ollama_options(None, '{"temperature":0.8}') == {"temperature": 0.8}
    assert resolve_ollama_options({}, '{"temperature":0.8}') == {}


def test_resolve_options_rejects_non_dictionary_values():
    with pytest.raises(InputNormalizationError, match="must be a dictionary"):
        resolve_ollama_options(["temperature"], "")
