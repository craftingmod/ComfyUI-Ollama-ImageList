from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

from backend.core import InputNormalizationError
from tests.backend.tensor_stub import solid_image
from tests.backend.test_extension_registration import install_comfy_api_stub


class FakeClip:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.tokenize_call = None
        self.generate_call = None

    def tokenize(self, prompt, **kwargs):
        self.tokenize_call = (prompt, kwargs)
        return {"tokens": [1, 2, 3]}

    def generate(self, tokens, **kwargs):
        self.generate_call = (tokens, kwargs)
        return [4, 5, 6]

    def decode(self, generated_ids):
        assert generated_ids == [4, 5, 6]
        return "decoded"


class Qwen3VLTokenizer:
    def tokenize_with_weights(self, text, images=None, **kwargs):
        return text, images, kwargs


class Gemma4Tokenizer:
    def tokenize_with_weights(self, text, images=None, **kwargs):
        return text, images, kwargs


class OldGemma4Tokenizer:
    def tokenize_with_weights(self, text, image=None, **kwargs):
        return text, image, kwargs


@pytest.fixture
def clip_module(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    monkeypatch.delitem(sys.modules, "backend.nodes.clip_generate", raising=False)
    return importlib.import_module("backend.nodes.clip_generate")


def execute_defaults(module, clip, **overrides):
    values = {
        "clip": [clip],
        "system": [""],
        "prompt": ["Describe the images."],
        "model_format": ["auto"],
        "max_length": [512],
        "sampling_mode": [
            {
                "sampling_mode": "on",
                "temperature": 0.7,
                "top_k": 64,
                "top_p": 0.95,
                "min_p": 0.05,
                "repetition_penalty": 1.05,
                "presence_penalty": 0.0,
                "seed": 7,
            }
        ],
        "images": None,
        "video": None,
        "audio": None,
        "thinking": [False],
        "use_default_template": [True],
    }
    values.update(overrides)
    return module.ClipImageListGenerateNode.execute(**values)


def test_qwen_system_role_and_image_list_use_one_generate_call(clip_module):
    clip = FakeClip(Qwen3VLTokenizer())
    result = execute_defaults(
        clip_module,
        clip,
        system=["Answer briefly {and accurately}."],
        images=[solid_image(2, 8, 8, 3, 0.1), solid_image(1, 12, 6, 3, 0.2)],
        thinking=[True],
    )

    assert result == ("decoded",)
    prompt, kwargs = clip.tokenize_call
    assert prompt == "Describe the images."
    assert len(kwargs["images"]) == 3
    assert all(image.shape[0] == 1 for image in kwargs["images"])
    assert kwargs["llama_template"].count("<|image_pad|>") == 3
    assert "<|im_start|>system\nAnswer briefly {{and accurately}}." in kwargs[
        "llama_template"
    ]
    assert kwargs["thinking"] is True
    assert kwargs["skip_template"] is False
    assert clip.generate_call[1]["seed"] == 7


def test_gemma4_named_images_supports_different_resolutions(clip_module):
    clip = FakeClip(Gemma4Tokenizer())
    execute_defaults(
        clip_module,
        clip,
        system=["Use the system role."],
        images=[solid_image(1, 8, 8, 3, 0.1), solid_image(1, 10, 6, 3, 0.2)],
    )

    _, kwargs = clip.tokenize_call
    assert len(kwargs["images"]) == 2
    assert "image" not in kwargs
    assert kwargs["llama_template"].count("<|image><|image|><image|>") == 2
    assert kwargs["llama_template"].startswith("<|turn>system\nUse the system role.")
    assert kwargs["llama_template"].endswith("<|channel>thought\n<channel|>")


def test_old_gemma4_rejects_heterogeneous_list_with_pr_link(clip_module):
    clip = FakeClip(OldGemma4Tokenizer())
    with pytest.raises(InputNormalizationError, match="pull/15450"):
        execute_defaults(
            clip_module,
            clip,
            images=[solid_image(1, 8, 8, 3, 0.1), solid_image(1, 10, 6, 3, 0.2)],
        )


def test_old_gemma4_combines_same_resolution_list(monkeypatch, clip_module):
    fake_torch = ModuleType("torch")

    def concatenate(images, dim):
        assert dim == 0
        assert len(images) == 2
        return solid_image(2, 8, 8, 3, 0.0)

    fake_torch.cat = concatenate
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    clip = FakeClip(OldGemma4Tokenizer())
    execute_defaults(
        clip_module,
        clip,
        images=[solid_image(1, 8, 8, 3, 0.1), solid_image(1, 8, 8, 3, 0.2)],
    )

    _, kwargs = clip.tokenize_call
    assert kwargs["image"].shape == (2, 8, 8, 3)
    assert "images" not in kwargs


def test_unknown_tokenizer_without_system_uses_official_default_path(clip_module):
    clip = FakeClip(object())
    execute_defaults(clip_module, clip)

    _, kwargs = clip.tokenize_call
    assert kwargs == {
        "skip_template": False,
        "min_length": 1,
        "thinking": False,
        "image": None,
        "video": None,
        "audio": None,
    }


def test_raw_prompt_mode_rejects_separate_system_prompt(clip_module):
    clip = FakeClip(Qwen3VLTokenizer())
    with pytest.raises(InputNormalizationError, match="system must be empty"):
        execute_defaults(
            clip_module,
            clip,
            system=["system"],
            use_default_template=[False],
        )
