import base64
import sys
from types import ModuleType

import pytest

import backend.backends.llama_cpp as llama_cpp_backend
from backend.backends.llama_cpp import LlamaCppBindings, run_chat, run_chat_sequential
from backend.core import (
    BackendError,
    InputNormalizationError,
    normalize_audio,
    normalize_images,
    normalize_media,
    normalize_video,
)
from tests.backend.tensor_stub import VideoInputStub, silent_audio, solid_image


NATIVE_EVENTS = []


class FakeMTMDHandler:
    is_support_vision = True
    is_support_audio = True
    is_support_video = False

    def _get_media_items(self):
        pass

    def _mtmd_tokenize(self):
        pass

    def _process_mtmd_prompt(self):
        pass

    def close(self):
        self.closed = True


class FakeLlama:
    instances = []
    metadata = {}
    response = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    generation_error = None
    nextn_layers = 0

    def __init__(self, **kwargs):
        NATIVE_EVENTS.append("target")
        self.kwargs = kwargs
        self.completion_kwargs = None
        self.completion_kwargs_history = []
        self.reset_count = 0
        self._native_speculative = None
        self.metadata = dict(type(self).metadata)
        self.closed = False
        self.close_count = 0
        if "chat_handler" in kwargs:
            self.chat_handler = kwargs["chat_handler"]
        elif "mmproj_path" in kwargs:
            self.chat_handler = FakeMTMDHandler()
            self.chat_handler.closed = False
        else:
            self.chat_handler = None
        type(self).instances.append(self)

    def create_chat_completion(self, **kwargs):
        self.completion_kwargs = kwargs
        self.completion_kwargs_history.append(kwargs)
        if type(self).generation_error is not None:
            raise type(self).generation_error
        return type(self).response

    def reset(self):
        self.reset_count += 1

    def n_layer_nextn(self):
        return type(self).nextn_layers

    def close(self):
        self.close_count += 1
        self.closed = True
        draft_model = self.kwargs.get("draft_model")
        if draft_model is not None:
            draft_model.close()
        if self.chat_handler is not None:
            close_handler = getattr(self.chat_handler, "close", None)
            if callable(close_handler):
                close_handler()


class FakeHandler(FakeMTMDHandler):
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        type(self).instances.append(self)

    def close(self):
        self.closed = True


class FakeVideoHandler(FakeHandler):
    is_support_video = True


class FakeJinjaFormatter:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.call_kwargs = None
        type(self).instances.append(self)

    def __call__(self, **kwargs):
        self.call_kwargs = kwargs
        return object()


class FakeDraftModel:
    instances = []

    def __init__(self, **kwargs):
        NATIVE_EVENTS.append("draft")
        self.kwargs = kwargs
        self.closed = False
        type(self).instances.append(self)

    @property
    def stats(self):
        if self.closed:
            raise RuntimeError("stats accessed after close")
        return {
            "draft_calls": 4,
            "accept_calls": 3,
            "drafted_tokens": 20,
            "accepted_tokens": 9,
            "acceptance_rate": 0.45,
            "mean_accepted_tokens": 2.25,
        }

    def close(self):
        self.closed = True


class FakeNGramDraft:
    instances = []

    def __init__(self, **kwargs):
        NATIVE_EVENTS.append("ngram")
        self.kwargs = kwargs
        self.closed = False
        type(self).instances.append(self)

    def close(self):
        self.closed = True


class FakeMTPDraft:
    instances = []

    def __init__(self, **kwargs):
        NATIVE_EVENTS.append("mtp")
        self.kwargs = kwargs
        self.closed = False
        self.stats_reads = 0
        self.is_mtp = True
        self.is_internal_mtp = kwargs["model_path"] is None
        type(self).instances.append(self)

    @property
    def stats(self):
        if self.closed:
            raise RuntimeError("stats accessed after close")
        self.stats_reads += 1
        if self.stats_reads == 1:
            return {
                "draft_calls": 5,
                "accept_calls": 4,
                "drafted_tokens": 20,
                "accepted_tokens": 10,
            }
        return {
            "draft_calls": 8,
            "accept_calls": 7,
            "drafted_tokens": 26,
            "accepted_tokens": 14,
        }

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fakes():
    NATIVE_EVENTS.clear()
    FakeLlama.instances = []
    FakeLlama.response = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    FakeLlama.generation_error = None
    FakeLlama.metadata = {}
    FakeLlama.nextn_layers = 0
    FakeHandler.instances = []
    FakeJinjaFormatter.instances = []
    FakeDraftModel.instances = []
    FakeNGramDraft.instances = []
    FakeMTPDraft.instances = []


def make_bindings(
    *,
    jinja_formatter_class=None,
    chat_formatter_to_handler=None,
    **handlers,
):
    return LlamaCppBindings(
        llama_class=FakeLlama,
        handlers=handlers,
        jinja_formatter_class=jinja_formatter_class,
        chat_formatter_to_handler=chat_formatter_to_handler,
    )


