import asyncio
import importlib
import json
import os
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from backend.core import BackendError, InputNormalizationError


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

    def post(self, path):
        def register(handler):
            self.handlers[path] = handler
            return handler

        return register

    def get(self, path):
        def register(handler):
            self.handlers[path] = handler
            return handler

        return register


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
        if (
            module_name in {"backend.extension", "backend.routes"}
            or module_name.startswith("backend.nodes")
        ):
            monkeypatch.delitem(sys.modules, module_name)

    extension_module = importlib.import_module("backend.extension")
    extension = asyncio.run(extension_module.comfy_entrypoint())
    node_classes = asyncio.run(extension.get_node_list())
    schemas = [node_class.define_schema() for node_class in node_classes]

    assert isinstance(extension, ComfyExtension)
    assert [schema.node_id for schema in schemas] == [
        "OllamaImageList_Connectivity",
        "OllamaImageList_Options",
        "OllamaImageList_Generate",
        "OllamaImageList_MiniMaxSystemPromptPreset",
        "OllamaImageList_LlamaCppSamplingPreset",
        "OllamaImageList_LlamaCppGemma4RuntimePreset",
        "OllamaImageList_LlamaCppNGramSpeculativePreset",
        "OllamaImageList_LlamaCppModelProfile",
        "OllamaImageList_LlamaCppHardwareRuntimeProfile",
        "OllamaImageList_LlamaCppReasoningConfig",
        "OllamaImageList_LlamaCppNGramSpeculativeConfig",
        "OllamaImageList_LlamaCppNativeSpeculativeConfig",
        "OllamaImageList_LlamaCppProfiledGenerate",
        "OllamaImageList_LlamaCppSequentialGenerate",
        "OllamaImageList_LlamaCppGenerate",
        "OllamaImageList_LlamaCppMediaDiagnostics",
        "OllamaImageList_MuseGlimmerResponseParser",
        "OllamaImageList_CLIPGenerateText",
        "OllamaImageList_ReferenceDirector",
    ]
    assert [schema.display_name for schema in schemas] == [
        "Ollama Image List Connectivity",
        "Ollama Image List Options",
        "Ollama Generate (Image List)",
        "MiniMax System Prompt Preset",
        "Llama.cpp Sampling Preset",
        "Llama.cpp Gemma 4 Runtime Preset",
        "Llama.cpp N-gram Speculative Preset",
        "Llama.cpp Model Profile",
        "Llama.cpp Hardware Runtime Profile",
        "Llama.cpp Thinking / Reasoning Config",
        "Llama.cpp N-gram Speculative Config",
        "Llama.cpp Native Speculative Config (Compat)",
        "Llama.cpp Generate",
        "Llama.cpp Sequential Generate",
        "Llama.cpp Generate (Multimodal)",
        "Llama.cpp Media Diagnostics",
        "Muse Glimmer Response Parser",
        "CLIP Generate Text (Image List)",
        "Reference Director",
    ]
    assert [schema.category for schema in schemas] == [
        "Ollama/Image List",
        "Ollama/Image List",
        "Ollama/Image List",
        "Ollama/prompt",
        "Ollama/llama_cpp/legacy",
        "Ollama/llama_cpp/legacy",
        "Ollama/llama_cpp/legacy",
        "Ollama/llama_cpp/compact",
        "Ollama/llama_cpp/compact",
        "Ollama/llama_cpp/compact",
        "Ollama/llama_cpp/compact",
        "Ollama/llama_cpp/experimental",
        "Ollama/llama_cpp/compact",
        "Ollama/llama_cpp/compact",
        "Ollama/llama_cpp/legacy",
        "Ollama/llama_cpp/utils",
        "Ollama/llama_cpp/utils",
        "Ollama/CLIP",
        "Ollama/Multimodal",
    ]
    assert routes.handlers.keys() == {
        "/ollama_image_list/models",
        "/ollama_multimodal/reference_director/upload",
        "/ollama_multimodal/reference_director/metadata",
        "/ollama_multimodal/reference_director/image_proxy",
        "/ollama_multimodal/reference_director/waveform",
        "/ollama_multimodal/reference_director/apply_edit",
        "/ollama_multimodal/reference_director/cache/{kind}/{filename}",
    }

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
    base_prompt = minimax_module.BASE_PROMPT_PATH.read_text(
        encoding="utf-8"
    ).rstrip("\r\n")
    for prompt_type in ("I2V", "FL2V", "FL2V_LOOP", "T2V", "L2V"):
        type_prompt = (
            minimax_module.PRESETS_DIRECTORY / f"PROMPT_{prompt_type}.md"
        ).read_text(encoding="utf-8").lstrip("\r\n")
        assert minimax_class.execute(prompt_type) == (
            f"{base_prompt}\n\n{type_prompt}",
        )
    reference_base_prompt = minimax_module.REFERENCE_BASE_PROMPT_PATH.read_text(
        encoding="utf-8"
    ).rstrip("\r\n")
    for prompt_type in ("R2V", "R2I", "R2A"):
        type_prompt = (
            minimax_module.PRESETS_DIRECTORY / f"PROMPT_{prompt_type}.md"
        ).read_text(encoding="utf-8").lstrip("\r\n")
        assert minimax_class.execute(prompt_type) == (
            f"{reference_base_prompt}\n\n{type_prompt}",
        )
    assert minimax_class.execute("I2V", "R2A") == minimax_class.execute("R2A")
    with pytest.raises(
        ValueError,
        match="Unknown MiniMax prompt preset 'invalid'.*I2V.*R2A.*L2V",
    ):
        minimax_class.execute("I2V", "invalid")

    muse_class, muse_schema = registered[
        "OllamaImageList_MuseGlimmerResponseParser"
    ]
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
    assert [field.name for field in options_schema.outputs] == ["options", "options_json"]
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
    assert generate_input_names.index("options") < generate_input_names.index("options_json")
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
    assert generate_input_names.index("unload_after_response") + 1 == generate_input_names.index(
        "keep_alive"
    )

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
    assert sampling_schema.outputs[0].data_type == "OLLAMA_IMAGE_LIST_LLAMA_CPP_SAMPLING"
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
        assert runtime_module.normalize_gemma4_runtime(advanced_runtime) == advanced_runtime
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
        "ngram_sync_check_tokens",
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
    assert ngram_inputs["ngram_sync_check_tokens"].options["default"] == 16
    assert ngram_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_NGRAM_SPECULATIVE"
    )
    assert ngram_class.execute("off", 0, 0, "invalid", 0, 0, 0) == (
        {"speculative_mode": "off"},
    )
    ngram_configuration = ngram_class.execute("ngram", 3, 10, "k", 2, 0, 16)[0]
    assert ngram_configuration == {
        "speculative_mode": "ngram",
        "ngram_size": 3,
        "num_pred_tokens": 10,
        "ngram_min_hits": 2,
        "ngram_max_entries_per_key": None,
        "ngram_sync_check_tokens": 16,
        "ngram_mode": "k",
    }
    ngram_module = importlib.import_module(
        "backend.nodes.llama_cpp_ngram_speculative"
    )
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
        "Gemma 4 Vision",
        "Muse Glimmer",
        "Qwen 3.5 Thinking",
        "Qwen 3.5 Non-thinking",
        "Qwen 3 VL",
        "Custom",
    ]
    assert all(
        field.options["advanced"] is True
        for field in compact_profile_schema.inputs[1:]
    )
    assert compact_profile_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE"
    )
    model_profile_defaults = {
        field.name: field.options["default"]
        for field in compact_profile_schema.inputs
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
        **{**model_profile_defaults, "profile": "Qwen 3.5 Thinking"}
    )[0]
    assert qwen35_thinking_profile["recommended_reasoning_mode"] == "on"
    assert qwen35_thinking_profile["temperature"] == 1.0
    assert qwen35_thinking_profile["top_p"] == 0.95
    assert qwen35_thinking_profile["top_k"] == 20
    assert qwen35_thinking_profile["min_p"] == 0.0
    assert qwen35_thinking_profile["presence_penalty"] == 1.5
    qwen35_non_thinking_profile = compact_profile_class.execute(
        **{**model_profile_defaults, "profile": "Qwen 3.5 Non-thinking"}
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
        "Automatic Offload",
        "CPU",
        "Custom",
    ]
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
    assert reasoning_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_REASONING_CONFIG"
    )
    auto_reasoning = reasoning_class.execute("auto", "xhigh", 2048)[0]
    assert auto_reasoning == {
        "reasoning_mode": "auto",
        "reasoning_effort": "auto",
        "max_reasoning_tokens": 0,
    }
    off_reasoning = reasoning_class.execute("off", "high", 1024)[0]
    assert off_reasoning == (
        {
            "reasoning_mode": "off",
            "reasoning_effort": "auto",
            "max_reasoning_tokens": 0,
        }
    )
    muse_reasoning = reasoning_class.execute("on", "high", 1024)[0]
    assert muse_reasoning == {
        "reasoning_mode": "on",
        "reasoning_effort": "high",
        "max_reasoning_tokens": 1024,
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
        "ngram_sync_check_tokens",
    ]
    assert compact_ngram_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
    )
    assert compact_ngram_class.execute("off", 3, 10, "k", 2, 8, 16) == (
        {"kind": "off"},
    )
    compact_ngram_config = compact_ngram_class.execute(
        "ngram", 3, 10, "k", 2, 0, 16
    )[0]
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
        "Muse Glimmer DFlash",
        "Generic DFlash",
        "Generic DSpark",
        "Gemma 4 External MTP",
        "Qwen 3.5 Internal MTP",
        "Custom",
    ]
    assert native_config_schema.outputs[0].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
    )
    off_draft_config = native_config_class.execute(
        "Off",
        "stale/draft.gguf",
        "draft-dspark",
        "off",
        2,
        0,
        0.0,
    )[0]
    assert off_draft_config == {"kind": "off"}
    muse_draft_config = native_config_class.execute(
        "Muse Glimmer DFlash",
        "external/mtp-model-a.gguf",
        "draft-dspark",
        "off",
        2,
        0,
        0.0,
    )[0]
    assert muse_draft_config == {
        "kind": "native",
        "config": {
            "spec_type": "draft-dflash",
            "mtp_provider": "off",
            "draft_model": "external/mtp-model-a.gguf",
            "spec_n_max": 16,
            "spec_n_min": 0,
            "spec_p_min": 0.0,
        },
    }
    internal_mtp_config = native_config_class.execute(
        "Qwen 3.5 Internal MTP",
        "stale/draft.gguf",
        "draft-dflash",
        "off",
        2,
        0,
        0.0,
    )[0]
    assert internal_mtp_config["kind"] == "native"
    assert internal_mtp_config["config"]["draft_model"] == "[none]"

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
        "verbose",
    ]
    assert compact_inputs["model_profile"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_MODEL_PROFILE"
    )
    assert compact_inputs["hardware_profile"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_HARDWARE_RUNTIME_PROFILE"
    )
    assert compact_inputs["hardware_profile"].options["optional"] is True
    assert compact_inputs["image_max_tokens"].options["default"] == 0
    assert compact_inputs["reasoning"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_REASONING_CONFIG"
    )
    assert compact_inputs["reasoning"].options["optional"] is True
    assert compact_inputs["speculative"].data_type == (
        "OLLAMA_IMAGE_LIST_LLAMA_CPP_SPECULATIVE_CONFIG"
    )
    assert compact_inputs["speculative"].options["optional"] is True

    sequential_class, sequential_schema = registered[
        "OllamaImageList_LlamaCppSequentialGenerate"
    ]
    assert compact_class not in sequential_class.__mro__[1:]
    assert sequential_schema.is_input_list is True
    assert sequential_schema.not_idempotent is True
    assert [field.name for field in sequential_schema.inputs] == [
        field.name for field in compact_schema.inputs
    ]
    assert [field.name for field in sequential_schema.outputs] == [
        field.name for field in compact_schema.outputs
    ]
    assert all(
        field.options["is_output_list"] is True
        for field in sequential_schema.outputs
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
    assert llama_schema.inputs[-2].name == "reasoning_strength"
    assert llama_schema.inputs[-1].name == "reasoning_budget"
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
    speculative_inputs = {
        field.name: field for field in speculative_schema.inputs
    }
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
        "external_gemma4",
        "internal_qwen35",
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
    assert sequential_output[1] == [""]
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
        image_max_tokens=[0],
        reasoning=[muse_reasoning],
        speculative=[compact_ngram_config],
    )
    compact_output = compact_class.execute(**compact_values)
    assert compact_output[0] == "done"
    assert captured_speculative_call["handler"] == "auto"
    assert captured_speculative_call["reasoning_strength"] == "high"
    assert captured_speculative_call["n_ctx"] == 32768
    assert captured_speculative_call["max_tokens"] == 4096
    assert captured_speculative_call["thinking"] is True
    assert captured_speculative_call["reasoning_strength"] == "high"
    assert captured_speculative_call["reasoning_budget"] == 1024
    assert captured_speculative_call["temperature"] == 1.0
    assert captured_speculative_call["presence_penalty"] == 0.0
    assert captured_speculative_call["n_batch"] == 512
    assert captured_speculative_call["gpu_layers"] == "all"
    assert captured_speculative_call["main_gpu"] == 0
    assert captured_speculative_call["n_threads"] == 0
    assert captured_speculative_call["flash_attention"] == "auto"
    assert captured_speculative_call["use_mmap"] is True
    assert captured_speculative_call["override_n_ubatch"] is False
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
    compact_qwen35_non_thinking_values["model_profile"] = [
        qwen35_non_thinking_profile
    ]
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
        raise AssertionError("an off Compact config imported the speculative dependency")

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
        image_max_tokens=[768],
        speculative=[muse_draft_config],
    )
    monkeypatch.setattr(
        compact_module,
        "require_native_speculative",
        lambda: speculative_binding,
    )
    compact_native_output = compact_class.execute(**compact_native_values)
    assert compact_native_output[0] == "done"
    assert captured_speculative_call["draft_model_path"] == (
        "D:/SharedModels/LLM/external/mtp-model-a.gguf"
    )
    assert captured_speculative_call["spec_type"] == "draft-dflash"
    assert captured_speculative_call["spec_n_max"] == 16
    assert captured_speculative_call["speculative_class"] is speculative_binding
    assert captured_speculative_call["override_n_ubatch"] is True
    assert captured_speculative_call["n_ubatch"] == 1024
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
    assert "speculative_class" not in captured_speculative_call

    monkeypatch.setattr(
        speculative_module,
        "require_native_speculative",
        lambda: speculative_binding,
    )
    captured_speculative_call.clear()
    speculative_values.update(
        draft_model=["external/mtp-model-a.gguf"],
        spec_type=["draft-dflash"],
        mtp_provider=["internal_qwen35"],
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
    assert captured_speculative_call["speculative_class"] is speculative_binding
    assert "ngram_speculative" not in captured_speculative_call

    captured_speculative_call.clear()
    speculative_values.update(
        draft_model=["[none]"],
        spec_type=["draft-mtp"],
        mtp_provider=["internal_qwen35"],
    )
    speculative_output = speculative_class.execute(**speculative_values)
    assert speculative_output[0] == "done"
    assert captured_speculative_call["draft_model_path"] == ""
    assert captured_speculative_call["mtp_provider"] == "internal_qwen35"

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
        override_image_max_tokens=[False],
        image_max_tokens=[2048],
        runtime=None,
    ) == {
        "n_batch": 512,
        "override_n_ubatch": False,
        "n_ubatch": 2048,
        "override_image_max_tokens": False,
        "image_max_tokens": 2048,
    }
    assert llama_module._resolve_runtime_values(
        n_batch=[512],
        override_n_ubatch=[False],
        n_ubatch=[512],
        override_image_max_tokens=[False],
        image_max_tokens=[1120],
        runtime=[runtime_class.execute("Vision Long / Thinking")[0]],
    ) == {
        "n_batch": 512,
        "override_n_ubatch": True,
        "n_ubatch": 512,
        "override_image_max_tokens": True,
        "image_max_tokens": 512,
    }
    assert llama_module._resolve_gguf_selection(
        "external/model-a.gguf", label="model GGUF", required=True
    ) == "D:/SharedModels/LLM/external/model-a.gguf"
    assert llama_module._resolve_gguf_selection(
        "[none]", label="mmproj GGUF", required=False
    ) == ""
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
