import copy
import json

import pytest

from backend.core.reference_contract import (
    ReferenceContractError,
    execution_fingerprint,
    execution_projection,
    parse_reference_state,
)
from backend.core.reference_manifest import (
    build_reference_manifest,
    build_reference_output_plan,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def director_state():
    return {
        "version": 1,
        "items": {
            "img-a": {
                "id": "img-a",
                "kind": "image",
                "source": {
                    "path": f"reference_director/sources/{HASH_A}.png",
                    "mime": "image/png",
                    "sha256": HASH_A,
                    "size": 123,
                },
                "caption": "image caption",
                "visualEnabled": True,
                "edit": {
                    "crop": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.7},
                    "flipX": True,
                    "removeBackground": True,
                    "background": {"mode": "transparent", "color": "#FFFFFF"},
                    "mask": {
                        "path": f"reference_director/sources/{HASH_D}.png",
                        "mime": "image/png",
                        "sha256": HASH_D,
                    },
                    "maskMode": "keep",
                    "revision": 2,
                },
            },
            "aud-b": {
                "id": "aud-b",
                "kind": "audio",
                "source": {
                    "path": f"reference_director/sources/{HASH_B}.wav",
                    "mime": "audio/wav",
                    "sha256": HASH_B,
                },
                "caption": "disabled audio",
                "audioEnabled": False,
                "crop": {"start": 0.25, "end": 1.5},
            },
            "vid-c": {
                "id": "vid-c",
                "kind": "video",
                "source": {
                    "path": f"reference_director/sources/{HASH_C}.mp4",
                    "mime": "video/mp4",
                    "sha256": HASH_C,
                },
                "caption": "video caption",
                "audioCaptionOverride": "video audio caption",
                "visualEnabled": False,
                "audioEnabled": True,
                "crop": {"start": 1.0, "end": 3.0},
            },
        },
        "visualOrder": ["vid-c", "img-a"],
        "audioOrder": ["aud-b", "vid-c"],
        "videoAudioPolicy": "preserve",
        "ui": {
            "cardAspectRatio": "4 / 3",
            "previewMaxPixels": 1_000_000,
            "waveformPeaks": 300,
        },
    }


def test_contract_projection_is_deterministic_and_excludes_ui_state():
    first = director_state()
    second = copy.deepcopy(first)
    second["ui"] = {"cardAspectRatio": "1 / 1", "previewMaxPixels": 10}

    parsed = parse_reference_state(json.dumps(first))
    assert execution_fingerprint(parsed) == execution_fingerprint(
        parse_reference_state(second)
    )
    projection = execution_projection(parsed)
    assert "ui" not in projection
    assert [item["id"] for item in projection["images"]] == ["img-a"]
    assert [item["id"] for item in projection["videos"]] == ["vid-c"]
    assert [item["id"] for item in projection["audios"]] == [
        "aud-b",
        "vid-c:audio",
    ]
    assert projection["audios"][1]["derivedFrom"] == "vid-c"
    assert projection["images"][0]["edit"]["mask"]["sha256"] == HASH_D
    assert projection["images"][0]["edit"]["removeBackground"] is True


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda state: state["items"]["img-a"]["source"].update(path="../secret.png"), "path"),
        (lambda state: state.update(visualOrder=["img-a", "img-a"]), "duplicate"),
        (lambda state: state.update(audioOrder=["aud-b"]), "missing"),
        (
            lambda state: state["items"]["vid-c"].update(
                crop={"start": 3.0, "end": 2.0}
            ),
            "start < end",
        ),
        (lambda state: state["items"]["img-a"].update(id="other"), "map key"),
    ],
)
def test_contract_rejects_invalid_paths_orders_ids_and_crops(mutate, match):
    state = director_state()
    mutate(state)
    with pytest.raises(ReferenceContractError, match=match):
        parse_reference_state(state)


def test_manifest_keeps_disabled_items_and_aligns_active_ids_and_captions():
    state = parse_reference_state(director_state())
    plan = build_reference_output_plan(state)
    manifest = build_reference_manifest(state)

    assert plan.image_ids == ("img-a",)
    assert plan.image_captions == ("image caption",)
    assert plan.audio_ids == ("vid-c:audio",)
    assert plan.audio_captions == ("video audio caption",)
    assert plan.video_ids == ()
    assert manifest["visual_order"] == ["vid-c", "img-a"]
    assert manifest["audio_order"] == ["aud-b", "vid-c"]
    assert manifest["outputs"] == {
        "images": ["img-a"],
        "audios": ["vid-c:audio"],
        "videos": [],
    }
    assert manifest["items"]["aud-b"]["enabled"] == {"audio": False}
    assert manifest["items"]["vid-c:audio"]["derived_from"] == "vid-c"
    assert manifest["items"]["img-a"]["edit"]["maskMode"] == "keep"
    serialized = json.dumps(manifest)
    assert "payload" not in serialized
    assert "C:\\" not in serialized


def test_contract_requires_a_safe_image_descriptor_for_edit_masks():
    state = director_state()
    state["items"]["img-a"]["edit"]["mask"]["path"] = "../mask.png"
    with pytest.raises(ReferenceContractError, match="mask.path"):
        parse_reference_state(state)

    state = director_state()
    state["items"]["img-a"]["edit"]["mask"].pop("mime")
    with pytest.raises(ReferenceContractError, match="mask.mime"):
        parse_reference_state(state)
