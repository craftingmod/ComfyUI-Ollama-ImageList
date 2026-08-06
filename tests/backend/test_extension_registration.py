import asyncio
import importlib
import json
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace


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
    )
    comfy_api = ModuleType("comfy_api")
    versioned_api = ModuleType("comfy_api.v0_0_2")
    versioned_api.ComfyExtension = ComfyExtension
    versioned_api.io = io
    comfy_api.v0_0_2 = versioned_api
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_api)
    monkeypatch.setitem(sys.modules, "comfy_api.v0_0_2", versioned_api)

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
    ]
    assert [schema.display_name for schema in schemas] == [
        "Ollama Image List Connectivity",
        "Ollama Image List Options",
        "Ollama Generate (Image List)",
    ]
    assert {schema.category for schema in schemas} == {"Ollama/Image List"}
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
