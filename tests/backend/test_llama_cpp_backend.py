import base64

import pytest

from backend.backends.llama_cpp import LlamaCppBindings, run_chat
from backend.core import (
    BackendError,
    InputNormalizationError,
    normalize_audio,
    normalize_images,
    normalize_media,
)
from tests.backend.tensor_stub import silent_audio, solid_image


class FakeLlama:
    instances = []
    response = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    generation_error = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.completion_kwargs = None
        self.closed = False
        type(self).instances.append(self)

    def create_chat_completion(self, **kwargs):
        self.completion_kwargs = kwargs
        if type(self).generation_error is not None:
            raise type(self).generation_error
        return type(self).response

    def close(self):
        self.closed = True


class FakeHandler:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        type(self).instances.append(self)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeLlama.instances = []
    FakeLlama.response = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    FakeLlama.generation_error = None
    FakeHandler.instances = []


def make_bindings(**handlers):
    return LlamaCppBindings(llama_class=FakeLlama, handlers=handlers)


def gguf_files(tmp_path):
    model = tmp_path / "model.gguf"
    mmproj = tmp_path / "mmproj.gguf"
    model.write_bytes(b"model")
    mmproj.write_bytes(b"projector")
    return model, mmproj


def test_run_chat_sends_all_images_once_and_unloads_model(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_images(
        [solid_image(1, 2, 3, 3, 0.1), solid_image(1, 4, 1, 3, 0.9)]
    )

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="system",
        prompt="compare",
        media=bundle,
        gpu_layers="all",
        flash_attention="enabled",
        max_tokens=42,
        seed=7,
        stop="END",
        bindings=make_bindings(),
    )

    assert len(FakeLlama.instances) == 1
    instance = FakeLlama.instances[0]
    assert instance.kwargs["model_path"] == str(model.resolve())
    assert instance.kwargs["mmproj_path"] == str(mmproj.resolve())
    assert instance.kwargs["chat_handler_kwargs"] == {"verbose": False}
    assert instance.kwargs["n_gpu_layers"] == "all"
    assert instance.kwargs["flash_attn_type"] == 1
    assert instance.closed is True
    assert instance.completion_kwargs["max_tokens"] == 42
    assert instance.completion_kwargs["seed"] == 7
    assert instance.completion_kwargs["stop"] == ["END"]

    messages = instance.completion_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "system"}
    content = messages[1]["content"]
    assert content[0] == {"type": "text", "text": "compare"}
    data_uris = [part["image_url"]["url"] for part in content[1:]]
    assert len(data_uris) == 2
    assert all(uri.startswith("data:image/png;base64,") for uri in data_uris)
    assert [base64.b64decode(uri.split(",", 1)[1]) for uri in data_uris] == [
        item.payload for item in bundle.items
    ]
    assert result.response == "done"
    assert result.metrics["usage"]["total_tokens"] == 12
    assert result.metrics["model_unloaded"] is True


def test_run_chat_sends_audio_as_base64_pcm16_wav(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_audio(
        {"waveform": silent_audio(1, 1, 80), "sample_rate": 16_000}
    )

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="transcribe",
        media=bundle,
        bindings=make_bindings(),
    )

    content = FakeLlama.instances[0].completion_kwargs["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text", "input_audio"]
    audio = content[1]["input_audio"]
    assert audio["format"] == "wav"
    assert base64.b64decode(audio["data"]) == bundle.items[0].payload
    assert base64.b64decode(audio["data"]).startswith(b"RIFF")
    assert FakeLlama.instances[0].closed is True


def test_run_chat_preserves_image_then_audio_order_in_one_message(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_media(
        images=solid_image(1, 2, 3, 3, 0.5),
        audio={"waveform": silent_audio(1, 2, 160), "sample_rate": 16_000},
    )

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="system",
        prompt="analyze both",
        media=bundle,
        bindings=make_bindings(),
    )

    content = FakeLlama.instances[0].completion_kwargs["messages"][-1]["content"]
    assert [part["type"] for part in content] == [
        "text",
        "image_url",
        "input_audio",
    ]
    assert base64.b64decode(content[2]["input_audio"]["data"]) == bundle.items[1].payload