def gguf_files(tmp_path):
    model = tmp_path / "model.gguf"
    mmproj = tmp_path / "mmproj.gguf"
    model.write_bytes(b"model")
    mmproj.write_bytes(b"projector")
    return model, mmproj


def test_missing_optional_dependency_points_to_supported_fork(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)

    with pytest.raises(BackendError) as error:
        llama_cpp_backend._import_bindings()

    message = str(error.value)
    assert "JamePeng's multimodal llama-cpp-python fork" in message
    assert "LLAMA_CPP_PYTHON_VISION_INSTALL.md" in message
    assert "https://github.com/JamePeng/llama-cpp-python/releases/" in message


def test_missing_experimental_speculative_api_has_actionable_error(monkeypatch):
    llama_cpp_package = ModuleType("llama_cpp")
    llama_cpp_package.__path__ = []
    monkeypatch.setitem(sys.modules, "llama_cpp", llama_cpp_package)
    monkeypatch.setitem(sys.modules, "llama_cpp.llama_speculative", None)

    with pytest.raises(BackendError) as error:
        llama_cpp_backend._import_native_speculative_class()

    message = str(error.value)
    assert "not installed in the Python environment that runs ComfyUI" in message
    assert "LlamaNativeSpeculativeDecoding" in message
    assert "v0.3.46-native-speculative.1" in message
    assert "llama_cpp_python-0.3.46-speculative-cp313-cu132-win_amd64.whl" in message
    assert "No model was loaded" in message


def test_missing_ngram_speculative_api_fails_only_when_requested(monkeypatch):
    llama_cpp_package = ModuleType("llama_cpp")
    llama_cpp_package.__path__ = []
    monkeypatch.setitem(sys.modules, "llama_cpp", llama_cpp_package)
    monkeypatch.setitem(sys.modules, "llama_cpp.llama_speculative", None)

    with pytest.raises(BackendError) as error:
        llama_cpp_backend._import_ngram_speculative_class()

    message = str(error.value)
    assert "N-gram speculative decoding is unavailable" in message
    assert "speculative_mode set to off" in message
    assert "DFlash/DSpark support is not required" in message


def test_target_only_path_does_not_import_or_pass_speculative_binding(tmp_path, monkeypatch):
    model, _ = gguf_files(tmp_path)

    def unexpected_import():
        raise AssertionError("target-only generation imported the speculative API")

    monkeypatch.setattr(
        llama_cpp_backend,
        "_import_native_speculative_class",
        unexpected_import,
    )
    monkeypatch.setattr(
        llama_cpp_backend,
        "_import_ngram_speculative_class",
        unexpected_import,
    )

    run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_images(None),
        ngram_speculative={"speculative_mode": "off", "ignored": "value"},
        bindings=make_bindings(),
    )

    assert "draft_model" not in FakeLlama.instances[0].kwargs
    assert FakeDraftModel.instances == []
    assert FakeNGramDraft.instances == []


def test_text_only_generate_omits_selected_mmproj_but_forwards_thinking(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="gemma4",
        system="",
        prompt="hello",
        media=normalize_media(),
        thinking=True,
        reasoning_strength="xhigh",
        bindings=make_bindings(gemma4=FakeHandler),
    )

    assert "mmproj_path" not in FakeLlama.instances[0].kwargs
    assert FakeLlama.instances[0].kwargs["chat_handler_kwargs"] == {
        "verbose": False,
        "extra_template_arguments": {
            "enable_thinking": True,
            "force_reasoning": True,
            "reasoning_strength": "xhigh",
        },
    }
    assert FakeHandler.instances == []
    assert result.media_diagnostics["mmproj"] is None


def test_text_only_auto_reasoning_leaves_template_arguments_untouched(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.metadata = {"tokenizer.chat_template": "{{ enable_thinking }}"}

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        thinking=None,
        reasoning_strength="xhigh",
        reasoning_budget=512,
        bindings=make_bindings(
            jinja_formatter_class=FakeJinjaFormatter,
            chat_formatter_to_handler=lambda formatter: formatter,
        ),
    )

    assert FakeLlama.instances[0].kwargs["chat_handler_kwargs"] == {
        "verbose": False
    }
    assert FakeJinjaFormatter.instances == []
    assert result.metrics["configuration"]["thinking"] is None
    assert result.metrics["configuration"]["reasoning_strength"] == "auto"
    assert result.metrics["configuration"]["reasoning_budget"] == 0


