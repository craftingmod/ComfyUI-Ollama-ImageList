import asyncio
import importlib
import json
import os
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from backend.core import BackendError, InputNormalizationError
from tests.backend.tensor_stub import VideoInputStub, silent_audio, solid_image


@dataclass(frozen=True)
class Field:
    direction: str
    data_type: str
    name: str
    options: dict

    @property
    def id(self) -> str:
        return self.name


class FieldType:
    data_type = ""

    @classmethod
    def Input(cls, name, **options):
        return Field("input", cls.data_type, name, options)

    @classmethod
    def Output(cls, name, **options):
        return Field("output", cls.data_type, name, options)


def field_type(name):
    return type(name.title(), (FieldType,), {"data_type": name})


class Custom:
    def __init__(self, name):
        self.data_type = name

    def Input(self, name, **options):
        return Field("input", self.data_type, name, options)

    def Output(self, name, **options):
        return Field("output", self.data_type, name, options)


class Schema:
    def __init__(self, **values):
        self.__dict__.update(values)


class ComfyNode:
    pass


class ComfyExtension:
    pass


class Caching:
    class CacheProvider:
        pass

    providers = []

    async def register_provider(self, provider):
        self.providers.append(provider)


class ComfyAPI:
    def __init__(self):
        self.caching = Caching()


class NodeOutput(tuple):
    def __new__(cls, *values):
        return super().__new__(cls, values)


class DynamicCombo:
    @dataclass(frozen=True)
    class Option:
        key: str
        inputs: list

    @classmethod
    def Input(cls, name, **options):
        return Field("input", "dynamic_combo", name, options)


class Routes:
    def __init__(self):
        self.handlers = {}
        self.methods = {}

    def _register(self, method, path):
        def register(handler):
            self.handlers[path] = handler
            self.methods[(method, path)] = handler
            return handler

        return register

    def post(self, path):
        return self._register("POST", path)

    def get(self, path):
        return self._register("GET", path)


def install_comfy_api_stub(monkeypatch):
    io = SimpleNamespace(
        Audio=field_type("audio"),
        Boolean=field_type("boolean"),
        Combo=field_type("combo"),
        Clip=field_type("clip"),
        ComfyNode=ComfyNode,
        Custom=Custom,
        Float=field_type("float"),
        Image=field_type("image"),
        Int=field_type("int"),
        DynamicCombo=DynamicCombo,
        NodeOutput=NodeOutput,
        Schema=Schema,
        String=field_type("string"),
        Video=field_type("video"),
    )
    comfy_api = ModuleType("comfy_api")
    versioned_api = ModuleType("comfy_api.v0_0_2")
    versioned_api.ComfyExtension = ComfyExtension
    versioned_api.io = io
    comfy_api.v0_0_2 = versioned_api
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_api)
    monkeypatch.setitem(sys.modules, "comfy_api.v0_0_2", versioned_api)
    latest_api = ModuleType("comfy_api.latest")
    latest_api.Caching = Caching
    latest_api.ComfyAPI = ComfyAPI
    latest_api.ComfyExtension = ComfyExtension
    latest_api.io = io
    comfy_api.latest = latest_api
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest_api)

    folder_paths = ModuleType("folder_paths")
    folder_paths.models_dir = "C:/ComfyUI/models"
    folder_paths.folder_names_and_paths = {
        "LLM": (["D:/SharedModels/LLM"], set()),
    }
    folder_paths.get_filename_list = lambda _folder_name: [
        "external/model-a.gguf",
        "local/model-b.gguf",
        "external/mmproj-model-a-f16.gguf",
        "external/mtp-model-a.gguf",
    ]

    def get_full_path_or_raise(_folder_name, filename):
        if filename.startswith("external/"):
            return f"D:/SharedModels/LLM/{filename}"
        return f"C:/ComfyUI/models/LLM/{filename}"

    folder_paths.get_full_path_or_raise = get_full_path_or_raise
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)

    routes = Routes()
    server = ModuleType("server")
    server.PromptServer = SimpleNamespace(instance=SimpleNamespace(routes=routes))
    monkeypatch.setitem(sys.modules, "server", server)
    return routes


