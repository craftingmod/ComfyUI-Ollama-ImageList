import struct

import pytest

from backend.core import (
    InputNormalizationError,
    MediaLimits,
    normalize_audio,
    normalize_images,
    normalize_media,
    normalize_video,
    unwrap_optional_scalar,
    unwrap_required_scalar,
)
from tests.backend.tensor_stub import VideoInputStub, silent_audio, solid_image


def png_dimensions(payload: bytes) -> tuple[int, int]:
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", payload[16:24])


def test_flattens_heterogeneous_lists_and_batches_in_stable_order():
    first = solid_image(2, 2, 3, 3, 0.25)
    second = solid_image(1, 4, 1, 4, 0.75)

    bundle = normalize_images([[first], second])

    assert [item.index for item in bundle.items] == [0, 1, 2]
    assert [png_dimensions(item.payload) for item in bundle.items] == [(3, 2), (3, 2), (1, 4)]
    assert [(item.metadata["width"], item.metadata["height"]) for item in bundle.items] == [
        (3, 2),
        (3, 2),
        (1, 4),
    ]
    assert [item.metadata["channels"] for item in bundle.items] == [3, 3, 4]
    assert len({item.metadata["sha256"] for item in bundle.items}) == 2


def test_rejects_invalid_channels_before_transport():
    with pytest.raises(InputNormalizationError, match="expected 1, 3, or 4"):
        normalize_images(solid_image(1, 2, 2, 2, 0.5))


def test_rejects_image_count_and_pixel_limit_violations():
    with pytest.raises(InputNormalizationError, match="Image count"):
        normalize_images(solid_image(2, 1, 1, 3, 0.0), limits=MediaLimits(max_images=1))

    with pytest.raises(InputNormalizationError, match="pixel limit"):
        normalize_images(
            solid_image(1, 2, 2, 3, 0.0),
            limits=MediaLimits(max_pixels_per_image=3),
        )


def test_audio_batch_becomes_independent_pcm16_wav_items():
    bundle = normalize_audio(
        {"waveform": silent_audio(2, 1, 80), "sample_rate": 16_000}
    )

    assert len(bundle.items) == 2
    assert all(item.payload.startswith(b"RIFF") for item in bundle.items)
    assert all(item.payload[8:12] == b"WAVE" for item in bundle.items)
    assert [item.metadata["duration_seconds"] for item in bundle.items] == [0.005, 0.005]


def test_video_input_preserves_encoded_stream_and_metadata():
    video = VideoInputStub(b"fake-mp4-payload")
    video.stream.seek(4)

    bundle = normalize_video([video])

    assert video.stream.tell() == 4
    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert item.kind == "video"
    assert item.mime_type == "video/mp4"
    assert item.payload == b"fake-mp4-payload"
    assert item.metadata["duration_seconds"] == 1.0
    assert item.metadata["frame_count"] == 24
    assert item.metadata["frame_rate"] == 24.0
    assert (item.metadata["width"], item.metadata["height"]) == (640, 360)
    assert bundle.manifest()["video_count"] == 1


def test_combined_media_keeps_existing_order_and_appends_video():
    bundle = normalize_media(
        images=solid_image(1, 1, 1, 3, 0.5),
        audio={"waveform": silent_audio(1, 1, 8), "sample_rate": 8_000},
        video=VideoInputStub(b"video"),
    )

    assert [item.kind for item in bundle.items] == ["image", "audio", "video"]
    assert bundle.manifest()["video_count"] == 1


def test_scalar_unwrapping_never_silently_selects_from_a_data_list():
    assert unwrap_required_scalar("model", ["gemma3"]) == "gemma3"
    assert unwrap_optional_scalar("think", None, "off") == "off"
    with pytest.raises(InputNormalizationError, match="exactly one"):
        unwrap_required_scalar("prompt", ["first", "second"])