def test_specific_handler_is_created_and_owned_by_llama(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="gemma4",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        bindings=make_bindings(gemma4=FakeHandler),
    )

    handler = FakeHandler.instances[0]
    assert handler.kwargs == {"mmproj_path": str(mmproj.resolve()), "verbose": False}
    assert FakeLlama.instances[0].kwargs["chat_handler"] is handler
    assert FakeLlama.instances[0].closed is True


def test_qwen3_asr_handler_is_available_for_audio_models(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="qwen3_asr",
        system="",
        prompt="transcribe",
        media=normalize_audio(
            {"waveform": silent_audio(1, 1, 80), "sample_rate": 16_000}
        ),
        bindings=make_bindings(qwen3_asr=FakeHandler),
    )

    handler = FakeHandler.instances[0]
    assert handler.kwargs == {"mmproj_path": str(mmproj.resolve()), "verbose": False}
    assert FakeLlama.instances[0].kwargs["chat_handler"] is handler
    assert FakeLlama.instances[0].closed is True


def test_auto_handler_inherits_enabled_verbose_setting(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="describe",
        media=normalize_images(None),
        verbose=True,
        bindings=make_bindings(),
    )

    model_kwargs = FakeLlama.instances[0].kwargs
    assert model_kwargs["verbose"] is True
    assert model_kwargs["chat_handler_kwargs"] == {"verbose": True}


def test_generation_failure_still_closes_model(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.generation_error = RuntimeError("CUDA failure")

    with pytest.raises(BackendError, match="CUDA failure"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_images(None),
            bindings=make_bindings(),
        )

    assert FakeLlama.instances[0].closed is True


def test_images_require_mmproj_before_native_import(tmp_path):
    model, _ = gguf_files(tmp_path)

    with pytest.raises(InputNormalizationError, match="mmproj_path is required"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="describe",
            media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
            bindings=make_bindings(),
        )

    assert FakeLlama.instances == []


def test_audio_requires_mmproj_before_native_import(tmp_path):
    model, _ = gguf_files(tmp_path)

    with pytest.raises(InputNormalizationError, match="mmproj_path is required"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="transcribe",
            media=normalize_audio(
                {"waveform": silent_audio(1, 1, 80), "sample_rate": 16_000}
            ),
            bindings=make_bindings(),
        )

    assert FakeLlama.instances == []


def test_reasoning_tags_are_split_from_response(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>inspect details</think>final answer",
                }
            }
        ],
        "usage": {},
    }

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_images(None),
        bindings=make_bindings(),
    )

    assert result.thinking == "inspect details"
    assert result.response == "final answer"


@pytest.mark.parametrize(
    ("content", "expected_thinking", "expected_response"),
    [
        (
            "<|channel>thought\ninspect details\n<channel|>final answer",
            "inspect details",
            "final answer",
        ),
        ("<|channel>thought\npartial reasoning", "partial reasoning", ""),
    ],
)
def test_gemma4_thought_channel_is_split(tmp_path, content, expected_thinking, expected_response):
    model, _ = gguf_files(tmp_path)
    FakeLlama.response = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {},
    }

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_images(None),
        bindings=make_bindings(),
    )

    assert result.thinking == expected_thinking
    assert result.response == expected_response


def test_model_path_must_be_an_existing_gguf(tmp_path):
    invalid = tmp_path / "model.bin"
    invalid.write_bytes(b"model")

    with pytest.raises(InputNormalizationError, match="must be a GGUF"):
        run_chat(
            model_path=str(invalid),
            system="",
            prompt="hello",
            media=normalize_images(None),
            bindings=make_bindings(),
        )