def test_text_only_jinja_handler_receives_disabled_thinking_arguments(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.metadata = {"tokenizer.chat_template": "{{ enable_thinking }}"}
    configured_formatters = []

    def to_handler(formatter):
        configured_formatters.append(formatter)
        return formatter

    run_chat(
        model_path=str(model),
        system="",
        prompt="translate this",
        media=normalize_media(),
        thinking=False,
        reasoning_strength="xhigh",
        bindings=make_bindings(
            jinja_formatter_class=FakeJinjaFormatter,
            chat_formatter_to_handler=to_handler,
        ),
    )

    formatter = FakeJinjaFormatter.instances[0]
    assert formatter.kwargs["template"] == "{{ enable_thinking }}"
    configured_formatters[0](messages=[])
    assert formatter.call_kwargs["enable_thinking"] is False
    assert formatter.call_kwargs["force_reasoning"] is False
    assert "reasoning_strength" not in formatter.call_kwargs


def test_text_only_thinking_template_requires_configurable_jinja_api(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.metadata = {
        "tokenizer.chat_template": "{% if enable_thinking %}think{% endif %}"
    }

    with pytest.raises(BackendError, match="cannot pass thinking controls"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="translate this",
            media=normalize_media(),
            thinking=False,
            bindings=make_bindings(),
        )

    assert FakeLlama.instances[0].closed is True


def test_ngram_speculative_forwards_parameters_and_preserves_multimodal_request(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_images(solid_image(1, 2, 3, 3, 0.5))

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="system",
        prompt="repeat a template",
        media=bundle,
        ngram_speculative=llama_cpp_backend.normalize_ngram_speculative(
            {
                "speculative_mode": "ngram",
                "ngram_size": 4,
                "num_pred_tokens": 12,
                "ngram_mode": "k4v",
                "ngram_min_hits": 3,
                "ngram_max_entries_per_key": 0,
                "ngram_sync_check_tokens": 24,
            }
        ),
        bindings=make_bindings(),
        ngram_speculative_class=FakeNGramDraft,
    )

    assert NATIVE_EVENTS == ["ngram", "target"]
    draft = FakeNGramDraft.instances[0]
    assert draft.kwargs == {
        "ngram_size": 4,
        "num_pred_tokens": 12,
        "mode": "k4v",
        "min_hits": 3,
        "max_entries_per_key": None,
        "sync_check_tokens": 24,
    }
    instance = FakeLlama.instances[0]
    assert instance.kwargs["draft_model"] is draft
    assert instance.kwargs["mmproj_path"] == str(mmproj.resolve())
    content = instance.completion_kwargs["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text", "image_url"]
    assert instance.closed is True
    assert draft.closed is True
    assert result.metrics["ngram_speculative"] == {
        "speculative_mode": "ngram",
        "ngram_size": 4,
        "num_pred_tokens": 12,
        "ngram_min_hits": 3,
        "ngram_max_entries_per_key": None,
        "ngram_sync_check_tokens": 24,
        "ngram_mode": "k4v",
    }
    assert "speculative" not in result.metrics


def test_ngram_speculative_generation_failure_closes_target_and_draft(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.generation_error = RuntimeError("generation failed")

    with pytest.raises(BackendError, match="generation failed"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="repeat",
            media=normalize_images(None),
            ngram_speculative={
                "speculative_mode": "ngram",
                "ngram_size": 3,
                "num_pred_tokens": 10,
                "ngram_mode": "k",
                "ngram_min_hits": 2,
                "ngram_max_entries_per_key": 8,
                "ngram_sync_check_tokens": 16,
            },
            bindings=make_bindings(),
            ngram_speculative_class=FakeNGramDraft,
        )

    assert FakeLlama.instances[0].closed is True
    assert FakeNGramDraft.instances[0].closed is True


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"ngram_size": 0}, "ngram_size"),
        ({"num_pred_tokens": 33}, "num_pred_tokens"),
        ({"ngram_mode": "other"}, "ngram_mode"),
        ({"ngram_min_hits": 0}, "ngram_min_hits"),
        ({"ngram_max_entries_per_key": 1025}, "ngram_max_entries_per_key"),
        ({"ngram_sync_check_tokens": 0}, "ngram_sync_check_tokens"),
    ],
)
def test_ngram_speculative_parameters_are_validated(override, message):
    values = {
        "speculative_mode": "ngram",
        "ngram_size": 3,
        "num_pred_tokens": 10,
        "ngram_mode": "k",
        "ngram_min_hits": 2,
        "ngram_max_entries_per_key": 8,
        "ngram_sync_check_tokens": 16,
    }
    values.update(override)

    with pytest.raises(InputNormalizationError, match=message):
        llama_cpp_backend.normalize_ngram_speculative(values)


def test_native_and_ngram_speculative_modes_cannot_be_combined(tmp_path):
    model, _ = gguf_files(tmp_path)
    draft = tmp_path / "draft.gguf"
    draft.write_bytes(b"draft")

    with pytest.raises(InputNormalizationError, match="cannot be enabled together"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_images(None),
            draft_model_path=str(draft),
            ngram_speculative={
                "speculative_mode": "ngram",
                "ngram_size": 3,
                "num_pred_tokens": 10,
                "ngram_mode": "k",
                "ngram_min_hits": 2,
                "ngram_max_entries_per_key": 8,
                "ngram_sync_check_tokens": 16,
            },
            bindings=make_bindings(),
            speculative_class=FakeDraftModel,
            ngram_speculative_class=FakeNGramDraft,
        )

    assert FakeDraftModel.instances == []
    assert FakeNGramDraft.instances == []
    assert FakeLlama.instances == []


