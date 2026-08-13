import importlib
import json
import sys

import pytest

from tests.backend.test_extension_registration import install_comfy_api_stub


def load_node_module(monkeypatch):
    install_comfy_api_stub(monkeypatch)
    for name in tuple(sys.modules):
        if name == "backend.nodes" or name.startswith("backend.nodes."):
            monkeypatch.delitem(sys.modules, name)
    return importlib.import_module("backend.nodes.reference_director")


def test_reference_director_schema_and_aligned_execute(monkeypatch):
    module = load_node_module(monkeypatch)
    schema = module.ReferenceDirectorNode.define_schema()
    assert schema.node_id == "OllamaImageList_ReferenceDirector"
    assert [field.name for field in schema.inputs] == ["director_state"]
    assert schema.inputs[0].options["extra_dict"] == {
        "widgetType": "OLLAMA_REFERENCE_DIRECTOR"
    }
    assert [field.name for field in schema.outputs] == [
        "images",
        "image_captions",
        "audios",
        "audio_captions",
        "videos",
        "video_captions",
        "manifest_json",
    ]
    assert [field.options.get("is_output_list", False) for field in schema.outputs] == [
        True,
        True,
        True,
        True,
        True,
        True,
        False,
    ]

    state = {
        "version": 1,
        "items": {
            "img": {
                "id": "img",
                "kind": "image",
                "source": {
                    "path": "reference_director/sources/image.png",
                    "mime": "image/png",
                    "sha256": "a" * 64,
                },
                "caption": "caption",
                "visualEnabled": True,
            }
        },
        "visualOrder": ["img"],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
        "ui": {"previewMaxPixels": 1},
    }
    loaded_type = importlib.import_module(
        "backend.core.reference_media"
    ).LoadedReferenceMedia
    monkeypatch.setattr(
        module,
        "load_reference_media",
        lambda _state: loaded_type(images=("native-image",)),
    )
    output = module.ReferenceDirectorNode.execute(json.dumps(state))
    assert output[:6] == (
        ["native-image"],
        ["caption"],
        [],
        [],
        [],
        [],
    )
    assert json.loads(output[6])["outputs"]["images"] == ["img"]


def test_reference_director_rejects_loader_alignment_mismatch(monkeypatch):
    module = load_node_module(monkeypatch)
    loaded_type = importlib.import_module(
        "backend.core.reference_media"
    ).LoadedReferenceMedia
    monkeypatch.setattr(
        module,
        "load_reference_media",
        lambda _state: loaded_type(images=("unexpected",)),
    )
    with pytest.raises(ValueError, match="IMAGE count"):
        module.ReferenceDirectorNode.execute(module.EMPTY_DIRECTOR_STATE_JSON)


def test_fingerprint_strongly_validates_sources_before_returning_cache_key(
    monkeypatch,
):
    module = load_node_module(monkeypatch)
    calls = []
    monkeypatch.setattr(
        module,
        "validate_reference_sources",
        lambda state: calls.append(state),
    )

    fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON
    )

    assert len(fingerprint) == 64
    assert len(calls) == 1