def test_extension_registers_v3_node_schemas_and_models_route(monkeypatch):
    routes = install_comfy_api_stub(monkeypatch)
    for module_name in tuple(sys.modules):
        if module_name in {
            "backend.extension",
            "backend.routes",
        } or module_name.startswith("backend.nodes"):
            monkeypatch.delitem(sys.modules, module_name)

    extension_module = importlib.import_module("backend.extension")
    extension = asyncio.run(extension_module.comfy_entrypoint())
    asyncio.run(extension.on_load())
    assert len(Caching.providers) == 1
    cleanup_provider = Caching.providers[0]
    assert cleanup_provider.should_cache(None) is False

    class TrackedSession:
        closed = False

        def close(self):
            self.closed = True

    tracked_session = TrackedSession()
    importlib.import_module("backend.llama_cpp_session_cleanup").track_session(
        tracked_session
    )
    cleanup_provider.on_prompt_end("interrupted-prompt")
    assert tracked_session.closed is True

    node_classes = asyncio.run(extension.get_node_list())
    schemas = [node_class.define_schema() for node_class in node_classes]

    assert isinstance(extension, ComfyExtension)
    assert [schema.node_id for schema in schemas] == [
        "OllamaImageList_Connectivity",
        "OllamaImageList_Options",
        "OllamaImageList_Generate",
        "OllamaImageList_MiniMaxSystemPromptPreset",
        "OllamaImageList_JinjaChatTemplatePreset",
        "OllamaImageList_LlamaCppSamplingPreset",
        "OllamaImageList_LlamaCppGemma4RuntimePreset",
        "OllamaImageList_LlamaCppNGramSpeculativePreset",
        "OllamaImageList_LlamaCppModelProfile",
        "OllamaImageList_LlamaCppHardwareRuntimeProfile",
        "OllamaImageList_LlamaCppReasoningConfig",
        "OllamaImageList_LlamaCppNGramSpeculativeConfig",
        "OllamaImageList_LlamaCppNativeSpeculativeConfig",
        "OllamaImageList_LlamaCppCreateSession",
        "OllamaImageList_LlamaCppCreateRuntimeSession",
        "OllamaImageList_LlamaCppConnectSession",
        "OllamaImageList_LlamaCppCreateQuestionFromInput",
        "OllamaImageList_LlamaCppDecideSession",
        "OllamaImageList_LlamaCppSessionGenerate",
        "OllamaImageList_LlamaCppUnloadSession",
        "OllamaImageList_LlamaCppProfiledGenerate",
        "OllamaImageList_LlamaCppSequentialGenerate",
        "OllamaImageList_LlamaCppSessionGenerateSequential",
        "OllamaImageList_LlamaCppGenerate",
        "OllamaImageList_LlamaCppMediaDiagnostics",
        "OllamaImageList_MuseGlimmerResponseParser",
        "OllamaImageList_CLIPGenerateText",
    ]
    assert [schema.display_name for schema in schemas] == [
        "Ollama Connectivity (images)",
        "Ollama Options (images)",
        "Ollama Generate (with images)",
        "MiniMax System Prompt Preset",
        "Jinja Chat Template Preset",
        "[llama.cpp] Sampling Preset",
        "[llama.cpp] Gemma 4 Runtime Preset",
        "[llama.cpp] N-gram Speculative Preset",
        "[llama.cpp] Model Profile",
        "[llama.cpp] Hardware Runtime Profile",
        "[llama.cpp] Thinking / Reasoning Profile",
        "[llama.cpp] N-gram Speculative Config",
        "[llama.cpp] Native Speculative Profile",
        "[llama.cpp] Create Native Session",
        "[llama.cpp] Create Runtime Session",
        "[llama.cpp] Connect Session",
        "[llama.cpp] Create Question From Input",
        "[llama.cpp] Decide (Session)",
        "[llama.cpp] Generate (Session)",
        "[llama.cpp] Unload Session",
        "[llama.cpp] Generate",
        "[llama.cpp] Sequential Generate",
        "[llama.cpp] Generate (Sequential)",
        "[llama.cpp] Generate (Multimodal)",
        "[llama.cpp] Media Diagnostics",
        "Muse Glimmer Response Parser",
        "CLIP Text Encode (Multimodal)",
    ]
    assert [schema.category for schema in schemas] == [
        "Ollama/images",
        "Ollama/images",
        "Ollama/images",
        "Ollama/preset",
        "Ollama/preset",
        "llama_cpp/legacy",
        "llama_cpp/legacy",
        "llama_cpp/legacy",
        "llama_cpp/profile",
        "llama_cpp/profile",
        "llama_cpp/profile",
        "llama_cpp/compact",
        "llama_cpp/profile",
        "llama_cpp/session",
        "llama_cpp/session",
        "llama_cpp/session",
        "llama_cpp/decision",
        "llama_cpp/decision",
        "llama_cpp/generate",
        "llama_cpp/session",
        "llama_cpp/compact",
        "llama_cpp/compact",
        "llama_cpp/generate",
        "llama_cpp/legacy",
        "llama_cpp/utils",
        "llama_cpp/utils",
        "model/conditioning/multimodal",
    ]
    assert routes.handlers.keys() == {
        "/ollama_image_list/models",
        "/ollama_image_list/llama_cpp/models",
        "/ollama_image_list/llama_cpp/runtime",
        "/ollama_image_list/llama_cpp/runtime/restart",
        "/ollama_image_list/llama_cpp/runtime/download",
    }
    assert (
        "GET",
        "/ollama_image_list/llama_cpp/runtime",
    ) in routes.methods
    assert (
        "POST",
        "/ollama_image_list/llama_cpp/runtime/restart",
    ) in routes.methods
    assert (
        "POST",
        "/ollama_image_list/llama_cpp/runtime/download",
    ) in routes.methods

    registered = {
        schema.node_id: (node_class, schema)
        for node_class, schema in zip(node_classes, schemas, strict=True)
    }
    hidden_legacy_ids = {
        "OllamaImageList_LlamaCppSamplingPreset",
        "OllamaImageList_LlamaCppGemma4RuntimePreset",
        "OllamaImageList_LlamaCppNGramSpeculativePreset",
        "OllamaImageList_LlamaCppGenerate",
    }
    assert {
        schema.node_id for schema in schemas if getattr(schema, "is_dev_only", False)
    } == hidden_legacy_ids
    deprecated_compact_ids = {
        "OllamaImageList_LlamaCppNGramSpeculativeConfig",
        "OllamaImageList_LlamaCppProfiledGenerate",
        "OllamaImageList_LlamaCppSequentialGenerate",
    }
    assert {
        schema.node_id for schema in schemas if schema.category == "llama_cpp/compact"
    } == deprecated_compact_ids
    assert {
        schema.node_id for schema in schemas if getattr(schema, "is_deprecated", False)
    } >= deprecated_compact_ids

    minimax_class, minimax_schema = registered[
        "OllamaImageList_MiniMaxSystemPromptPreset"
    ]
    assert [(field.name, field.data_type) for field in minimax_schema.inputs] == [
        ("type", "combo"),
        ("enum_string", "string"),
    ]
    assert minimax_schema.inputs[0].options["options"] == [
        "I2V",
        "FL2V",
        "FL2V_LOOP",
        "T2V",
        "R2V",
        "R2I",
        "R2A",
        "L2V",
    ]
    assert minimax_schema.inputs[1].options["optional"] is True
    assert minimax_schema.inputs[1].options["force_input"] is True
    assert [(field.name, field.data_type) for field in minimax_schema.outputs] == [
        ("system_prompt", "string"),
    ]
    minimax_module = importlib.import_module("backend.nodes.minimax_prompt")
    base_prompt = minimax_module.BASE_PROMPT_PATH.read_text(encoding="utf-8").rstrip(
        "\r\n"
    )
    for prompt_type in ("I2V", "FL2V", "FL2V_LOOP", "T2V", "L2V"):
        type_prompt = (
            (minimax_module.PRESETS_DIRECTORY / f"PROMPT_{prompt_type}.md")
            .read_text(encoding="utf-8")
            .lstrip("\r\n")
        )
        assert minimax_class.execute(prompt_type) == (
            f"{base_prompt}\n\n{type_prompt}",
        )
    reference_base_prompt = minimax_module.REFERENCE_BASE_PROMPT_PATH.read_text(
        encoding="utf-8"
    ).rstrip("\r\n")
    for prompt_type in ("R2V", "R2I", "R2A"):
        type_prompt = (
            (minimax_module.PRESETS_DIRECTORY / f"PROMPT_{prompt_type}.md")
            .read_text(encoding="utf-8")
            .lstrip("\r\n")
        )
        assert minimax_class.execute(prompt_type) == (
            f"{reference_base_prompt}\n\n{type_prompt}",
        )
    assert minimax_class.execute("I2V", "R2A") == minimax_class.execute("R2A")
    with pytest.raises(
        ValueError,
        match="Unknown MiniMax prompt preset 'invalid'.*I2V.*R2A.*L2V",
    ):
        minimax_class.execute("I2V", "invalid")

    jinja_class, jinja_schema = registered["OllamaImageList_JinjaChatTemplatePreset"]
    assert [(field.name, field.data_type) for field in jinja_schema.inputs] == [
        ("template", "combo"),
    ]
    assert jinja_schema.inputs[0].options["options"] == [
        "qwen_fixed",
    ]
    assert [(field.name, field.data_type) for field in jinja_schema.outputs] == [
        ("chat_template", "string"),
    ]
    jinja_module = importlib.import_module("backend.nodes.jinja_chat_template")
    qwen_fixed_text = (jinja_module.PRESETS_DIRECTORY / "qwen_fixed.jinja").read_text(
        encoding="utf-8"
    )
    assert jinja_class.execute("qwen_fixed.jinja") == (qwen_fixed_text,)
    assert jinja_class.execute("qwen_fixed") == (qwen_fixed_text,)
    with pytest.raises(
        ValueError,
        match="Unknown Jinja chat template preset 'invalid'.*qwen_fixed.jinja",
    ):
        jinja_class.execute("invalid")
    with pytest.raises(
        ValueError,
        match="Unknown Jinja chat template preset 'qwen_fixed.md'.*qwen_fixed.jinja",
    ):
        jinja_class.execute("qwen_fixed.md")

    muse_class, muse_schema = registered["OllamaImageList_MuseGlimmerResponseParser"]
    assert [(field.name, field.data_type) for field in muse_schema.inputs] == [
        ("muse_response", "string"),
    ]
    assert muse_schema.inputs[0].options["force_input"] is True
    assert [(field.name, field.data_type) for field in muse_schema.outputs] == [
        ("response", "string"),
        ("thinking", "string"),
        ("raw", "string"),
        ("valid", "boolean"),
    ]
    assert muse_class.execute(
        " to=self<|message|>Think<|eom|>"
        "<|start|>assistant to=user<|message|>Answer<|eot|>"
    ) == ("Answer", "Think", "", True)

    clip_schema = registered["OllamaImageList_CLIPGenerateText"][1]
    assert clip_schema.is_input_list is True
    clip_inputs = {field.name: field for field in clip_schema.inputs}
    assert [field.name for field in clip_schema.inputs] == [
        "clip",
        "system",
        "prompt",
        "images",
        "video",
        "audio",
        "model_format",
        "max_length",
        "sampling_mode",
        "thinking",
        "use_default_template",
    ]
    assert clip_inputs["clip"].data_type == "clip"
    assert clip_inputs["images"].options["optional"] is True
    assert clip_inputs["video"].data_type == "image"
    assert clip_inputs["model_format"].options["options"] == [
        "auto",
        "qwen3_vl",
        "qwen3_5",
        "gemma4",
    ]
    assert clip_inputs["sampling_mode"].data_type == "dynamic_combo"
    sampling_on = clip_inputs["sampling_mode"].options["options"][0]
    sampling_seed = next(field for field in sampling_on.inputs if field.name == "seed")
    assert sampling_seed.options["control_after_generate"] is True
    assert clip_inputs["use_default_template"].options["advanced"] is True
    assert [field.name for field in clip_schema.outputs] == ["generated_text"]

    connectivity_class, connectivity_schema = registered["OllamaImageList_Connectivity"]
    connectivity_inputs = connectivity_schema.inputs
    assert [(field.name, field.data_type) for field in connectivity_inputs] == [
        ("url", "string"),
        ("available_models", "combo"),
        ("model", "string"),
    ]
    assert connectivity_inputs[1].options["options"] == []
    assert [field.name for field in connectivity_schema.outputs] == ["url", "model"]
    assert connectivity_class.validate_inputs("arbitrary:model") is True
    assert connectivity_class.execute(
        "http://127.0.0.1:11434", "arbitrary:model", "manual:model"
    ) == ("http://127.0.0.1:11434", "manual:model")

    options_class, options_schema = registered["OllamaImageList_Options"]
    option_names = [
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
    ]
    assert [field.name for field in options_schema.inputs] == [
        name
        for option_name in option_names
        for name in (f"use_{option_name}", option_name)
    ]
    assert [field.data_type for field in options_schema.outputs] == [
        "DICT",
        "string",
    ]
    assert [field.name for field in options_schema.outputs] == [
        "options",
        "options_json",
    ]
    assert [field.options["display_name"] for field in options_schema.outputs] == [
        "options",
        "options_json",
    ]
    option_values = {
        field.name: field.options["default"] for field in options_schema.inputs
    }
    option_values.update(
        use_num_ctx=True,
        num_ctx=8192,
        use_temperature=True,
        temperature=0.2,
        use_stop=True,
        stop="END",
        top_k=5,
    )
    options_dict, options_json = options_class.execute(**option_values)
    assert json.loads(options_json) == {
        "num_ctx": 8192,
        "temperature": 0.2,
        "stop": ["END"],
    }
    assert options_dict == {
        "num_ctx": 8192,
        "temperature": 0.2,
        "stop": ["END"],
    }

    generate_schema = registered["OllamaImageList_Generate"][1]
    assert generate_schema.is_input_list is True
    generate_inputs = {field.name: field for field in generate_schema.inputs}
    assert generate_inputs["options"].data_type == "DICT"
    assert generate_inputs["options"].options["optional"] is True
    assert generate_inputs["options_json"].data_type == "string"
    assert generate_inputs["options_json"].options["default"] == ""
    assert generate_inputs["options_json"].options["advanced"] is True
    generate_input_names = [field.name for field in generate_schema.inputs]
    assert "images" in generate_input_names
    assert "media" not in generate_input_names
    assert "audio" not in generate_input_names
    assert "audio_transport" not in generate_input_names
    assert generate_input_names.index("options") < generate_input_names.index(
        "options_json"
    )
    assert [field.name for field in generate_schema.outputs] == [
        "response",
        "thinking",
        "raw_json",
        "metrics_json",
        "image_manifest_json",
    ]
    assert generate_schema.outputs[-1].options["display_name"] == "image manifest"
    generate_module = importlib.import_module("backend.nodes.ollama_generate")
    image_item = SimpleNamespace(
        payload=b"png",
        manifest=lambda: {
            "kind": "image",
            "index": 0,
            "mime_type": "image/png",
            "byte_size": 3,
        },
    )
    image_manifest = generate_module._image_manifest(
        SimpleNamespace(items=(image_item,)),
        {
            "model": "gemma3",
            "audio_transport": "disabled",
            "media": {"audio_count": 0},
        },
    )
    assert image_manifest == {
        "image_count": 1,
        "total_encoded_bytes": 3,
        "images": [
            {
                "index": 0,
                "mime_type": "image/png",
                "byte_size": 3,
            }
        ],
        "request": {"model": "gemma3"},
    }
    unload_input = generate_inputs["unload_after_response"]
    assert unload_input.data_type == "boolean"
    assert unload_input.options == {
        "default": False,
        "label_on": "Unload",
        "label_off": "Use keep_alive",
        "advanced": True,
        "tooltip": (
            "Unload the Ollama model immediately after the response is complete. "
            "When enabled, this overrides keep_alive with 0."
        ),
    }
    assert generate_inputs["keep_alive"].data_type == "string"
    assert generate_input_names.index(
        "unload_after_response"
    ) + 1 == generate_input_names.index("keep_alive")

    sampling_class, sampling_schema = registered[
        "OllamaImageList_LlamaCppSamplingPreset"
    ]
    assert sampling_schema.inputs[0].name == "preset"
    assert sampling_schema.inputs[0].options["options"] == [
        "Image analysis",
        "Gemma 4",
        "Gemma 4 Uncensored",
        "llama.cpp default",
    ]
    assert (
        sampling_schema.outputs[0].data_type == "OLLAMA_IMAGE_LIST_LLAMA_CPP_SAMPLING"
    )
    assert sampling_class.execute("Gemma 4") == (
        {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
            "min_p": 0.0,
            "repeat_penalty": 1.0,
        },
    )

    runtime_class, runtime_schema = registered[
        "OllamaImageList_LlamaCppGemma4RuntimePreset"
    ]
    assert runtime_schema.inputs[0].name == "preset"
    assert runtime_schema.inputs[0].options["options"] == [
        "Text / Audio",
        "Vision Standard",
        "Vision Long / Thinking",
        "Multi-image / Video",
        "High Detail / OCR (Experimental)",
    ]
    assert runtime_schema.inputs[0].options["default"] == "Vision Standard"
    assert [field.name for field in runtime_schema.outputs] == [
        "runtime",
        "n_ctx",
        "max_tokens",
    ]
    assert runtime_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_GEMMA4_RUNTIME"
    )
    assert [field.data_type for field in runtime_schema.outputs[1:]] == ["int", "int"]
    assert runtime_class.execute("Vision Standard") == (
        {
            "n_batch": 512,
            "override_n_ubatch": True,
            "n_ubatch": 512,
            "override_image_max_tokens": True,
            "image_max_tokens": 512,
        },
        16384,
        1024,
    )
    runtime_module = importlib.import_module("backend.nodes.llama_cpp_runtime")
    for runtime_preset in runtime_module.GEMMA4_RUNTIME_PRESETS.values():
        advanced_runtime = {
            name: value
            for name, value in runtime_preset.items()
            if name not in {"n_ctx", "max_tokens"}
        }
        assert (
            runtime_module.normalize_gemma4_runtime(advanced_runtime)
            == advanced_runtime
        )
    invalid_runtime = dict(runtime_class.execute("Vision Standard")[0])
    invalid_runtime["n_batch"] = 2048
    invalid_runtime["image_max_tokens"] = 1120
    with pytest.raises(InputNormalizationError, match="effective runtime.n_ubatch"):
        runtime_module.normalize_gemma4_runtime(invalid_runtime)

    ngram_class, ngram_schema = registered[
        "OllamaImageList_LlamaCppNGramSpeculativePreset"
    ]
    assert [field.name for field in ngram_schema.inputs] == [
        "speculative_mode",
        "ngram_size",
        "num_pred_tokens",
        "ngram_mode",
        "ngram_min_hits",
        "ngram_max_entries_per_key",
    ]
    ngram_inputs = {field.name: field for field in ngram_schema.inputs}
    assert ngram_inputs["speculative_mode"].options == {
        "options": ["off", "ngram"],
        "default": "off",
        "tooltip": (
            "off preserves normal generation. ngram predicts candidates from "
            "repeated token patterns already in the current context."
        ),
    }
    assert ngram_inputs["ngram_size"].options["default"] == 3
    assert ngram_inputs["num_pred_tokens"].options["default"] == 10
    assert ngram_inputs["ngram_mode"].options["options"] == ["k", "k4v"]
    assert ngram_inputs["ngram_min_hits"].options["default"] == 2
    assert ngram_inputs["ngram_max_entries_per_key"].options["default"] == 8
    assert ngram_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_NGRAM_SPECULATIVE"
    )
    assert ngram_class.execute("off", 0, 0, "invalid", 0, 0) == (
        {"speculative_mode": "off"},
    )
    ngram_configuration = ngram_class.execute("ngram", 3, 10, "k", 2, 0)[0]
    assert ngram_configuration == {
        "speculative_mode": "ngram",
        "ngram_size": 3,
        "num_pred_tokens": 10,
        "ngram_min_hits": 2,
        "ngram_max_entries_per_key": None,
        "ngram_mode": "k",
    }
    ngram_module = importlib.import_module("backend.nodes.llama_cpp_ngram_speculative")
    assert ngram_module.normalize_ngram_speculative(ngram_configuration) == (
        ngram_configuration
    )

    compact_profile_class, compact_profile_schema = registered[
        "OllamaImageList_LlamaCppModelProfile"
    ]
    assert [field.name for field in compact_profile_schema.inputs] == [
        "profile",
        "custom_handler",
        "temperature",
        "top_p",
        "top_k",
        "min_p",
        "repeat_penalty",
        "presence_penalty",
    ]
    assert compact_profile_schema.inputs[0].options["options"] == [
        "General",
        "Gemma 4",
        "Gemma 4 Vision",
        "General Vision",
        "Muse Glimmer",
        "Qwen 3 VL",
        "Qwen 3.5+ Non-thinking",
        "Qwen 3.5+ Thinking",
        "Qwen 3.8 Non-Thinking",
        "Qwen 3.8 Thinking",
        "Custom",
    ]
    assert all(
        field.options["advanced"] is True for field in compact_profile_schema.inputs[1:]
    )
    assert compact_profile_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE"
    )
    model_profile_defaults = {
        field.name: field.options["default"]
        for field in compact_profile_schema.inputs
        if "default" in field.options
    }
    muse_profile = compact_profile_class.execute(
        **{**model_profile_defaults, "profile": "Muse Glimmer"}
    )[0]
    assert muse_profile["temperature"] == 1.0
    assert muse_profile["top_k"] == 64
    assert set(muse_profile) == {
        "handler",
        "recommended_reasoning_mode",
        "temperature",
        "top_p",
        "top_k",
        "min_p",
        "presence_penalty",
        "repeat_penalty",
    }
    qwen35_thinking_profile = compact_profile_class.execute(
        **{**model_profile_defaults, "profile": "Qwen 3.5+ Thinking"}
    )[0]
    assert qwen35_thinking_profile["recommended_reasoning_mode"] == "on"
    assert qwen35_thinking_profile["temperature"] == 1.0
    assert qwen35_thinking_profile["top_p"] == 0.95
    assert qwen35_thinking_profile["top_k"] == 20
    assert qwen35_thinking_profile["min_p"] == 0.0
    assert qwen35_thinking_profile["presence_penalty"] == 1.5
    qwen35_non_thinking_profile = compact_profile_class.execute(
        **{**model_profile_defaults, "profile": "Qwen 3.5+ Non-thinking"}
    )[0]
    assert qwen35_non_thinking_profile["recommended_reasoning_mode"] == "off"
    assert qwen35_non_thinking_profile["temperature"] == 0.7
    assert qwen35_non_thinking_profile["top_p"] == 0.8
    qwen3_vl_profile = compact_profile_class.execute(
        **{**model_profile_defaults, "profile": "Qwen 3 VL"}
    )[0]
    assert qwen3_vl_profile["temperature"] == 0.7
    assert qwen3_vl_profile["top_p"] == 0.8
    assert qwen3_vl_profile["top_k"] == 20
    assert qwen3_vl_profile["min_p"] == 0.0
    assert qwen3_vl_profile["presence_penalty"] == 1.5
    custom_model_profile = compact_profile_class.execute(
        "Custom", "qwen3_vl", 0.7, 0.8, 20, 0.1, 1.1, 1.25
    )[0]
    assert custom_model_profile == {
        "handler": "qwen3_vl",
        "recommended_reasoning_mode": "auto",
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.1,
        "presence_penalty": 1.25,
        "repeat_penalty": 1.1,
    }

    hardware_class, hardware_schema = registered[
        "OllamaImageList_LlamaCppHardwareRuntimeProfile"
    ]
    assert [field.name for field in hardware_schema.inputs] == [
        "profile",
        "n_batch",
        "n_ubatch",
        "gpu_layers",
        "main_gpu",
        "n_threads",
        "flash_attention",
        "use_mmap",
    ]
    assert hardware_schema.inputs[0].options["options"] == [
        "GPU Full Offload",
        "GPU Vision 512",
        "Qwen Vision 1024",
        "Automatic Offload",
        "CPU",
        "Custom",
    ]
    assert hardware_schema.inputs[0].options["default"] == "Automatic Offload"
    assert hardware_schema.inputs[3].options["default"] == "auto"
    assert hardware_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_HARDWARE_RUNTIME_PROFILE"
    )
    default_hardware_profile = hardware_class.execute(
        "GPU Full Offload", 1, 1, "cpu", 3, 8, "disabled", False
    )[0]
    assert default_hardware_profile == {
        "n_batch": 512,
        "n_ubatch": 0,
        "gpu_layers": "all",
        "main_gpu": 0,
        "n_threads": 0,
        "flash_attention": "auto",
        "use_mmap": True,
    }
    custom_hardware_profile = hardware_class.execute(
        "Custom", 2048, 1024, "auto", 1, 12, "enabled", False
    )[0]
    assert custom_hardware_profile["n_batch"] == 2048
    assert custom_hardware_profile["n_ubatch"] == 1024

    reasoning_class, reasoning_schema = registered[
        "OllamaImageList_LlamaCppReasoningConfig"
    ]
    assert [field.name for field in reasoning_schema.inputs] == [
        "reasoning_mode",
        "reasoning_effort",
        "max_reasoning_tokens",
        "preserve_thinking",
    ]
    assert reasoning_schema.inputs[0].options["options"] == ["auto", "off", "on"]
    assert reasoning_schema.search_aliases == ["thinking", "reasoning"]
    assert reasoning_schema.inputs[1].options["options"] == [
        "auto",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert reasoning_schema.inputs[2].options["default"] == 0
    assert reasoning_schema.inputs[3].options["default"] is False
    assert reasoning_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_REASONING_CONFIG"
    )
    auto_reasoning = reasoning_class.execute("auto", "xhigh", 2048)[0]
    assert auto_reasoning == {
        "reasoning_mode": "auto",
        "reasoning_effort": "auto",
        "max_reasoning_tokens": 0,
        "preserve_thinking": False,
    }
    off_reasoning = reasoning_class.execute("off", "high", 1024)[0]
    assert off_reasoning == (
        {
            "reasoning_mode": "off",
            "reasoning_effort": "auto",
            "max_reasoning_tokens": 0,
            "preserve_thinking": False,
        }
    )
    muse_reasoning = reasoning_class.execute("on", "high", 1024)[0]
    assert muse_reasoning == {
        "reasoning_mode": "on",
        "reasoning_effort": "high",
        "max_reasoning_tokens": 1024,
        "preserve_thinking": False,
    }

    compact_ngram_class, compact_ngram_schema = registered[
        "OllamaImageList_LlamaCppNGramSpeculativeConfig"
    ]
    assert [field.name for field in compact_ngram_schema.inputs] == [
        "speculative_mode",
        "ngram_size",
        "num_pred_tokens",
        "ngram_mode",
        "ngram_min_hits",
        "ngram_max_entries_per_key",
    ]
    assert compact_ngram_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
    )
    assert compact_ngram_class.execute("off", 3, 10, "k", 2, 8) == ({"kind": "off"},)
    compact_ngram_config = compact_ngram_class.execute("ngram", 3, 10, "k", 2, 0)[0]
    assert compact_ngram_config == {
        "kind": "ngram",
        "config": ngram_configuration,
    }

    native_config_class, native_config_schema = registered[
        "OllamaImageList_LlamaCppNativeSpeculativeConfig"
    ]
    assert native_config_schema.is_experimental is True
    native_inputs = {field.name: field for field in native_config_schema.inputs}
    assert native_inputs["preset"].options["options"] == [
        "Off",
        "External MTP",
        "Internal MTP",
        "DFlash",
        "DSpark",
        "Custom",
    ]
    assert [field.name for field in native_config_schema.inputs] == [
        "preset",
        "draft_model",
        "draft_n_max",
        "custom_spec_type",
        "custom_mtp_provider",
        "draft_p_min",
        "draft_n_gpu_layers",
        "draft_backend_sampling",
    ]
    assert "advanced" not in native_inputs["draft_n_max"].options
    assert native_inputs["custom_mtp_provider"].options["advanced"] is True
    assert native_inputs["draft_p_min"].options["advanced"] is True
    assert native_inputs["draft_n_gpu_layers"].options["options"] == ["auto", "all"]
    assert native_inputs["draft_n_gpu_layers"].options["advanced"] is True
    assert native_inputs["draft_backend_sampling"].options["advanced"] is True
    assert "spec_n_min" not in native_inputs
    assert "spec_n_max" not in native_inputs
    assert "spec_p_min" not in native_inputs
    assert native_config_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
    )
    off_draft_config = native_config_class.execute(
        "Off",
        "stale/draft.gguf",
        2,
        "draft-dspark",
        "off",
        0.0,
        "all",
        True,
    )[0]
    assert off_draft_config == {"kind": "off"}
    external_mtp_config = native_config_class.execute(
        "External MTP",
        "external/mtp-model-a.gguf",
        8,
        "draft-dspark",
        "off",
        0.25,
        "auto",
        False,
    )[0]
    assert external_mtp_config == {
        "kind": "native",
        "config": {
            "spec_type": "draft-mtp",
            "mtp_provider": "external",
            "draft_model": "external/mtp-model-a.gguf",
            "draft_n_max": 8,
            "draft_p_min": 0.25,
            "draft_n_gpu_layers": "auto",
            "draft_backend_sampling": False,
        },
    }
    dflash_config = native_config_class.execute(
        "DFlash",
        "external/dflash-model.gguf",
        7,
        "draft-dspark",
        "off",
        0.0,
        "all",
        True,
    )[0]
    assert dflash_config == {
        "kind": "native",
        "config": {
            "spec_type": "draft-dflash",
            "mtp_provider": "off",
            "draft_model": "external/dflash-model.gguf",
            "draft_n_max": 7,
            "draft_p_min": 0.0,
            "draft_n_gpu_layers": "all",
            "draft_backend_sampling": True,
        },
    }
    internal_mtp_config = native_config_class.execute(
        "Internal MTP",
        "stale/draft.gguf",
        2,
        "draft-dflash",
        "off",
        0.0,
        "all",
        True,
    )[0]
    assert internal_mtp_config["kind"] == "native"
    assert internal_mtp_config["config"]["draft_model"] == "[none]"
    custom_config = native_config_class.execute(
        "Custom",
        "external/custom-model.gguf",
        9,
        "draft-mtp",
        "external",
        0.4,
        "auto",
        False,
    )[0]
    assert custom_config["config"] == {
        "spec_type": "draft-mtp",
        "mtp_provider": "external",
        "draft_model": "external/custom-model.gguf",
        "draft_n_max": 9,
        "draft_p_min": 0.4,
        "draft_n_gpu_layers": "auto",
        "draft_backend_sampling": False,
    }

    compact_class, compact_schema = registered[
        "OllamaImageList_LlamaCppProfiledGenerate"
    ]
    compact_inputs = {field.name: field for field in compact_schema.inputs}
    assert compact_schema.is_input_list is True
    assert compact_schema.not_idempotent is True
    assert [field.name for field in compact_schema.inputs] == [
        "model_path",
        "mmproj_path",
        "model_profile",
        "hardware_profile",
        "reasoning",
        "speculative",
        "system",
        "prompt",
        "n_ctx",
        "max_tokens",
        "image_max_tokens",
        "seed",
        "stop",
        "images",
        "audio",
        "video",
        "video_with_audio",
        "verbose",
        "image_min_tokens",
    ]
    assert compact_inputs["model_profile"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE"
    )
    assert compact_inputs["hardware_profile"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_HARDWARE_RUNTIME_PROFILE"
    )
    assert compact_inputs["hardware_profile"].options["optional"] is True
    assert compact_inputs["image_min_tokens"].options["default"] == 0
    assert compact_inputs["image_max_tokens"].options["default"] == 0
    assert compact_inputs["reasoning"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_REASONING_CONFIG"
    )
    assert compact_inputs["reasoning"].options["optional"] is True
    assert compact_inputs["speculative"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
    )
    assert compact_inputs["video_with_audio"].data_type == "boolean"
    assert compact_inputs["video_with_audio"].options["default"] is False
    assert compact_inputs["speculative"].options["optional"] is True

    create_session_class, create_session_schema = registered[
        "OllamaImageList_LlamaCppCreateSession"
    ]
    assert create_session_schema.is_input_list is True
    assert create_session_schema.not_idempotent is True
    assert create_session_schema.is_experimental is True
    assert [field.name for field in create_session_schema.inputs] == [
        "model_path",
        "mmproj_path",
        "model_profile",
        "custom_chat_template",
        "hardware_profile",
        "reasoning",
        "speculative",
        "n_ctx",
        "image_min_tokens",
        "image_max_tokens",
        "verbose",
    ]
    assert create_session_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION"
    )
    _, create_runtime_session_schema = registered[
        "OllamaImageList_LlamaCppCreateRuntimeSession"
    ]
    assert create_runtime_session_schema.node_id == (
        "OllamaImageList_LlamaCppCreateRuntimeSession"
    )
    assert create_runtime_session_schema.is_input_list is True
    assert create_runtime_session_schema.not_idempotent is True
    assert create_runtime_session_schema.is_experimental is True
    assert [field.name for field in create_runtime_session_schema.inputs] == [
        "model_path",
        "mmproj_path",
        "model_profile",
        "custom_chat_template",
        "hardware_profile",
        "reasoning",
        "speculative",
        "n_ctx",
        "image_min_tokens",
        "image_max_tokens",
        "verbose",
    ]
    runtime_session_inputs = {
        field.name: field for field in create_runtime_session_schema.inputs
    }
    assert runtime_session_inputs["hardware_profile"].options["optional"] is True
    assert runtime_session_inputs["reasoning"].options["optional"] is True
    assert runtime_session_inputs["speculative"].options["optional"] is True
    assert [field.name for field in create_runtime_session_schema.outputs] == [
        "session"
    ]
    assert create_runtime_session_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION"
    )
    _, connect_session_schema = registered[
        "OllamaImageList_LlamaCppConnectSession"
    ]
    assert connect_session_schema.is_input_list is True
    assert connect_session_schema.not_idempotent is True
    assert connect_session_schema.is_experimental is True
    assert [field.name for field in connect_session_schema.inputs] == [
        "url",
        "available_models",
        "model",
        "api_key",
    ]
    connect_inputs = {field.name: field for field in connect_session_schema.inputs}
    assert connect_inputs["url"].data_type == "string"
    assert connect_inputs["available_models"].data_type == "combo"
    assert connect_inputs["available_models"].options["options"] == []
    assert connect_inputs["model"].data_type == "string"
    assert connect_session_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION"
    )
    _, create_question_input_schema = registered[
        "OllamaImageList_LlamaCppCreateQuestionFromInput"
    ]
    assert create_question_input_schema.is_input_list is True
    assert [field.name for field in create_question_input_schema.inputs] == [
        "question",
        "answer",
    ]
    assert all(
        field.options["force_input"] is True
        for field in create_question_input_schema.inputs
    )
    assert create_question_input_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_QUESTION"
    )
    _, decide_schema = registered["OllamaImageList_LlamaCppDecideSession"]
    assert decide_schema.is_input_list is True
    assert [field.name for field in decide_schema.inputs] == [
        "session",
        "system",
        "context",
        "question",
        "model_profile",
    ]
    assert [field.name for field in decide_schema.outputs] == [
        "selected",
        "probabilities_json",
        "session",
    ]
    assert decide_schema.inputs[0].data_type == "OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION"
    assert decide_schema.inputs[-1].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE"
    )
    assert decide_schema.inputs[-1].options["optional"] is True
    assert decide_schema.inputs[3].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_QUESTION"
    )
    assert decide_schema.outputs[-1].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION"
    )
    session_generate_class, session_generate_schema = registered[
        "OllamaImageList_LlamaCppSessionGenerate"
    ]
    assert session_generate_schema.is_input_list is True
    assert [field.name for field in session_generate_schema.inputs] == [
        "session",
        "system",
        "prompt",
        "max_tokens",
        "seed",
        "stop",
        "images",
        "audio",
        "video",
        "video_with_audio",
        "session_unload",
        "model_profile",
    ]
    session_generate_inputs = {
        field.name: field for field in session_generate_schema.inputs
    }
    assert session_generate_inputs["session_unload"].data_type == "boolean"
    assert session_generate_inputs["session_unload"].options["default"] is False
    assert session_generate_inputs["model_profile"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE"
    )
    assert session_generate_inputs["model_profile"].options["optional"] is True
    assert [field.name for field in session_generate_schema.outputs] == [
        "response",
        "thinking",
        "raw_json",
        "metrics_json",
        "media_diagnostics",
    ]
    assert session_generate_schema.outputs[-1].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MEDIA_DIAGNOSTICS"
    )
    unload_session_class, unload_session_schema = registered[
        "OllamaImageList_LlamaCppUnloadSession"
    ]
    assert unload_session_schema.is_output_node is True
    assert unload_session_schema.outputs == []
    assert [field.name for field in unload_session_schema.inputs] == [
        "session",
        "timing",
    ]
    assert unload_session_schema.inputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION"
    )
    assert unload_session_schema.inputs[1].data_type == "*"
    assert unload_session_schema.inputs[1].options["optional"] is True

    sequential_class, sequential_schema = registered[
        "OllamaImageList_LlamaCppSequentialGenerate"
    ]
    assert compact_class not in sequential_class.__mro__[1:]
    assert sequential_schema.is_input_list is True
    assert sequential_schema.not_idempotent is True
    assert [field.name for field in sequential_schema.inputs] == [
        field.name for field in compact_schema.inputs
    ]
    sequential_inputs = {field.name: field for field in sequential_schema.inputs}
    assert sequential_inputs["video_with_audio"].data_type == "boolean"
    assert sequential_inputs["video_with_audio"].options["default"] is False
    assert [field.name for field in sequential_schema.outputs] == [
        "response",
        "response_seq",
        "thinking",
        "raw_json",
        "metrics_json",
        "media_diagnostics",
    ]
    assert sequential_schema.outputs[1].data_type == "LLAMA_SEQUENTIAL_RESPONSE"
    assert all(
        field.options["is_output_list"] is True for field in sequential_schema.outputs
    )

    llama_class, llama_schema = registered["OllamaImageList_LlamaCppGenerate"]
    assert llama_schema.is_input_list is True
    assert llama_schema.not_idempotent is True
    llama_inputs = {field.name: field for field in llama_schema.inputs}
    assert llama_inputs["model_path"].data_type == "combo"
    assert llama_inputs["model_path"].options["options"] == [
        "external/model-a.gguf",
        "local/model-b.gguf",
        "external/mmproj-model-a-f16.gguf",
        "external/mtp-model-a.gguf",
    ]
    assert llama_inputs["mmproj_path"].data_type == "combo"
    assert llama_inputs["mmproj_path"].options["options"] == [
        "[none]",
        "external/mmproj-model-a-f16.gguf",
        "external/model-a.gguf",
        "local/model-b.gguf",
        "external/mtp-model-a.gguf",
    ]
    assert llama_inputs["sampling"].data_type == "OLLAMA_IMAGE_LIST_LLAMA_CPP_SAMPLING"
    assert llama_inputs["sampling"].options["optional"] is True
    assert llama_inputs["runtime"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_GEMMA4_RUNTIME"
    )
    assert llama_inputs["runtime"].options["optional"] is True
    assert llama_inputs["ngram_speculative"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_NGRAM_SPECULATIVE"
    )
    assert llama_inputs["ngram_speculative"].options["optional"] is True
    assert llama_inputs["handler"].options["options"] == [
        "auto",
        "generic",
        "gemma4",
        "qwen3_vl",
        "qwen25_vl",
        "qwen3_asr",
        "qwen35",
    ]
    assert llama_inputs["thinking"].data_type == "boolean"
    assert llama_inputs["thinking"].options["default"] is False
    assert "advanced" not in llama_inputs["thinking"].options
    assert llama_inputs["reasoning_strength"].options["options"] == [
        "auto",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert llama_inputs["reasoning_strength"].options["default"] == "auto"
    assert llama_inputs["reasoning_strength"].options["advanced"] is True
    assert llama_inputs["reasoning_budget"].options["default"] == 0
    assert llama_inputs["reasoning_budget"].options["min"] == 0
    assert llama_inputs["reasoning_budget"].options["max"] == 65536
    assert llama_inputs["reasoning_budget"].options["advanced"] is True
    assert llama_schema.inputs[-4].name == "reasoning_strength"
    assert llama_schema.inputs[-3].name == "reasoning_budget"
    assert llama_schema.inputs[-2].name == "override_image_min_tokens"
    assert llama_schema.inputs[-1].name == "image_min_tokens"
    assert llama_inputs["gpu_layers"].options["default"] == "all"
    assert all(
        llama_inputs[name].options["advanced"] is True
        for name in (
            "gpu_layers",
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "repeat_penalty",
        )
    )
    assert "advanced" not in llama_inputs["n_ctx"].options
    assert "advanced" not in llama_inputs["max_tokens"].options
    assert "advanced" not in llama_inputs["seed"].options
    assert llama_inputs["override_n_ubatch"].options["default"] is False
    assert llama_inputs["override_n_ubatch"].options["advanced"] is True
    assert llama_inputs["n_ubatch"].options["default"] == 512
    assert llama_inputs["n_ubatch"].options["advanced"] is True
    assert llama_inputs["override_image_min_tokens"].options["default"] is False
    assert llama_inputs["override_image_min_tokens"].options["advanced"] is True
    assert llama_inputs["image_min_tokens"].options["default"] == 1024
    assert llama_inputs["image_min_tokens"].options["advanced"] is True
    assert llama_inputs["override_image_max_tokens"].options["default"] is False
    assert llama_inputs["override_image_max_tokens"].options["advanced"] is True
    assert llama_inputs["image_max_tokens"].options["default"] == 1120
    assert llama_inputs["image_max_tokens"].options["advanced"] is True
    assert llama_inputs["images"].options["optional"] is True
    assert llama_inputs["audio"].data_type == "audio"
    assert llama_inputs["audio"].options["optional"] is True
    assert llama_inputs["video"].data_type == "video"
    assert llama_inputs["video"].options["optional"] is True
    assert "MTMD_VIDEO" in llama_inputs["video"].options["tooltip"]
    assert "FFmpeg" not in llama_inputs["video"].options["tooltip"]
    assert [field.name for field in llama_schema.outputs] == [
        "response",
        "thinking",
        "raw_json",
        "metrics_json",
        "media_diagnostics",
    ]
    assert llama_schema.outputs[-1].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MEDIA_DIAGNOSTICS"
    )

    assert "OllamaImageList_LlamaCppSpeculativeGenerate" not in registered
    speculative_module = importlib.import_module(
        "backend.nodes.llama_cpp_speculative_generate"
    )
    speculative_class = speculative_module.LlamaCppSpeculativeGenerateNode
    speculative_schema = speculative_class.define_schema()
    assert speculative_schema.is_input_list is True
    assert speculative_schema.not_idempotent is True
    assert speculative_schema.is_experimental is True
    speculative_inputs = {field.name: field for field in speculative_schema.inputs}
    speculative_input_names = [field.name for field in speculative_schema.inputs]
    assert speculative_input_names.index("mmproj_path") + 1 == (
        speculative_input_names.index("draft_model")
    )
    assert speculative_inputs["draft_model"].options["options"] == [
        "[none]",
        "external/mtp-model-a.gguf",
        "external/model-a.gguf",
        "local/model-b.gguf",
        "external/mmproj-model-a-f16.gguf",
    ]
    assert speculative_inputs["spec_type"].options["options"] == [
        "none",
        "draft-dflash",
        "draft-dspark",
        "draft-mtp",
    ]
    assert speculative_inputs["spec_type"].options["default"] == "none"
    assert speculative_inputs["spec_n_max"].options["default"] == 2
    assert speculative_inputs["spec_n_min"].options["default"] == 0
    assert speculative_inputs["spec_p_min"].options["default"] == 0.0
    assert speculative_inputs["mtp_provider"].options["options"] == [
        "off",
        "external",
        "internal",
    ]
    assert speculative_inputs["mtp_provider"].options["default"] == "off"
    assert "mtp_n_max" not in speculative_inputs
    assert "mtp_n_min" not in speculative_inputs
    assert "mtp_p_min" not in speculative_inputs
    assert "mtp_verbose" not in speculative_inputs
    assert speculative_input_names[7] == "mtp_provider"
    assert speculative_inputs["sampling"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SAMPLING"
    )
    assert speculative_inputs["runtime"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_GEMMA4_RUNTIME"
    )
    assert "ngram_speculative" not in speculative_inputs
    assert speculative_inputs["reasoning_strength"].options["advanced"] is True
    assert speculative_input_names.index("reasoning_strength") == (
        speculative_input_names.index("thinking") + 1
    )
    assert speculative_input_names.index("reasoning_budget") == (
        speculative_input_names.index("reasoning_strength") + 1
    )
    assert [field.name for field in speculative_schema.outputs] == [
        "response",
        "thinking",
        "raw_json",
        "metrics_json",
        "media_diagnostics",
    ]

    llama_module = importlib.import_module("backend.nodes.llama_cpp_generate")
    speculative_binding = object()
    monkeypatch.setattr(
        speculative_module,
        "require_native_speculative",
        lambda: speculative_binding,
    )
    captured_speculative_call = {}

    def fake_run_chat(**kwargs):
        captured_speculative_call.update(kwargs)
        return SimpleNamespace(
            response="done",
            thinking="",
            raw={"choices": []},
            metrics={"model_unloaded": True},
            media_diagnostics={"model_unloaded_after_response": True},
        )

    monkeypatch.setattr(llama_module, "run_chat", fake_run_chat)
    compact_module = importlib.import_module("backend.nodes.llama_cpp_compact")
    monkeypatch.setattr(compact_module, "run_chat", fake_run_chat)

    def fake_run_chat_sequential(*, media_items, **kwargs):
        captured_speculative_call.update(kwargs)
        captured_speculative_call["media_item_count"] = len(media_items)
        return [fake_run_chat(**kwargs) for _media in media_items]

    monkeypatch.setattr(
        compact_module,
        "run_chat_sequential",
        fake_run_chat_sequential,
    )
    session_module = importlib.import_module("backend.nodes.llama_cpp_session")
    captured_session_configuration = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured_session_configuration.update(kwargs)
            self.closed = False
            self.requests = []

        def generate(self, **kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                response="session done",
                thinking="",
                raw={"choices": []},
                metrics={"model_unloaded": False},
                media_diagnostics={"model_unloaded_after_response": False},
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(session_module, "LlamaCppSession", FakeSession)
    create_session_values = {
        field.name: [field.options["default"]]
        for field in create_session_schema.inputs
        if "default" in field.options
    }
    create_session_values.update(
        model_path=["external/model-a.gguf"],
        mmproj_path=["[none]"],
        model_profile=[muse_profile],
        hardware_profile=[custom_hardware_profile],
        reasoning=[muse_reasoning],
        speculative=[compact_ngram_config],
    )
    created_session = create_session_class.execute(**create_session_values)[0]
    assert isinstance(created_session, FakeSession)
    assert captured_session_configuration["model_path"] == (
        "D:/SharedModels/LLM/external/model-a.gguf"
    )
    assert captured_session_configuration["n_batch"] == 2048
    assert captured_session_configuration["n_ubatch"] == 1024
    assert captured_session_configuration["reasoning_budget"] == 1024
    assert captured_session_configuration["temperature"] == 1.0
    assert captured_session_configuration["ngram_speculative"] == ngram_configuration
    session_generate_output = session_generate_class.execute(
        [created_session],
        ["system"],
        ["prompt"],
        [512],
        [-1],
        [""],
        [None],
        [None],
        [None],
        [False],
    )
    assert session_generate_output[0] == "session done"
    assert session_generate_output[-1] == {"model_unloaded_after_response": False}
    assert created_session.requests[0]["prompt"] == "prompt"
    unload_session_class.execute([created_session], ["after loop"])
    assert created_session.closed is True
    unload_session_class.execute([created_session])

    default_session_values = dict(create_session_values)
    default_session_values.pop("hardware_profile")
    default_session_values.pop("reasoning")
    default_session_values.pop("speculative")
    captured_session_configuration.clear()
    create_session_class.execute(**default_session_values)
    assert captured_session_configuration["n_batch"] == 512
    assert captured_session_configuration["gpu_layers"] == "auto"
    assert captured_session_configuration["reasoning_budget"] == 0
    assert "ngram_speculative" not in captured_session_configuration

    llama_values = {
        field.name: [field.options["default"]]
        for field in llama_schema.inputs
        if "default" in field.options
    }
    llama_values.update(
        model_path=["external/model-a.gguf"],
        mmproj_path=["[none]"],
        ngram_speculative=[ngram_configuration],
    )
    llama_output = llama_class.execute(**llama_values)
    assert llama_output[0] == "done"
    assert captured_speculative_call["ngram_speculative"] == ngram_configuration
    assert captured_speculative_call["reasoning_strength"] == "auto"
    assert captured_speculative_call["reasoning_budget"] == 0
    assert "draft_model_path" not in captured_speculative_call

    captured_speculative_call.clear()
    sequential_values = {
        field.name: [field.options["default"]]
        for field in sequential_schema.inputs
        if "default" in field.options
    }
    sequential_values.update(
        model_path=["external/model-a.gguf"],
        mmproj_path=["[none]"],
        model_profile=[muse_profile],
        max_tokens=[4096],
        reasoning=[muse_reasoning],
    )
    sequential_output = sequential_class.execute(**sequential_values)
    assert sequential_output[0] == ["done"]
    assert sequential_output[1] == [
        {
            "request_index": 0,
            "kind": "text",
            "modality_index": 0,
            "response": "done",
        }
    ]
    assert sequential_output[2] == [""]
    assert all(isinstance(value, list) for value in sequential_output)
    assert captured_speculative_call["model_path"] == (
        "D:/SharedModels/LLM/external/model-a.gguf"
    )
    assert captured_speculative_call["media_item_count"] == 1
    assert captured_speculative_call["reasoning_strength"] == "high"
    assert captured_speculative_call["reasoning_budget"] == 1024

    captured_speculative_call.clear()
    compact_values = {
        field.name: [field.options["default"]]
        for field in compact_schema.inputs
        if "default" in field.options
    }
    compact_values.update(
        model_path=["external/model-a.gguf"],
        mmproj_path=["[none]"],
        model_profile=[muse_profile],
        n_ctx=[32768],
        max_tokens=[4096],
        image_min_tokens=[0],
        image_max_tokens=[0],
        reasoning=[muse_reasoning],
        speculative=[compact_ngram_config],
    )
    compact_output = compact_class.execute(**compact_values)
    assert compact_output[0] == "done"
    assert captured_speculative_call["handler"] == "generic"
    assert captured_speculative_call["reasoning_strength"] == "high"
    assert captured_speculative_call["n_ctx"] == 32768
    assert captured_speculative_call["max_tokens"] == 4096
    assert captured_speculative_call["thinking"] is True
    assert captured_speculative_call["reasoning_strength"] == "high"
    assert captured_speculative_call["reasoning_budget"] == 1024
    assert captured_speculative_call["temperature"] == 1.0
    assert captured_speculative_call["presence_penalty"] == 0.0
    assert captured_speculative_call["n_batch"] == 512
    assert captured_speculative_call["gpu_layers"] == "auto"
    assert captured_speculative_call["main_gpu"] == 0
    assert captured_speculative_call["n_threads"] == 0
    assert captured_speculative_call["flash_attention"] == "auto"
    assert captured_speculative_call["use_mmap"] is True
    assert captured_speculative_call["override_n_ubatch"] is False
    assert captured_speculative_call["override_image_min_tokens"] is False
    assert captured_speculative_call["override_image_max_tokens"] is False
    assert captured_speculative_call["ngram_speculative"] == ngram_configuration

    captured_speculative_call.clear()
    compact_auto_values = dict(compact_values)
    compact_auto_values.pop("reasoning")
    compact_auto_output = compact_class.execute(**compact_auto_values)
    assert compact_auto_output[0] == "done"
    assert captured_speculative_call["thinking"] is None
    assert captured_speculative_call["reasoning_strength"] == "auto"
    assert captured_speculative_call["reasoning_budget"] == 0

    captured_speculative_call.clear()
    compact_qwen35_thinking_values = dict(compact_values)
    compact_qwen35_thinking_values.pop("reasoning")
    compact_qwen35_thinking_values["model_profile"] = [qwen35_thinking_profile]
    compact_qwen35_thinking_output = compact_class.execute(
        **compact_qwen35_thinking_values
    )
    assert compact_qwen35_thinking_output[0] == "done"
    assert captured_speculative_call["thinking"] is True
    assert captured_speculative_call["temperature"] == 1.0
    assert captured_speculative_call["top_p"] == 0.95
    assert captured_speculative_call["top_k"] == 20
    assert captured_speculative_call["min_p"] == 0.0
    assert captured_speculative_call["presence_penalty"] == 1.5

    captured_speculative_call.clear()
    compact_qwen35_non_thinking_values = dict(compact_qwen35_thinking_values)
    compact_qwen35_non_thinking_values["model_profile"] = [qwen35_non_thinking_profile]
    compact_qwen35_non_thinking_output = compact_class.execute(
        **compact_qwen35_non_thinking_values
    )
    assert compact_qwen35_non_thinking_output[0] == "done"
    assert captured_speculative_call["thinking"] is False
    assert captured_speculative_call["temperature"] == 0.7
    assert captured_speculative_call["top_p"] == 0.8

    compact_qwen35_conflict_values = dict(compact_qwen35_thinking_values)
    compact_qwen35_conflict_values["reasoning"] = [off_reasoning]
    with pytest.raises(
        InputNormalizationError,
        match="Model Profile requires reasoning_mode=on",
    ):
        compact_class.execute(**compact_qwen35_conflict_values)

    excessive_reasoning = reasoning_class.execute("on", "high", 8192)[0]
    compact_excessive_values = dict(compact_values)
    compact_excessive_values["reasoning"] = [excessive_reasoning]
    with pytest.raises(
        InputNormalizationError,
        match="max_reasoning_tokens cannot exceed Generate max_tokens",
    ):
        compact_class.execute(**compact_excessive_values)

    def unexpected_compact_speculative_dependency():
        raise AssertionError(
            "an off Compact config imported the speculative dependency"
        )

    monkeypatch.setattr(
        compact_module,
        "require_native_speculative",
        unexpected_compact_speculative_dependency,
    )
    captured_speculative_call.clear()
    compact_off_values = dict(compact_values)
    compact_off_values["speculative"] = [off_draft_config]
    compact_off_output = compact_class.execute(**compact_off_values)
    assert compact_off_output[0] == "done"
    assert "ngram_speculative" not in captured_speculative_call
    assert "draft_model_path" not in captured_speculative_call
    assert "spec_type" not in captured_speculative_call

    captured_speculative_call.clear()
    compact_native_values = {
        field.name: [field.options["default"]]
        for field in compact_schema.inputs
        if "default" in field.options
    }
    compact_native_values.update(
        model_path=["external/model-a.gguf"],
        mmproj_path=["[none]"],
        model_profile=[muse_profile],
        hardware_profile=[custom_hardware_profile],
        image_min_tokens=[768],
        image_max_tokens=[768],
        speculative=[dflash_config],
    )
    monkeypatch.setattr(
        compact_module,
        "require_native_speculative",
        lambda: speculative_binding,
    )
    compact_native_output = compact_class.execute(**compact_native_values)
    assert compact_native_output[0] == "done"
    assert captured_speculative_call["draft_model_path"] == (
        "D:/SharedModels/LLM/external/dflash-model.gguf"
    )
    assert captured_speculative_call["spec_type"] == "draft-dflash"
    assert captured_speculative_call["spec_n_max"] == 7
    assert captured_speculative_call["spec_n_min"] == 0
    assert captured_speculative_call["spec_p_min"] == 0.0
    assert captured_speculative_call["draft_n_gpu_layers"] == "all"
    assert captured_speculative_call["draft_backend_sampling"] is True
    assert captured_speculative_call["speculative_api"] is speculative_binding
    assert captured_speculative_call["override_n_ubatch"] is True
    assert captured_speculative_call["n_ubatch"] == 1024
    assert captured_speculative_call["override_image_min_tokens"] is True
    assert captured_speculative_call["image_min_tokens"] == 768
    assert captured_speculative_call["override_image_max_tokens"] is True
    assert captured_speculative_call["image_max_tokens"] == 768

    original_resolve_gguf_selection = llama_module._resolve_gguf_selection

    def reject_stale_inactive_selection(selection, *, label, required):
        if selection.startswith("stale/"):
            raise AssertionError(f"inactive {label} selection was resolved")
        return original_resolve_gguf_selection(
            selection,
            label=label,
            required=required,
        )

    monkeypatch.setattr(
        llama_module,
        "_resolve_gguf_selection",
        reject_stale_inactive_selection,
    )
    captured_speculative_call.clear()
    llama_values["mmproj_path"] = ["stale/mmproj.gguf"]
    llama_output = llama_class.execute(**llama_values)
    assert llama_output[0] == "done"
    assert captured_speculative_call["mmproj_path"] == ""

    captured_speculative_call.clear()
    speculative_values = {
        field.name: [field.options["default"]]
        for field in speculative_schema.inputs
        if "default" in field.options
    }
    speculative_values.update(
        model_path=["external/model-a.gguf"],
        mmproj_path=["[none]"],
        draft_model=["stale/draft.gguf"],
    )

    def unexpected_speculative_dependency():
        raise AssertionError("spec_type=none imported the speculative dependency")

    monkeypatch.setattr(
        speculative_module,
        "require_native_speculative",
        unexpected_speculative_dependency,
    )
    speculative_output = speculative_class.execute(**speculative_values)
    assert speculative_output[0] == "done"
    assert captured_speculative_call["draft_model_path"] == ""
    assert captured_speculative_call["spec_type"] == "none"
    assert captured_speculative_call["reasoning_strength"] == "auto"
    assert captured_speculative_call["reasoning_budget"] == 0
    assert "speculative_api" not in captured_speculative_call

    monkeypatch.setattr(
        speculative_module,
        "require_native_speculative",
        lambda: speculative_binding,
    )
    captured_speculative_call.clear()
    speculative_values.update(
        draft_model=["external/mtp-model-a.gguf"],
        spec_type=["draft-dflash"],
        mtp_provider=["internal"],
    )
    speculative_output = speculative_class.execute(**speculative_values)
    assert speculative_output[0] == "done"
    assert captured_speculative_call["draft_model_path"] == (
        "D:/SharedModels/LLM/external/mtp-model-a.gguf"
    )
    assert captured_speculative_call["spec_type"] == "draft-dflash"
    assert captured_speculative_call["spec_n_max"] == 2
    assert captured_speculative_call["spec_n_min"] == 0
    assert captured_speculative_call["spec_p_min"] == 0.0
    assert captured_speculative_call["mtp_provider"] == "off"
    assert "mtp_n_max" not in captured_speculative_call
    assert "mtp_n_min" not in captured_speculative_call
    assert "mtp_p_min" not in captured_speculative_call
    assert "mtp_verbose" not in captured_speculative_call
    assert captured_speculative_call["speculative_api"] is speculative_binding
    assert "ngram_speculative" not in captured_speculative_call

    captured_speculative_call.clear()
    speculative_values.update(
        draft_model=["[none]"],
        spec_type=["draft-mtp"],
        mtp_provider=["internal"],
    )
    speculative_output = speculative_class.execute(**speculative_values)
    assert speculative_output[0] == "done"
    assert captured_speculative_call["draft_model_path"] == ""
    assert captured_speculative_call["mtp_provider"] == "internal"

    def missing_speculative_api():
        raise BackendError("native speculative dependency is not installed")

    def unexpected_media_normalization(**_kwargs):
        raise AssertionError("media normalization ran before the dependency check")

    monkeypatch.setattr(
        speculative_module,
        "require_native_speculative",
        missing_speculative_api,
    )
    monkeypatch.setattr(llama_module, "normalize_media", unexpected_media_normalization)
    captured_speculative_call.clear()
    with pytest.raises(BackendError, match="dependency is not installed"):
        speculative_class.execute(**speculative_values)
    assert captured_speculative_call == {}

    assert llama_module._resolve_sampling_values(
        temperature=[0.1],
        top_p=[0.8],
        top_k=[20],
        min_p=[0.1],
        repeat_penalty=[1.1],
        sampling=None,
    ) == {
        "temperature": 0.1,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.1,
        "repeat_penalty": 1.1,
    }
    assert llama_module._resolve_sampling_values(
        temperature=[0.1],
        top_p=[0.8],
        top_k=[20],
        min_p=[0.1],
        repeat_penalty=[1.1],
        sampling=[sampling_class.execute("Gemma 4")[0]],
    ) == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
    }
    assert llama_module._resolve_runtime_values(
        n_batch=[512],
        override_n_ubatch=[False],
        n_ubatch=[2048],
        override_image_min_tokens=[True],
        image_min_tokens=[1024],
        override_image_max_tokens=[False],
        image_max_tokens=[2048],
        runtime=None,
    ) == {
        "n_batch": 512,
        "override_n_ubatch": False,
        "n_ubatch": 2048,
        "override_image_min_tokens": True,
        "image_min_tokens": 1024,
        "override_image_max_tokens": False,
        "image_max_tokens": 2048,
    }
    assert llama_module._resolve_runtime_values(
        n_batch=[512],
        override_n_ubatch=[False],
        n_ubatch=[512],
        override_image_min_tokens=[True],
        image_min_tokens=[1024],
        override_image_max_tokens=[False],
        image_max_tokens=[1120],
        runtime=[runtime_class.execute("Vision Long / Thinking")[0]],
    ) == {
        "n_batch": 512,
        "override_n_ubatch": True,
        "n_ubatch": 512,
        "override_image_min_tokens": True,
        "image_min_tokens": 1024,
        "override_image_max_tokens": True,
        "image_max_tokens": 512,
    }
    assert (
        llama_module._resolve_gguf_selection(
            "external/model-a.gguf", label="model GGUF", required=True
        )
        == "D:/SharedModels/LLM/external/model-a.gguf"
    )
    assert (
        llama_module._resolve_gguf_selection(
            "[none]", label="mmproj GGUF", required=False
        )
        == ""
    )
    with pytest.raises(InputNormalizationError, match="No model GGUF is selected"):
        llama_module._resolve_gguf_selection(
            "[no GGUF models found]", label="model GGUF", required=True
        )

    diagnostics_class, diagnostics_schema = registered[
        "OllamaImageList_LlamaCppMediaDiagnostics"
    ]
    assert diagnostics_schema.inputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MEDIA_DIAGNOSTICS"
    )
    assert [field.name for field in diagnostics_schema.outputs] == [
        "all_media_evaluated",
        "vision_available",
        "audio_available",
        "video_available",
        "audio_count",
        "image_count",
        "video_count",
        "json",
        "formatted_text",
    ]
    diagnostics = {
        "schema_version": 1,
        "handler": "GenericMTMDChatHandler",
        "capabilities": {"vision": True, "audio": True, "video": False},
        "requested": {
            "media_count": 2,
            "image_count": 1,
            "audio_count": 1,
            "video_count": 0,
        },
        "evaluated": {
            "media_count": 2,
            "image_count": 1,
            "audio_count": 1,
            "video_count": 0,
        },
        "mtmd": {
            "strict_pipeline": True,
            "completion_succeeded": True,
            "all_media_evaluated": True,
            "verification": "mtmd_evaluated",
        },
        "model_unloaded_after_response": True,
    }
    diagnostics_outputs = diagnostics_class.execute(diagnostics)
    assert diagnostics_outputs[:7] == (True, True, True, False, 1, 1, 0)
    assert json.loads(diagnostics_outputs[7]) == diagnostics
    assert diagnostics_outputs[8] == (
        "MTMD MEDIA INGESTION: PASS\n\n"
        "Capabilities\n"
        "  Vision: available\n"
        "  Audio:  available\n"
        "  Video:  unavailable\n\n"
        "Evaluated\n"
        "  Images: 1/1\n"
        "  Audio:  1/1\n"
        "  Video:  0/0\n\n"
        "Handler: GenericMTMDChatHandler\n"
        "Verification: mtmd_evaluated\n"
        "Model unloaded: yes"
    )

    registered_model_folder = sys.modules["folder_paths"].folder_names_and_paths[
        "ollama_image_list_llm"
    ]
    assert registered_model_folder == (
        [
            os.path.abspath(os.path.normpath("D:/SharedModels/LLM")),
            os.path.abspath(os.path.normpath(os.path.join("C:/ComfyUI/models", "LLM"))),
        ],
        {".gguf"},
    )


