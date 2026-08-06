import asyncio
import importlib
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


class Custom(FieldType):
    def __init__(self, name):
        self.data_type = name


class Schema:
    def __init__(self, **values):
        self.__dict__.update(values)


class ComfyNode:
    pass


class ComfyExtension:
    pass


def install_comfy_api_stub(monkeypatch):
    io = SimpleNamespace(
        Audio=field_type("audio"),
        Boolean=field_type("boolean"),
        Combo=field_type("combo"),
        ComfyNode=ComfyNode,
        Custom=Custom,
        Image=field_type("image"),
        Int=field_type("int"),
        NodeOutput=tuple,
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


def test_extension_registers_both_v3_node_schemas(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    for module_name in tuple(sys.modules):
        if module_name == "backend.extension" or module_name.startswith("backend.nodes"):
            monkeypatch.delitem(sys.modules, module_name)

    extension_module = importlib.import_module("backend.extension")
    extension = asyncio.run(extension_module.comfy_entrypoint())
    node_classes = asyncio.run(extension.get_node_list())
    schemas = [node_class.define_schema() for node_class in node_classes]

    assert isinstance(extension, ComfyExtension)
    assert [schema.node_id for schema in schemas] == [
        "OllamaMultimodal_MediaBundle",
        "OllamaMultimodal_Generate",
    ]
    assert all(schema.is_input_list for schema in schemas)