def test_native_speculative_draft_is_created_first_and_stats_are_copied(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    draft = tmp_path / "dflash.gguf"
    draft.write_bytes(b"draft")

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        system="",
        prompt="hello",
        media=normalize_images(None),
        gpu_layers="all",
        draft_model_path=str(draft),
        spec_type="draft-dflash",
        spec_n_max=15,
        spec_n_min=2,
        spec_p_min=0.25,
        bindings=make_bindings(),
        speculative_class=FakeDraftModel,
    )

    assert NATIVE_EVENTS == ["draft", "target"]
    draft_instance = FakeDraftModel.instances[0]
    assert draft_instance.kwargs == {
        "model_path": str(draft.resolve()),
        "spec_type": "draft-dflash",
        "n_gpu_layers": "all",
        "n_max": 15,
        "n_min": 2,
        "p_min": 0.25,
    }
    assert FakeLlama.instances[0].kwargs["draft_model"] is draft_instance
    assert "mmproj_path" not in FakeLlama.instances[0].kwargs
    assert "chat_handler_kwargs" in FakeLlama.instances[0].kwargs
    assert FakeLlama.instances[0].closed is True
    assert draft_instance.closed is True
    assert result.metrics["speculative"] == {
        "enabled": True,
        "implementation": "draft-dflash",
        "draft_model": "dflash.gguf",
        "n_max": 15,
        "n_min": 2,
        "p_min": 0.25,
        "stats": {
            "draft_calls": 4,
            "accept_calls": 3,
            "drafted_tokens": 20,
            "accepted_tokens": 9,
            "acceptance_rate": 0.45,
            "mean_accepted_tokens": 2.25,
        },
    }


def test_native_speculative_closes_draft_when_target_initialization_fails(tmp_path):
    model, _ = gguf_files(tmp_path)
    draft = tmp_path / "dflash.gguf"
    draft.write_bytes(b"draft")

    class FailingLlama:
        def __init__(self, **_kwargs):
            NATIVE_EVENTS.append("target")
            raise RuntimeError("target init failed")

    with pytest.raises(BackendError, match="target init failed"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_images(None),
            draft_model_path=str(draft),
            bindings=LlamaCppBindings(llama_class=FailingLlama, handlers={}),
            speculative_class=FakeDraftModel,
        )

    assert NATIVE_EVENTS == ["draft", "target"]
    assert FakeDraftModel.instances[0].closed is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"spec_type": "unknown"}, "spec_type"),
        ({"spec_n_max": 0}, "spec_n_max"),
        ({"spec_n_max": 2, "spec_n_min": 3}, "spec_n_min"),
        ({"spec_p_min": 1.1}, "spec_p_min"),
    ],
)
def test_native_speculative_parameters_are_validated_before_loading(
    tmp_path, overrides, message
):
    model, _ = gguf_files(tmp_path)
    draft = tmp_path / "draft.gguf"
    draft.write_bytes(b"draft")

    with pytest.raises(InputNormalizationError, match=message):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_images(None),
            draft_model_path=str(draft),
            bindings=make_bindings(),
            speculative_class=FakeDraftModel,
            **overrides,
        )

    assert FakeDraftModel.instances == []
    assert FakeLlama.instances == []


def test_gemma4_external_mtp_forwards_assistant_and_reports_request_delta(tmp_path):
    model, _ = gguf_files(tmp_path)
    assistant = tmp_path / "gemma4-assistant.gguf"
    assistant.write_bytes(b"assistant")
    FakeLlama.response["choices"][0]["finish_reason"] = "stop"

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        gpu_layers="all",
        draft_model_path=str(assistant),
        spec_type="draft-mtp",
        mtp_provider="external_gemma4",
        spec_n_max=2,
        spec_n_min=1,
        spec_p_min=0.2,
        verbose=True,
        bindings=make_bindings(),
        speculative_class=FakeMTPDraft,
    )

    assert NATIVE_EVENTS == ["mtp", "target"]
    decoder = FakeMTPDraft.instances[0]
    assert decoder.kwargs == {
        "model_path": str(assistant.resolve()),
        "spec_type": "draft-mtp",
        "n_gpu_layers": "all",
        "n_max": 2,
        "n_min": 1,
        "p_min": 0.2,
        "verbose": True,
    }
    target = FakeLlama.instances[0]
    assert target.kwargs["draft_model"] is decoder
    assert target.kwargs["n_seq_max"] == 1
    assert target.kwargs["native_context_reprefill"] is False
    assert decoder.stats_reads == 2
    assert target.closed is True
    assert decoder.closed is True
    assert result.metrics["speculative"] == {
        "enabled": True,
        "implementation": "draft-mtp",
        "draft_model": "gemma4-assistant.gguf",
        "n_max": 2,
        "n_min": 1,
        "p_min": 0.2,
        "stats": {
            "draft_calls": 3,
            "accept_calls": 3,
            "drafted_tokens": 6,
            "accepted_tokens": 4,
            "acceptance_rate": 4 / 6,
            "mean_accepted_per_call": 4 / 3,
        },
        "mtp_provider": "external_gemma4",
        "verbose": True,
        "n_layer_nextn": None,
        "completion_tokens": 2,
        "tokens_per_second": result.metrics["speculative"]["tokens_per_second"],
        "finish_reason": "stop",
    }
    assert result.metrics["speculative"]["tokens_per_second"] > 0


