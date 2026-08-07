import asyncio
import importlib
import json
import os
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from backend.core import InputNormalizationError


@dataclass(frozen=True)
class Field:
    direction: str
    data_type: str
    name: str
    options: dict


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


class Routes:
    def __init__(self):
        self.handlers = {}

    def post(self, path):
        def register(handler):
            self.handlers[path] = handler
            return handler

        return register


def install_comfy_api_stub(monkeypatch):
    io = SimpleNamespace(
        Audio=field_type("audio"),
        Boolean=field_type("boolean"),
        Combo=field_type("combo"),
        ComfyNode=ComfyNode,
        Custom=Custom,
        Float=field_type("float"),
        Image=field_type("image"),
        Int=field_type("int"),
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
        "OllamaImageList_LlamaCppSamplingPreset",
        "OllamaImageList_LlamaCppGemma4RuntimePreset",
        "OllamaImageList_LlamaCppGenerate",
        "OllamaImageList_LlamaCppMediaDiagnostics",
    ]
    assert [schema.display_name for schema in schemas] == [
        "Ollama Image List Connectivity",
        "Ollama Image List Options",
        "Ollama Generate (Image List)",
        "Llama.cpp Sampling Preset",
        "Llama.cpp Gemma 4 Runtime Preset",
        "Llama.cpp Generate (Multimodal)",
        "Llama.cpp Media Diagnostics",
    ]
    assert [schema.category for schema in schemas] == [
        "Ollama/Image List",
        "Ollama/Image List",
        "Ollama/Image List",
        "Ollama/llama_cpp",
        "Ollama/llama_cpp",
        "Ollama/llama_cpp",
        "Ollama/llama_cpp",
    ]
    assert routes.handlers.keys() == {"/ollama_image_list/models"}

    registered = {
        schema.node_id: (node_class, schema)
        for node_class, schema in zip(node_classes, schemas, strict=True)
    }

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

    llama_schema = registered["OllamaImageList_LlamaCppGenerate"][1]
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

    llama_module = importlib.import_module("backend.nodes.llama_cpp_generate")
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