def test_compact_sequential_media_bundles_are_atomic_and_modality_ordered(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    compact_module = importlib.import_module("backend.nodes.llama_cpp_compact")

    bundles = compact_module._sequential_media_bundles(
        images=[
            solid_image(1, 1, 1, 3, 0.25),
            solid_image(1, 1, 1, 3, 0.75),
        ],
        audio=[
            {"waveform": silent_audio(1, 1, 8), "sample_rate": 16_000},
            {"waveform": silent_audio(1, 1, 16), "sample_rate": 16_000},
        ],
        video=[VideoInputStub(b"video-0"), VideoInputStub(b"video-1")],
    )

    assert [[item.kind for item in bundle.items] for bundle in bundles] == [
        ["image"],
        ["image"],
        ["audio"],
        ["audio"],
        ["video"],
        ["video"],
    ]
    assert all(len(bundle.items) == 1 for bundle in bundles)


def test_compact_sequential_video_with_audio_pairs_extracted_audio(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    compact_module = importlib.import_module("backend.nodes.llama_cpp_compact")
    video_item = SimpleNamespace(kind="video")
    embedded_audio_item = SimpleNamespace(kind="audio")

    def fake_normalize_media(*, video, video_with_audio, **_kwargs):
        assert video_with_audio is True
        return SimpleNamespace(items=(embedded_audio_item, video_item))

    monkeypatch.setattr(compact_module, "normalize_media", fake_normalize_media)

    bundles = compact_module._sequential_media_bundles(
        video=[VideoInputStub(b"video-with-audio")],
        video_with_audio=True,
    )

    assert [[item.kind for item in bundle.items] for bundle in bundles] == [
        ["audio", "video"]
    ]


def test_compact_sequential_outputs_include_typed_sequence(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    compact_module = importlib.import_module("backend.nodes.llama_cpp_compact")
    kinds = ["image", "image", "audio", "video", "video"]
    results = [
        SimpleNamespace(
            response=f"{kind}-{index}",
            thinking="",
            raw={},
            metrics={},
            media_diagnostics={},
        )
        for index, kind in enumerate(kinds)
    ]

    output = compact_module._compact_sequential_outputs(results, kinds)

    assert output[0] == [
        "image-0",
        "image-1",
        "audio-2",
        "video-3",
        "video-4",
    ]
    assert output[1] == [
        {
            "request_index": 0,
            "kind": "image",
            "modality_index": 0,
            "response": "image-0",
        },
        {
            "request_index": 1,
            "kind": "image",
            "modality_index": 1,
            "response": "image-1",
        },
        {
            "request_index": 2,
            "kind": "audio",
            "modality_index": 0,
            "response": "audio-2",
        },
        {
            "request_index": 3,
            "kind": "video",
            "modality_index": 0,
            "response": "video-3",
        },
        {
            "request_index": 4,
            "kind": "video",
            "modality_index": 1,
            "response": "video-4",
        },
    ]


def test_runtime_session_server_arguments_convert_profiles_without_native_api(
    monkeypatch,
):
    install_comfy_api_stub(monkeypatch)
    session_module = importlib.import_module("backend.nodes.llama_cpp_session")
    compact_module = importlib.import_module("backend.nodes.llama_cpp_compact")
    llama_module = importlib.import_module("backend.backends.llama_cpp")

    monkeypatch.setattr(
        session_module,
        "_resolve_file",
        lambda value, **_kwargs: value or None,
    )

    def unexpected_native_speculative_dependency():
        raise AssertionError("runtime server arguments must not load llama_cpp_python")

    for module in (session_module, compact_module, llama_module):
        monkeypatch.setattr(
            module,
            "require_native_speculative",
            unexpected_native_speculative_dependency,
            raising=False,
        )

    model_profile = {
        "handler": "gemma4",
        "recommended_reasoning_mode": "auto",
        "temperature": 0.65,
        "top_p": 0.87,
        "top_k": 37,
        "min_p": 0.13,
        "presence_penalty": 0.4,
        "repeat_penalty": 1.17,
    }
    hardware_profile = {
        "n_batch": 1024,
        "n_ubatch": 512,
        "gpu_layers": "cpu",
        "main_gpu": 2,
        "n_threads": 7,
        "flash_attention": "disabled",
        "use_mmap": False,
    }
    base_values = {
        "model_path": ["external/model-a.gguf"],
        "mmproj_path": ["external/mmproj-model-a-f16.gguf"],
        "model_profile": [model_profile],
        "custom_chat_template": ["{% custom template %}"],
        "hardware_profile": [hardware_profile],
        "reasoning": [
            {
                "reasoning_mode": "on",
                "reasoning_effort": "high",
                "max_reasoning_tokens": 321,
                "preserve_thinking": True,
            }
        ],
        "n_ctx": [4096],
        "image_min_tokens": [64],
        "image_max_tokens": [128],
        "verbose": [True],
        "reasoning_preserve_supported": True,
    }

    def option_value(arguments, option):
        return arguments[arguments.index(option) + 1]

    native_values = {
        **base_values,
        "speculative": [
            {
                "kind": "native",
                "config": {
                    "spec_type": "draft-dflash",
                    "mtp_provider": "off",
                    "draft_model": "external/mtp-model-a.gguf",
                    "draft_n_max": 7,
                    "draft_p_min": 0.2,
                    "draft_n_gpu_layers": "all",
                    "draft_backend_sampling": False,
                },
            }
        ],
    }
    arguments, custom_template, model = session_module._runtime_server_arguments(
        **native_values
    )
    assert custom_template == "{% custom template %}"
    assert model.endswith("external/model-a.gguf")
    assert option_value(arguments, "--model") == model
    assert option_value(arguments, "--mmproj").endswith(
        "external/mmproj-model-a-f16.gguf"
    )
    assert option_value(arguments, "--ctx-size") == "4096"
    assert option_value(arguments, "--temp") == "0.65"
    assert option_value(arguments, "--top-p") == "0.87"
    assert option_value(arguments, "--top-k") == "37"
    assert option_value(arguments, "--min-p") == "0.13"
    assert option_value(arguments, "--presence-penalty") == "0.4"
    assert option_value(arguments, "--repeat-penalty") == "1.17"
    assert option_value(arguments, "--batch-size") == "1024"
    assert option_value(arguments, "--ubatch-size") == "512"
    assert option_value(arguments, "--gpu-layers") == "0"
    assert option_value(arguments, "--main-gpu") == "2"
    assert option_value(arguments, "--flash-attn") == "off"
    assert option_value(arguments, "--load-mode") == "none"
    assert option_value(arguments, "--threads") == "7"
    assert option_value(arguments, "--reasoning") == "on"
    assert option_value(arguments, "--reasoning-effort") == "high"
    assert option_value(arguments, "--reasoning-budget") == "321"
    assert "--reasoning-preserve" in arguments
    assert option_value(arguments, "--image-min-tokens") == "64"
    assert option_value(arguments, "--image-max-tokens") == "128"
    assert option_value(arguments, "--spec-type") == "draft-dflash"
    assert option_value(arguments, "--spec-draft-n-max") == "7"
    assert option_value(arguments, "--spec-draft-p-min") == "0.2"
    assert option_value(arguments, "--spec-draft-ngl") == "all"
    assert "--no-spec-draft-backend-sampling" in arguments
    assert option_value(arguments, "--spec-draft-model").endswith(
        "external/mtp-model-a.gguf"
    )
    assert "--handler" not in arguments
    assert "--verbose" in arguments

    zero_values = {
        **base_values,
        "hardware_profile": None,
        "reasoning": [
            {
                "reasoning_mode": "on",
                "reasoning_effort": "auto",
                "max_reasoning_tokens": 0,
                "preserve_thinking": False,
            }
        ],
        "image_min_tokens": [0],
        "image_max_tokens": [0],
        "verbose": [False],
        "reasoning_preserve_supported": False,
        "speculative": [{"kind": "off"}],
    }
    zero_arguments, _, _ = session_module._runtime_server_arguments(**zero_values)
    assert option_value(zero_arguments, "--batch-size") == "512"
    assert option_value(zero_arguments, "--gpu-layers") == "auto"
    assert option_value(zero_arguments, "--flash-attn") == "auto"
    assert option_value(zero_arguments, "--load-mode") == "mmap"
    assert option_value(zero_arguments, "--reasoning") == "on"
    assert not {
        "--ubatch-size",
        "--threads",
        "--reasoning-effort",
        "--reasoning-budget",
        "--reasoning-preserve",
        "--no-reasoning-preserve",
        "--image-min-tokens",
        "--image-max-tokens",
        "--spec-type",
        "--verbose",
    }.intersection(zero_arguments)

    off_values = {
        **zero_values,
        "reasoning": [
            {
                "reasoning_mode": "off",
                "reasoning_effort": "high",
                "max_reasoning_tokens": 321,
                "preserve_thinking": False,
            }
        ],
    }
    off_arguments, _, _ = session_module._runtime_server_arguments(**off_values)
    assert option_value(off_arguments, "--reasoning") == "off"
    assert "--reasoning-effort" not in off_arguments
    assert "--reasoning-budget" not in off_arguments

    for mode in ("k", "k4v"):
        mode_arguments = []
        for max_entries in (1, 99):
            ngram_values = {
                **zero_values,
                "speculative": [
                    {
                        "kind": "ngram",
                        "config": {
                            "speculative_mode": "ngram",
                            "ngram_size": 4,
                            "num_pred_tokens": 12,
                            "ngram_mode": mode,
                            "ngram_min_hits": 3,
                            "ngram_max_entries_per_key": max_entries,
                        },
                    }
                ],
            }
            arguments, _, _ = session_module._runtime_server_arguments(
                **ngram_values
            )
            prefix = f"--spec-ngram-map-{mode}"
            assert option_value(arguments, "--spec-type") == f"ngram-map-{mode}"
            assert option_value(arguments, f"{prefix}-size-n") == "4"
            assert option_value(arguments, f"{prefix}-size-m") == "12"
            assert option_value(arguments, f"{prefix}-min-hits") == "3"
            assert not any("entries-per-key" in value for value in arguments)
            mode_arguments.append(arguments)
        assert mode_arguments[0] == mode_arguments[1]


def test_runtime_session_custom_template_is_removed_on_close_and_start_failure(
    monkeypatch,
):
    install_comfy_api_stub(monkeypatch)
    session_module = importlib.import_module("backend.nodes.llama_cpp_session")
    server_module = importlib.import_module("backend.backends.llama_cpp_server")
    monkeypatch.setattr(
        server_module,
        "_default_transport",
        lambda *_args, **_kwargs: (200, b'{"status":"ok"}'),
    )
    monkeypatch.setattr(
        session_module,
        "_resolve_llama_executable",
        lambda: ("llama.exe", "path"),
    )
    monkeypatch.setattr(
        session_module,
        "_supports_reasoning_preserve",
        lambda _executable, *, internal: True,
    )
    monkeypatch.setattr(
        session_module,
        "_resolve_file",
        lambda value, **_kwargs: value or None,
    )

    class Process:
        url = "http://127.0.0.1:45678"
        closed = False

        def close(self):
            self.closed = True

    process = Process()
    captured_arguments = []

    def start_server(_executable, arguments, *, internal, api_key=None):
        assert internal is False
        captured_arguments.append(arguments)
        return process

    monkeypatch.setattr(
        session_module, "start_owned_llama_server", start_server
    )
    monkeypatch.setattr(
        session_module,
        "list_server_models",
        lambda *, url, api_key=None: ["stub-model"],
    )

    values = {
        "model_path": ["external/model-a.gguf"],
        "mmproj_path": ["[none]"],
        "model_profile": [
            {
                "handler": "auto",
                "recommended_reasoning_mode": "auto",
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 40,
                "min_p": 0.05,
                "presence_penalty": 0.0,
                "repeat_penalty": 1.0,
            }
        ],
        "custom_chat_template": ["{% set custom = true %}"],
        "hardware_profile": None,
        "reasoning": None,
        "speculative": None,
        "n_ctx": [4096],
        "image_min_tokens": [0],
        "image_max_tokens": [0],
        "verbose": [False],
    }
    node_class = session_module.LlamaCppCreateRuntimeSessionNode
    session = node_class.execute(**values)[0]
    template_path = captured_arguments[0][
        captured_arguments[0].index("--chat-template-file") + 1
    ]
    assert os.path.isfile(template_path)
    with open(template_path, encoding="utf-8") as template_file:
        assert template_file.read() == "{% set custom = true %}"
    assert session.model == "stub-model"

    session.close()
    assert process.closed is True
    assert os.path.exists(template_path) is False

    def fail_start(_executable, arguments, *, internal, api_key=None):
        assert internal is False
        captured_arguments.append(arguments)
        raise RuntimeError("server start failed")

    monkeypatch.setattr(session_module, "start_owned_llama_server", fail_start)
    with pytest.raises(RuntimeError, match="server start failed"):
        node_class.execute(**values)
    failed_template_path = captured_arguments[1][
        captured_arguments[1].index("--chat-template-file") + 1
    ]
    assert os.path.exists(failed_template_path) is False


def import_llama_cpp_decision_nodes(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    for module_name in tuple(sys.modules):
        if module_name == "backend.nodes" or module_name.startswith("backend.nodes."):
            monkeypatch.delitem(sys.modules, module_name)
    return importlib.import_module("backend.nodes.llama_cpp_decision")


def test_llama_cpp_question_input_preserves_list_order(monkeypatch):
    decision_nodes = import_llama_cpp_decision_nodes(monkeypatch)
    from_input = decision_nodes.LlamaCppCreateQuestionFromInputNode
    listed = from_input.execute(["Which option?"], ["first", "second", "third"])[0]

    assert listed == {
        "question": "Which option?",
        "answer": ["first", "second", "third"],
    }
    with pytest.raises(InputNormalizationError, match="exactly one STRING"):
        from_input.execute(["one", "two"], ["first", "second"])
    with pytest.raises(InputNormalizationError, match="flat ComfyUI STRING list"):
        from_input.execute(["one"], [["first"], ["second"]])


def test_llama_cpp_question_payload_rejects_invalid_values(monkeypatch):
    decision_nodes = import_llama_cpp_decision_nodes(monkeypatch)
    make_payload = decision_nodes.make_question_payload

    invalid_values = [
        (" ", ["first", "second"], "non-empty string"),
        ("question", ["first"], "between 2 and 26"),
        ("question", ["first", "first"], "unique"),
        ("question", ["first", "  "], "non-empty strings"),
        ("question", ["first", 2], "must be strings"),
    ]
    for question, answers, message in invalid_values:
        with pytest.raises(InputNormalizationError, match=message):
            make_payload(question, answers)
    with pytest.raises(InputNormalizationError, match="between 2 and 26"):
        make_payload("question", [f"answer {index}" for index in range(27)])


def test_llama_cpp_decide_node_preserves_answer_labels_and_probability_order(
    monkeypatch,
):
    decision_nodes = import_llama_cpp_decision_nodes(monkeypatch)
    calls = []

    class FakeNativeSession:
        def decide(self, **values):
            calls.append(values)
            return "second option", {"second option": 0.7, "first option": 0.3}

    monkeypatch.setattr(decision_nodes, "LlamaCppSession", FakeNativeSession)
    session = FakeNativeSession()
    payload = {
        "question": "Choose",
        "answer": ["first option", "second option"],
    }
    result = decision_nodes.LlamaCppDecideSessionNode.execute(
        [session], ["system rules"], ["supporting context"], [payload]
    )

    assert result[0] == "second option"
    assert list(json.loads(result[1])) == ["first option", "second option"]
    assert result[2] is session
    assert calls == [
        {
            "question": "Choose",
            "context": "System:\nsystem rules\n\nContext:\nsupporting context",
            "answers": ["first option", "second option"],
        }
    ]
    with pytest.raises(InputNormalizationError, match="Create Native Session"):
        decision_nodes.LlamaCppDecideSessionNode.execute(
            [object()], [""], [""], [payload]
        )