def test_qwen35_internal_mtp_passes_none_and_validates_embedded_nextn(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.nextn_layers = 2

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        gpu_layers="all",
        spec_type="draft-mtp",
        mtp_provider="internal_qwen35",
        spec_n_max=2,
        bindings=make_bindings(),
        speculative_class=FakeMTPDraft,
    )

    decoder = FakeMTPDraft.instances[0]
    assert decoder.kwargs["model_path"] is None
    assert decoder.kwargs["spec_type"] == "draft-mtp"
    assert decoder.is_internal_mtp is True
    assert result.metrics["speculative"]["mtp_provider"] == "internal_qwen35"
    assert result.metrics["speculative"]["draft_model"] is None
    assert result.metrics["speculative"]["n_layer_nextn"] == 2
    assert FakeLlama.instances[0].closed is True
    assert decoder.closed is True


def test_qwen35_internal_mtp_rejects_target_without_nextn_and_unloads(tmp_path):
    model, _ = gguf_files(tmp_path)

    with pytest.raises(BackendError, match="no usable embedded NextN/MTP layers"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_media(),
            gpu_layers="all",
            spec_type="draft-mtp",
            mtp_provider="internal_qwen35",
            bindings=make_bindings(),
            speculative_class=FakeMTPDraft,
        )

    assert FakeLlama.instances[0].closed is True
    assert FakeMTPDraft.instances[0].closed is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"mtp_provider": "internal_qwen35", "spec_type": "none"},
            "mtp_provider must be off",
        ),
        (
            {"mtp_provider": "internal_qwen35", "spec_type": "draft-dflash"},
            "spec_type must be draft-mtp",
        ),
        (
            {"mtp_provider": "off"},
            "draft-mtp requires mtp_provider",
        ),
        (
            {"mtp_provider": "external_gemma4"},
            "requires a matching gemma4-assistant GGUF",
        ),
        (
            {"mtp_provider": "internal_qwen35", "draft_model_path": "{draft}"},
            "leave draft_model unselected",
        ),
        (
            {"mtp_provider": "internal_qwen35", "gpu_layers": "cpu"},
            "requires gpu_layers=all",
        ),
        (
            {"mtp_provider": "internal_qwen35", "spec_n_max": 0},
            "spec_n_max",
        ),
        (
            {
                "mtp_provider": "internal_qwen35",
                "spec_n_max": 2,
                "spec_n_min": 3,
            },
            "spec_n_min",
        ),
        (
            {"mtp_provider": "internal_qwen35", "spec_p_min": 1.1},
            "spec_p_min",
        ),
    ],
)
def test_mtp_configuration_is_validated_before_loading(tmp_path, kwargs, message):
    model, _ = gguf_files(tmp_path)
    draft = tmp_path / "assistant.gguf"
    draft.write_bytes(b"draft")
    resolved_kwargs = {
        key: (str(draft) if value == "{draft}" else value)
        for key, value in kwargs.items()
    }

    call_kwargs = {
        "model_path": str(model),
        "system": "",
        "prompt": "hello",
        "media": normalize_media(),
        "gpu_layers": "all",
        "spec_type": "draft-mtp",
        "bindings": make_bindings(),
        "speculative_class": FakeMTPDraft,
        **resolved_kwargs,
    }
    with pytest.raises(InputNormalizationError, match=message):
        run_chat(**call_kwargs)

    assert FakeMTPDraft.instances == []
    assert FakeLlama.instances == []


def test_spec_type_none_runs_target_only_even_with_a_stale_draft_selection(tmp_path):
    model, _ = gguf_files(tmp_path)
    draft = tmp_path / "stale-draft.gguf"
    draft.write_bytes(b"draft")

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        draft_model_path=str(draft),
        spec_type="none",
        mtp_provider="off",
        bindings=make_bindings(),
        speculative_class=FakeDraftModel,
    )

    assert FakeDraftModel.instances == []
    assert "draft_model" not in FakeLlama.instances[0].kwargs
    assert "speculative" not in result.metrics


