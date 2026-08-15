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
    assert [field.name for field in schema.inputs] == [
        "director_state",
        "limit_image_pixels",
        "max_image_pixels",
        "composite_alpha",
        "alpha_background",
        "grid_columns",
        "preview_pixels",
        "show_captions",
        "card_aspect",
        "preview_fit",
        "waveform_pairs",
    ]
    assert schema.inputs[0].options["extra_dict"] == {
        "widgetType": "OLLAMA_REFERENCE_DIRECTOR"
    }
    limit_image_pixels = schema.inputs[1]
    assert limit_image_pixels.data_type == "boolean"
    assert limit_image_pixels.options["default"] is False
    assert limit_image_pixels.options["label_off"] == "Original"
    assert limit_image_pixels.options["label_on"] == "Limited"
    assert limit_image_pixels.options["advanced"] is True
    assert limit_image_pixels.options["socketless"] is False
    max_image_pixels = schema.inputs[2]
    assert max_image_pixels.data_type == "float"
    assert max_image_pixels.options["display_name"] == "max_image_pixels (MPixel)"
    assert max_image_pixels.options["default"] == 2.0
    assert max_image_pixels.options["min"] == 0.25
    assert max_image_pixels.options["max"] == 40.0
    assert max_image_pixels.options["advanced"] is True
    assert max_image_pixels.options["socketless"] is False
    composite_alpha = schema.inputs[3]
    assert composite_alpha.data_type == "boolean"
    assert composite_alpha.options["default"] is False
    assert composite_alpha.options["label_off"] == "Preserve"
    assert composite_alpha.options["label_on"] == "Opaque"
    assert composite_alpha.options["advanced"] is True
    assert composite_alpha.options["socketless"] is False
    alpha_background = schema.inputs[4]
    assert alpha_background.data_type == "color"
    assert alpha_background.options["default"] == "#000000"
    assert alpha_background.options["advanced"] is True
    assert alpha_background.options["socketless"] is False
    grid_columns = schema.inputs[5]
    assert grid_columns.data_type == "int"
    assert grid_columns.options["display_name"] == "grid_columns"
    assert grid_columns.options["default"] == 3
    assert grid_columns.options["advanced"] is True
    assert grid_columns.options["socketless"] is True
    preview_pixels = schema.inputs[6]
    assert preview_pixels.data_type == "float"
    assert preview_pixels.options["display_name"] == "preview_pixels (MPixel)"
    assert preview_pixels.options["default"] == 1.0
    assert preview_pixels.options["advanced"] is True
    assert preview_pixels.options["socketless"] is True
    show_captions = schema.inputs[7]
    assert show_captions.data_type == "boolean"
    assert show_captions.options["display_name"] == "show_captions"
    assert show_captions.options["default"] is True
    assert show_captions.options["advanced"] is True
    assert show_captions.options["socketless"] is True
    card_aspect = schema.inputs[8]
    assert card_aspect.data_type == "combo"
    assert card_aspect.options["display_name"] == "card_aspect"
    assert card_aspect.options["options"] == [
        "1 / 1",
        "4 / 3",
        "3 / 4",
        "16 / 9",
        "9 / 16",
    ]
    assert card_aspect.options["default"] == "4 / 3"
    assert card_aspect.options["advanced"] is True
    assert card_aspect.options["socketless"] is True
    preview_fit = schema.inputs[9]
    assert preview_fit.data_type == "combo"
    assert preview_fit.options["display_name"] == "preview_fit"
    assert preview_fit.options["options"] == ["contain", "cover"]
    assert preview_fit.options["default"] == "contain"
    assert preview_fit.options["advanced"] is True
    assert preview_fit.options["socketless"] is True
    waveform_pairs = schema.inputs[10]
    assert waveform_pairs.data_type == "int"
    assert waveform_pairs.options["display_name"] == "waveform_pairs"
    assert waveform_pairs.options["default"] == 300
    assert waveform_pairs.options["min"] == 100
    assert waveform_pairs.options["max"] == 1000
    assert waveform_pairs.options["step"] == 50
    assert waveform_pairs.options["advanced"] is True
    assert waveform_pairs.options["socketless"] is True
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
                "imageEnabled": True,
            }
        },
        "imageOrder": ["img"],
        "videoOrder": [],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
        "ui": {"previewMaxPixels": 1},
    }
    loaded_type = importlib.import_module(
        "backend.core.reference_media"
    ).LoadedReferenceMedia
    loaded_settings = []
    monkeypatch.setattr(
        module,
        "load_reference_media",
        lambda _state, **kwargs: loaded_settings.append(kwargs["image_output"])
        or loaded_type(images=("native-image",)),
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
    assert json.loads(output[6])["image_output"] == {
        "mode": "original",
        "alphaMode": "preserve",
    }
    assert loaded_settings[0].projection() == {
        "mode": "original",
        "alphaMode": "preserve",
    }
    limited_output = module.ReferenceDirectorNode.execute(
        json.dumps(state),
        limit_image_pixels=True,
        max_image_pixels=3.75,
    )
    assert json.loads(limited_output[6])["image_output"] == {
        "mode": "limited",
        "alphaMode": "preserve",
        "maxPixels": 3_750_000,
    }
    assert loaded_settings[1].projection() == {
        "mode": "limited",
        "alphaMode": "preserve",
        "maxPixels": 3_750_000,
    }
    opaque_output = module.ReferenceDirectorNode.execute(
        json.dumps(state),
        composite_alpha=True,
        alpha_background="#12345680",
    )
    assert json.loads(opaque_output[6])["image_output"] == {
        "mode": "original",
        "alphaMode": "opaque",
        "alphaBackground": "#123456",
    }


def test_reference_director_rejects_loader_alignment_mismatch(monkeypatch):
    module = load_node_module(monkeypatch)
    loaded_type = importlib.import_module(
        "backend.core.reference_media"
    ).LoadedReferenceMedia
    monkeypatch.setattr(
        module,
        "load_reference_media",
        lambda _state, **_kwargs: loaded_type(images=("unexpected",)),
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
    display_only_fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON,
        grid_columns=8,
        preview_pixels=16.0,
        show_captions=False,
        card_aspect="16 / 9",
        preview_fit="cover",
        waveform_pairs=1000,
    )
    inactive_max_fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON,
        max_image_pixels=40.0,
    )
    limited_fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON,
        limit_image_pixels=True,
        max_image_pixels=4.0,
    )
    inactive_background_fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON,
        alpha_background="#ffffff",
    )
    opaque_fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON,
        composite_alpha=True,
        alpha_background="#ffffff",
    )
    opaque_alpha_fingerprint = module.ReferenceDirectorNode.fingerprint_inputs(
        module.EMPTY_DIRECTOR_STATE_JSON,
        composite_alpha=True,
        alpha_background="#ffffff00",
    )

    assert len(fingerprint) == 64
    assert display_only_fingerprint == fingerprint
    assert inactive_max_fingerprint == fingerprint
    assert inactive_background_fingerprint == fingerprint
    assert limited_fingerprint != fingerprint
    assert opaque_fingerprint != fingerprint
    assert opaque_alpha_fingerprint == opaque_fingerprint
    assert len(calls) == 7