def test_mtp_rejects_media_before_native_loading(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    with pytest.raises(InputNormalizationError, match="text-only"):
        run_chat(
            model_path=str(model),
            mmproj_path=str(mmproj),
            system="",
            prompt="hello",
            media=normalize_images(solid_image(1, 2, 2, 3, 0.5)),
            gpu_layers="all",
            spec_type="draft-mtp",
            mtp_provider="internal_qwen35",
            bindings=make_bindings(),
            speculative_class=FakeMTPDraft,
        )

    assert FakeMTPDraft.instances == []
    assert FakeLlama.instances == []


def test_mtp_initialization_failure_does_not_fallback_to_target_only(tmp_path):
    model, _ = gguf_files(tmp_path)

    class FailingMTPDraft:
        def __init__(self, **_kwargs):
            raise RuntimeError("ABI mismatch")

    with pytest.raises(BackendError, match="speculative ABI v2"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_media(),
            gpu_layers="all",
            spec_type="draft-mtp",
            mtp_provider="internal_qwen35",
            bindings=make_bindings(),
            speculative_class=FailingMTPDraft,
        )

    assert FakeLlama.instances == []


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
        presence_penalty=1.5,
        seed=7,
        stop="END",
        bindings=make_bindings(),
    )

    assert len(FakeLlama.instances) == 1
    instance = FakeLlama.instances[0]
    assert instance.kwargs["model_path"] == str(model.resolve())
    assert instance.kwargs["mmproj_path"] == str(mmproj.resolve())
    assert instance.kwargs["chat_handler_kwargs"] == {
        "verbose": False,
        "extra_template_arguments": {
            "enable_thinking": False,
            "force_reasoning": False,
        },
    }
    assert instance.kwargs["n_gpu_layers"] == "all"
    assert instance.kwargs["flash_attn_type"] == 1
    assert instance.closed is True
    assert instance.completion_kwargs["max_tokens"] == 42
    assert instance.completion_kwargs["present_penalty"] == 1.5
    assert "presence_penalty" not in instance.completion_kwargs
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
    assert result.metrics["configuration"]["presence_penalty"] == 1.5
    assert result.media_diagnostics["capabilities"] == {
        "vision": True,
        "audio": True,
        "video": False,
    }
    assert result.media_diagnostics["evaluated"] == {
        "media_count": 2,
        "image_count": 2,
        "audio_count": 0,
        "video_count": 0,
    }
    assert result.media_diagnostics["mtmd"] == {
        "strict_pipeline": True,
        "completion_succeeded": True,
        "all_media_evaluated": True,
        "verification": "mtmd_evaluated",
    }
    assert result.media_diagnostics["model_unloaded_after_response"] is True


def test_auto_adapts_images_for_muse_glimmer_embedded_template(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_images(
        [solid_image(1, 2, 3, 3, 0.1), solid_image(1, 4, 1, 3, 0.9)]
    )
    FakeLlama.metadata = {"general.architecture": "muse-glimmer"}

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="compare",
        media=bundle,
        bindings=make_bindings(),
    )

    content = FakeLlama.instances[0].completion_kwargs["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text", "image", "image"]
    assert all(part["image"].startswith("data:image/png;base64,") for part in content[1:])


def test_explicit_generic_keeps_openai_image_parts_for_muse_glimmer(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    FakeLlama.metadata = {"general.architecture": "muse-glimmer"}

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="generic",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 2, 3, 3, 0.5)),
        bindings=make_bindings(generic=FakeHandler),
    )

    content = FakeLlama.instances[0].completion_kwargs["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text", "image_url"]


def test_run_chat_sends_audio_as_base64_pcm16_wav(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_audio(
        {"waveform": silent_audio(1, 1, 80), "sample_rate": 16_000}
    )

    result = run_chat(
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


def test_run_chat_sequential_reuses_model_resets_each_audio_and_unloads_once(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundles = [
        normalize_audio(
            {"waveform": silent_audio(1, 1, sample_count), "sample_rate": 16_000}
        )
        for sample_count in (80, 160)
    ]

    results = run_chat_sequential(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="transcribe independently",
        media_items=bundles,
        bindings=make_bindings(),
    )

    assert len(FakeLlama.instances) == 1
    instance = FakeLlama.instances[0]
    assert instance.reset_count == 2
    assert len(instance.completion_kwargs_history) == 2
    assert instance.closed is True
    assert instance.close_count == 1
    payloads = [
        base64.b64decode(call["messages"][-1]["content"][1]["input_audio"]["data"])
        for call in instance.completion_kwargs_history
    ]
    assert payloads == [bundle.items[0].payload for bundle in bundles]
    assert len(results) == 2
    assert all(result.response == "done" for result in results)
    assert all(
        result.metrics["sequential"]["context_reset_before_item"] is True
        for result in results
    )
    assert all(
        result.media_diagnostics["model_unloaded_after_sequence"] is True
        for result in results
    )


def test_run_chat_sequential_rejects_native_fork_without_reset_and_still_unloads(tmp_path):
    class NoResetLlama(FakeLlama):
        instances = []
        reset = None

    model, mmproj = gguf_files(tmp_path)
    bindings = LlamaCppBindings(llama_class=NoResetLlama, handlers={})

    with pytest.raises(BackendError, match=r"native-speculative.*Llama\.reset\(\)"):
        run_chat_sequential(
            model_path=str(model),
            mmproj_path=str(mmproj),
            handler="auto",
            system="",
            prompt="transcribe independently",
            media_items=[
                normalize_audio(
                    {"waveform": silent_audio(1, 1, 80), "sample_rate": 16_000}
                )
            ],
            bindings=bindings,
        )

    assert len(NoResetLlama.instances) == 1
    assert NoResetLlama.instances[0].closed is True
    assert NoResetLlama.instances[0].close_count == 1


def test_run_chat_sequential_uses_memory_clear_for_non_native_fork(tmp_path):
    class FakeContext:
        def __init__(self):
            self.clear_calls = []

        def memory_clear(self, clear_data):
            self.clear_calls.append(clear_data)

    class NonNativeLlama(FakeLlama):
        instances = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            del self._native_speculative
            self._ctx = FakeContext()
            self.n_tokens = 123

        def reset(self):
            raise AssertionError("non-native fallback must not call reset()")

    model, mmproj = gguf_files(tmp_path)
    bindings = LlamaCppBindings(llama_class=NonNativeLlama, handlers={})

    results = run_chat_sequential(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="transcribe independently",
        media_items=[
            normalize_audio(
                {"waveform": silent_audio(1, 1, count), "sample_rate": 16_000}
            )
            for count in (80, 160)
        ],
        bindings=bindings,
    )

    assert len(results) == 2
    assert len(NonNativeLlama.instances) == 1
    instance = NonNativeLlama.instances[0]
    assert instance._ctx.clear_calls == [True, True]
    assert instance.n_tokens == 0
    assert instance.close_count == 1


def test_run_chat_preserves_image_then_audio_order_in_one_message(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_media(
        images=solid_image(1, 2, 3, 3, 0.5),
        audio={"waveform": silent_audio(1, 2, 160), "sample_rate": 16_000},
    )

    result = run_chat(
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
    assert result.media_diagnostics["requested"]["image_count"] == 1
    assert result.media_diagnostics["requested"]["audio_count"] == 1
    assert result.media_diagnostics["evaluated"]["image_count"] == 1
    assert result.media_diagnostics["evaluated"]["audio_count"] == 1


def test_run_chat_sends_comfy_video_as_internal_video_data_uri(tmp_path):
    model, mmproj = gguf_files(tmp_path)
    bundle = normalize_video(VideoInputStub(b"fake-video-stream"))

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="generic",
        system="",
        prompt="describe the video",
        media=bundle,
        bindings=make_bindings(generic=FakeVideoHandler),
    )

    content = FakeLlama.instances[0].completion_kwargs["messages"][-1]["content"]
    assert [part["type"] for part in content] == ["text", "video"]
    video_uri = content[1]["video"]["url"]
    assert video_uri.startswith("data:video/mp4;base64,")
    assert base64.b64decode(video_uri.split(",", 1)[1]) == b"fake-video-stream"
    assert result.media_diagnostics["capabilities"]["video"] is True
    assert result.media_diagnostics["requested"]["video_count"] == 1
    assert result.media_diagnostics["evaluated"]["video_count"] == 1
    assert result.media_diagnostics["mtmd"]["all_media_evaluated"] is True


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
    assert handler.kwargs == {
        "mmproj_path": str(mmproj.resolve()),
        "verbose": False,
        "enable_thinking": False,
    }
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
    assert handler.kwargs == {
        "mmproj_path": str(mmproj.resolve()),
        "verbose": False,
        "extra_template_arguments": {
            "enable_thinking": False,
            "force_reasoning": False,
        },
    }
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
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        verbose=True,
        bindings=make_bindings(),
    )

    model_kwargs = FakeLlama.instances[0].kwargs
    assert model_kwargs["verbose"] is True
    assert model_kwargs["chat_handler_kwargs"] == {
        "verbose": True,
        "extra_template_arguments": {
            "enable_thinking": False,
            "force_reasoning": False,
        },
    }


def test_thinking_and_multimodal_overrides_reach_specific_handler(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="gemma4",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        thinking=True,
        n_batch=1120,
        override_n_ubatch=True,
        n_ubatch=1120,
        override_image_max_tokens=True,
        image_max_tokens=1120,
        bindings=make_bindings(gemma4=FakeHandler),
    )

    assert FakeHandler.instances[0].kwargs == {
        "mmproj_path": str(mmproj.resolve()),
        "verbose": False,
        "enable_thinking": True,
        "image_max_tokens": 1120,
    }
    assert FakeLlama.instances[0].kwargs["n_ubatch"] == 1120
    assert result.metrics["configuration"] == {
        "thinking": True,
        "reasoning_strength": "auto",
        "reasoning_budget": 0,
        "reasoning_budget_applied": False,
        "reasoning_budget_format": None,
        "n_ctx": 8192,
        "n_batch": 1120,
        "n_ubatch_override": 1120,
        "image_max_tokens_override": 1120,
        "presence_penalty": 0.0,
    }


def test_qwen3_vl_thinking_maps_to_force_reasoning(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="qwen3_vl",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        thinking=True,
        bindings=make_bindings(qwen3_vl=FakeHandler),
    )

    assert FakeHandler.instances[0].kwargs["force_reasoning"] is True
    assert "extra_template_arguments" not in FakeHandler.instances[0].kwargs


def test_auto_handler_receives_thinking_and_image_token_overrides(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        thinking=True,
        reasoning_strength="xhigh",
        n_batch=1120,
        override_n_ubatch=True,
        n_ubatch=1120,
        override_image_max_tokens=True,
        image_max_tokens=1120,
        bindings=make_bindings(),
    )

    assert FakeLlama.instances[0].kwargs["chat_handler_kwargs"] == {
        "verbose": False,
        "extra_template_arguments": {
            "enable_thinking": True,
            "force_reasoning": True,
            "reasoning_strength": "xhigh",
        },
        "image_max_tokens": 1120,
    }


def test_disabled_thinking_ignores_selected_reasoning_strength(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    result = run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        thinking=False,
        reasoning_strength="xhigh",
        bindings=make_bindings(),
    )

    template_arguments = FakeLlama.instances[0].kwargs["chat_handler_kwargs"][
        "extra_template_arguments"
    ]
    assert template_arguments == {
        "enable_thinking": False,
        "force_reasoning": False,
    }
    assert result.metrics["configuration"]["reasoning_strength"] == "auto"


def test_auto_reasoning_strength_is_not_forwarded_when_thinking_is_enabled(tmp_path):
    model, _ = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        thinking=True,
        reasoning_strength="auto",
        bindings=make_bindings(),
    )

    template_arguments = FakeLlama.instances[0].kwargs["chat_handler_kwargs"][
        "extra_template_arguments"
    ]
    assert template_arguments == {
        "enable_thinking": True,
        "force_reasoning": True,
    }


def test_qwen_reasoning_budget_is_forwarded_to_completion(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.metadata = {
        "tokenizer.chat_template": "<think>{{ messages }}</think>"
    }

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        thinking=True,
        reasoning_budget=256,
        bindings=make_bindings(),
    )

    completion_kwargs = FakeLlama.instances[0].completion_kwargs
    assert completion_kwargs["reasoning_budget"] == 256
    assert completion_kwargs["reasoning_start"] == "<think>"
    assert completion_kwargs["reasoning_end"] == "</think>"
    assert completion_kwargs["reasoning_start_in_prompt"] is True
    assert result.metrics["configuration"]["reasoning_budget"] == 256
    assert result.metrics["configuration"]["reasoning_budget_applied"] is True
    assert result.metrics["configuration"]["reasoning_budget_format"] == "think_tags"


def test_gemma_reasoning_budget_uses_channel_markers(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.metadata = {
        "tokenizer.chat_template": "<|channel>analysis<channel|>{{ messages }}"
    }

    run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        thinking=True,
        reasoning_budget=128,
        bindings=make_bindings(),
    )

    completion_kwargs = FakeLlama.instances[0].completion_kwargs
    assert completion_kwargs["reasoning_budget"] == 128
    assert completion_kwargs["reasoning_start"] == "<|channel>"
    assert completion_kwargs["reasoning_end"] == "<channel|>"
    assert completion_kwargs["reasoning_start_in_prompt"] is False


def test_zero_or_disabled_reasoning_budget_is_not_forwarded(tmp_path):
    model, _ = gguf_files(tmp_path)

    result = run_chat(
        model_path=str(model),
        system="",
        prompt="hello",
        media=normalize_media(),
        thinking=False,
        reasoning_budget=512,
        bindings=make_bindings(),
    )

    assert "reasoning_budget" not in FakeLlama.instances[0].completion_kwargs
    assert result.metrics["configuration"]["reasoning_budget"] == 0
    assert result.metrics["configuration"]["reasoning_budget_applied"] is False


def test_positive_reasoning_budget_rejects_unknown_template_and_unloads(tmp_path):
    model, _ = gguf_files(tmp_path)
    FakeLlama.metadata = {"tokenizer.chat_template": "{{ messages }}"}

    with pytest.raises(InputNormalizationError, match="supported reasoning format"):
        run_chat(
            model_path=str(model),
            system="",
            prompt="hello",
            media=normalize_media(),
            thinking=True,
            reasoning_budget=256,
            bindings=make_bindings(),
        )

    assert FakeLlama.instances[0].closed is True


def test_disabled_overrides_do_not_pass_integer_values(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    run_chat(
        model_path=str(model),
        mmproj_path=str(mmproj),
        handler="auto",
        system="",
        prompt="describe",
        media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
        n_ubatch=2048,
        image_max_tokens=2048,
        bindings=make_bindings(),
    )

    model_kwargs = FakeLlama.instances[0].kwargs
    assert "n_ubatch" not in model_kwargs
    assert "image_max_tokens" not in model_kwargs["chat_handler_kwargs"]


def test_image_token_override_rejects_unsafe_physical_batch(tmp_path):
    model, mmproj = gguf_files(tmp_path)

    with pytest.raises(InputNormalizationError, match="effective n_ubatch"):
        run_chat(
            model_path=str(model),
            mmproj_path=str(mmproj),
            handler="auto",
            system="",
            prompt="describe",
            media=normalize_images(solid_image(1, 1, 1, 3, 0.5)),
            n_batch=1120,
            override_image_max_tokens=True,
            image_max_tokens=1120,
            bindings=make_bindings(),
        )

    assert FakeLlama.instances == []


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


@pytest.mark.parametrize(
    "content",
    [
        "<think>inspect details</think>final answer",
        "inspect details</think>final answer",
    ],
)
def test_reasoning_tags_are_split_from_response(tmp_path, content):
    model, _ = gguf_files(tmp_path)
    FakeLlama.response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
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
