import hashlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from backend.core import reference_background, reference_media
from backend.core.reference_contract import (
    ImageEdit,
    NormalizedCrop,
    ReferenceSource,
    TimeRange,
    parse_reference_state,
)


class FakeArray:
    ndim = 2

    def __init__(self, channels, samples=None, *, image_shape=None):
        self.shape = image_shape if image_shape is not None else (channels, samples)

    def reshape(self, *shape):
        self.shape = tuple(shape)
        return self

    @property
    def T(self):
        self.shape = tuple(reversed(self.shape))
        return self

    def __getitem__(self, index):
        channels, samples = self.shape
        sample_slice = index[1]
        start = sample_slice.start or 0
        stop = sample_slice.stop if sample_slice.stop is not None else samples
        return FakeArray(channels, stop - start)

    def __truediv__(self, _value):
        return self


class FakeTensor:
    def __init__(self, shape):
        self.shape = tuple(shape)

    def unsqueeze(self, index):
        shape = list(self.shape)
        shape.insert(index, 1)
        self.shape = tuple(shape)
        return self


def install_fake_numpy_and_torch(monkeypatch):
    numpy = ModuleType("numpy")
    numpy.float32 = object()
    numpy.asarray = lambda value, dtype=None: value
    numpy.array = lambda image, dtype=None, copy=None: FakeArray(
        0,
        image_shape=(image.height, image.width, 4 if image.mode == "RGBA" else 3),
    )

    def concatenate(values, axis):
        assert axis == 1
        return FakeArray(values[0].shape[0], sum(value.shape[1] for value in values))

    numpy.concatenate = concatenate
    numpy.ascontiguousarray = lambda value, dtype=None: value
    torch = ModuleType("torch")
    torch.from_numpy = lambda value: FakeTensor(value.shape)
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "torch", torch)


def install_fake_pillow(monkeypatch, operations):
    class FakeImage:
        def __init__(self, width=10, height=8, mode="RGB"):
            self.width = width
            self.height = height
            self.mode = mode
            self.info = {}

        @property
        def size(self):
            return self.width, self.height

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def load(self):
            operations.append("load")

        def copy(self):
            return self

        def close(self):
            operations.append("close")

        def getbands(self):
            return tuple(self.mode)

        def convert(self, mode):
            operations.append(("convert", mode))
            self.mode = mode
            return self

        def crop(self, box):
            operations.append(("crop", box))
            left, top, right, bottom = box
            self.width = right - left
            self.height = bottom - top
            return self

        def alpha_composite(self, foreground):
            operations.append(("alpha_composite", foreground.size))

        def getchannel(self, channel):
            operations.append(("getchannel", channel))
            return FakeImage(self.width, self.height, mode="L")

        def putalpha(self, alpha):
            operations.append(("putalpha", alpha.size))

        def resize(self, size, _resampling):
            operations.append(("resize", size))
            self.width, self.height = size
            return self

    image = SimpleNamespace(
        DecompressionBombWarning=RuntimeWarning,
        open=lambda _path: FakeImage(),
        new=lambda mode, size, _color: FakeImage(*size, mode=mode),
    )
    image_ops = SimpleNamespace(
        exif_transpose=lambda value: value,
        mirror=lambda value: operations.append("mirror") or value,
        flip=lambda value: operations.append("flip") or value,
    )
    image_color = SimpleNamespace(getcolor=lambda _color, _mode: (255, 255, 255, 255))
    image_chops = SimpleNamespace(
        multiply=lambda _alpha, mask: operations.append("mask-multiply") or mask
    )
    pil = ModuleType("PIL")
    pil.Image = image
    pil.ImageOps = image_ops
    pil.ImageColor = image_color
    pil.ImageChops = image_chops
    monkeypatch.setitem(sys.modules, "PIL", pil)


def test_optional_rembg_reports_a_focused_install_error(monkeypatch):
    monkeypatch.setattr(reference_background.importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(
        reference_background.ReferenceBackgroundRemovalUnavailable,
        match="optional.*rembg",
    ):
        reference_background.remove_reference_background(object())


def test_optional_rembg_reuses_one_lazy_session(monkeypatch):
    class FakeImage:
        size = (4, 2)

        def convert(self, _mode):
            return self

    sessions = []
    calls = []
    rembg = ModuleType("rembg")
    rembg.new_session = lambda: sessions.append(object()) or sessions[-1]
    rembg.remove = lambda image, *, session: calls.append((image, session)) or image
    monkeypatch.setattr(reference_background.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(reference_background, "_SESSION", None)
    monkeypatch.setitem(sys.modules, "rembg", rembg)

    image = FakeImage()
    assert reference_background.remove_reference_background(image) is image
    assert reference_background.remove_reference_background(image) is image
    assert len(sessions) == 1
    assert calls == [(image, sessions[0]), (image, sessions[0])]


def test_resolver_verifies_input_boundary_size_and_hash(tmp_path):
    media = tmp_path / "reference_director" / "sources" / "source.bin"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"reference")
    digest = hashlib.sha256(b"reference").hexdigest()
    source = ReferenceSource(
        path="reference_director/sources/source.bin",
        mime="image/png",
        sha256=digest,
        size=len(b"reference"),
    )
    assert reference_media.resolve_reference_source(source, input_root=tmp_path) == media

    stale = ReferenceSource(source.path, source.mime, "0" * 64, source.size)
    with pytest.raises(reference_media.ReferenceMediaError, match="hash"):
        reference_media.resolve_reference_source(stale, input_root=tmp_path)


def test_resolver_enforces_actual_file_size_when_descriptor_omits_size(
    monkeypatch, tmp_path
):
    assert reference_media.MAX_REFERENCE_SOURCE_BYTES == 256 * 1024 * 1024
    media = tmp_path / "oversized.bin"
    payload = b"123456789"
    media.write_bytes(payload)
    source = ReferenceSource(
        path="oversized.bin",
        mime="audio/wav",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=None,
    )
    monkeypatch.setattr(reference_media, "MAX_REFERENCE_SOURCE_BYTES", 8)

    with pytest.raises(reference_media.ReferenceMediaError, match="256 MiB"):
        reference_media.resolve_reference_source(source, input_root=tmp_path)


def test_image_loader_applies_crop_flip_and_solid_background(monkeypatch):
    operations = []
    install_fake_pillow(monkeypatch, operations)
    install_fake_numpy_and_torch(monkeypatch)
    source = ReferenceSource("reference_director/sources/a.png", "image/png", "a" * 64)
    edit = ImageEdit(
        crop=NormalizedCrop(0.1, 0.25, 0.5, 0.5),
        flip_x=True,
        background_mode="solid",
        background_color="#ffffff",
    )
    tensor = reference_media._load_image(Path("unused"), source, edit)
    assert tensor.shape == (1, 4, 5, 3)
    assert ("crop", (1, 2, 6, 6)) in operations
    assert "mirror" in operations
    assert any(operation[0] == "alpha_composite" for operation in operations if isinstance(operation, tuple))


def test_image_loader_runs_optional_background_removal_before_other_edits(monkeypatch):
    operations = []
    install_fake_pillow(monkeypatch, operations)
    install_fake_numpy_and_torch(monkeypatch)
    monkeypatch.setattr(
        reference_media,
        "remove_reference_background",
        lambda image: operations.append("remove-background") or image,
    )
    source = ReferenceSource("reference_director/sources/a.png", "image/png", "a" * 64)
    edit = ImageEdit(remove_background=True, background_mode="transparent")

    tensor = reference_media._load_image(Path("unused"), source, edit)

    assert tensor.shape == (1, 8, 10, 4)
    assert "remove-background" in operations


def test_materialized_edit_is_not_applied_twice(monkeypatch):
    operations = []
    install_fake_pillow(monkeypatch, operations)
    install_fake_numpy_and_torch(monkeypatch)
    source = ReferenceSource("reference_director/edits/a.png", "image/png", "a" * 64)
    edit = ImageEdit(
        crop=NormalizedCrop(0.1, 0.1, 0.5, 0.5),
        flip_x=True,
        background_mode="solid",
        background_color="#ffffff",
    )
    tensor = reference_media._load_image(Path("unused"), source, edit)
    assert tensor.shape == (1, 8, 10, 3)
    assert "mirror" not in operations
    assert not any(operation[0] == "crop" for operation in operations if isinstance(operation, tuple))


def test_image_loader_applies_a_content_addressed_keep_mask(monkeypatch):
    operations = []
    install_fake_pillow(monkeypatch, operations)
    install_fake_numpy_and_torch(monkeypatch)
    mask_source = ReferenceSource(
        "reference_director/sources/mask.png", "image/png", "d" * 64
    )
    source = ReferenceSource(
        "reference_director/sources/a.png", "image/png", "a" * 64
    )
    edit = ImageEdit(
        mask=mask_source,
        mask_mode="keep",
        background_mode="transparent",
    )

    tensor = reference_media._load_image(
        Path("image.png"), source, edit, Path("mask.png")
    )

    assert tensor.shape == (1, 8, 10, 4)
    assert "mask-multiply" in operations
    assert any(
        operation[0] == "putalpha"
        for operation in operations
        if isinstance(operation, tuple)
    )


def test_mask_tracks_flip_without_an_explicit_crop_and_preserves_alpha(monkeypatch):
    operations = []
    install_fake_pillow(monkeypatch, operations)
    install_fake_numpy_and_torch(monkeypatch)
    mask_source = ReferenceSource(
        "reference_director/sources/mask.png", "image/png", "d" * 64
    )
    source = ReferenceSource(
        "reference_director/sources/a.png", "image/png", "a" * 64
    )
    edit = ImageEdit(mask=mask_source, mask_mode="keep", flip_x=True)

    tensor = reference_media._load_image(
        Path("image.png"), source, edit, Path("mask.png")
    )

    assert tensor.shape == (1, 8, 10, 4)
    assert operations.count("mirror") == 2


def test_proxy_sized_mask_uses_the_same_normalized_crop_as_the_source(monkeypatch):
    operations = []
    install_fake_pillow(monkeypatch, operations)
    install_fake_numpy_and_torch(monkeypatch)
    mask_source = ReferenceSource(
        "reference_director/sources/mask.png", "image/png", "d" * 64
    )
    source = ReferenceSource(
        "reference_director/sources/a.png", "image/png", "a" * 64
    )
    edit = ImageEdit(
        crop=NormalizedCrop(0.25, 0.25, 0.5, 0.5),
        mask=mask_source,
        mask_mode="keep",
        background_mode="transparent",
    )

    tensor = reference_media._load_image(
        Path("image.png"), source, edit, Path("mask.png")
    )

    assert tensor.shape == (1, 4, 6, 4)
    crop_operations = [
        operation for operation in operations
        if isinstance(operation, tuple) and operation[0] == "crop"
    ]
    assert crop_operations == [("crop", (2, 2, 8, 6)), ("crop", (2, 2, 8, 6))]


def test_audio_loader_uses_pyav_and_applies_seconds_crop(monkeypatch):
    install_fake_numpy_and_torch(monkeypatch)

    class Frame:
        sample_rate = 4
        layout = SimpleNamespace(nb_channels=1)

        def to_ndarray(self):
            return FakeArray(1, 8)

    stream = SimpleNamespace(codec_context=SimpleNamespace(sample_rate=4))

    class Container:
        streams = SimpleNamespace(audio=[stream])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def decode(self, _stream):
            return [Frame()]

    class Resampler:
        def __init__(self, *, format):
            assert format == "fltp"

        def resample(self, frame):
            return [] if frame is None else [frame]

    av = ModuleType("av")
    av.open = lambda *_args, **_kwargs: Container()
    av.audio = SimpleNamespace(
        resampler=SimpleNamespace(AudioResampler=Resampler)
    )
    monkeypatch.setitem(sys.modules, "av", av)

    audio = reference_media._load_audio(Path("unused"), TimeRange(0.5, 1.5))
    assert audio["sample_rate"] == 4
    assert audio["waveform"].shape == (1, 1, 4)


def test_audio_loader_rejects_more_than_two_hours_of_decoded_samples(monkeypatch):
    install_fake_numpy_and_torch(monkeypatch)
    assert reference_media.MAX_AUDIO_DURATION_SECONDS == 2 * 60 * 60

    class Frame:
        sample_rate = 1
        layout = SimpleNamespace(nb_channels=1)

        def to_ndarray(self):
            return FakeArray(1, reference_media.MAX_AUDIO_DURATION_SECONDS + 1)

    stream = SimpleNamespace(codec_context=SimpleNamespace(sample_rate=1))

    class Container:
        streams = SimpleNamespace(audio=[stream])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def decode(self, _stream):
            return [Frame()]

    class Resampler:
        def __init__(self, *, format):
            assert format == "fltp"

        def resample(self, frame):
            return [] if frame is None else [frame]

    av = ModuleType("av")
    av.open = lambda *_args, **_kwargs: Container()
    av.audio = SimpleNamespace(
        resampler=SimpleNamespace(AudioResampler=Resampler)
    )
    monkeypatch.setitem(sys.modules, "av", av)

    with pytest.raises(reference_media.ReferenceMediaError, match="2-hour"):
        reference_media._load_audio(Path("unused"), None)


def test_audio_loader_bounds_the_selected_waveform_memory(monkeypatch):
    install_fake_numpy_and_torch(monkeypatch)

    class Frame:
        sample_rate = 1
        layout = SimpleNamespace(nb_channels=1)

        def to_ndarray(self):
            return FakeArray(1, 3)

    stream = SimpleNamespace(codec_context=SimpleNamespace(sample_rate=1))

    class Container:
        streams = SimpleNamespace(audio=[stream])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def decode(self, _stream):
            return [Frame()]

    class Resampler:
        def __init__(self, *, format):
            assert format == "fltp"

        def resample(self, frame):
            return [] if frame is None else [frame]

    av = ModuleType("av")
    av.open = lambda *_args, **_kwargs: Container()
    av.audio = SimpleNamespace(
        resampler=SimpleNamespace(AudioResampler=Resampler)
    )
    monkeypatch.setitem(sys.modules, "av", av)
    monkeypatch.setattr(reference_media, "MAX_AUDIO_OUTPUT_BYTES", 8)

    with pytest.raises(reference_media.ReferenceMediaError, match="256 MiB"):
        reference_media._load_audio(Path("unused"), None)


def test_video_loader_uses_public_input_impl_and_explicit_trim_contract(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        reference_media,
        "_validate_video_stream_layout",
        lambda _path: None,
    )

    class Video:
        def get_duration(self):
            return 10.0

        def as_trimmed(self, **kwargs):
            calls["trim"] = kwargs
            return self

    input_impl = SimpleNamespace(
        VideoFromFile=lambda path: calls.update(path=path) or Video()
    )
    comfy_api = ModuleType("comfy_api")
    versioned = ModuleType("comfy_api.v0_0_2")
    versioned.InputImpl = input_impl
    comfy_api.v0_0_2 = versioned
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_api)
    monkeypatch.setitem(sys.modules, "comfy_api.v0_0_2", versioned)

    video = reference_media._load_video(Path("movie.mp4"), TimeRange(1.0, 3.5))
    assert isinstance(video, Video)
    assert calls["path"].endswith("movie.mp4")
    assert calls["trim"] == {
        "start_time": 1.0,
        "duration": 2.5,
        "strict_duration": False,
    }


def test_video_loader_rejects_sources_longer_than_one_hour(monkeypatch):
    assert reference_media.MAX_VIDEO_DURATION_SECONDS == 60 * 60
    monkeypatch.setattr(
        reference_media,
        "_validate_video_stream_layout",
        lambda _path: None,
    )

    class Video:
        def get_duration(self):
            return reference_media.MAX_VIDEO_DURATION_SECONDS + 0.01

    input_impl = SimpleNamespace(VideoFromFile=lambda _path: Video())
    comfy_api = ModuleType("comfy_api")
    versioned = ModuleType("comfy_api.v0_0_2")
    versioned.InputImpl = input_impl
    comfy_api.v0_0_2 = versioned
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_api)
    monkeypatch.setitem(sys.modules, "comfy_api.v0_0_2", versioned)

    with pytest.raises(reference_media.ReferenceMediaError, match="1-hour"):
        reference_media._load_video(Path("movie.mp4"), None)


def test_video_stream_layout_rejects_multiple_audio_tracks(monkeypatch):
    video = SimpleNamespace(codec_context=object(), disposition=None)
    audio_a = SimpleNamespace(codec_context=object())
    audio_b = SimpleNamespace(codec_context=object())

    class Container:
        streams = SimpleNamespace(video=[video], audio=[audio_a, audio_b])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    av = ModuleType("av")
    av.open = lambda *_args, **_kwargs: Container()
    monkeypatch.setitem(sys.modules, "av", av)

    with pytest.raises(reference_media.ReferenceMediaError, match="at most one audio"):
        reference_media._validate_video_stream_layout(Path("movie.mp4"))


def test_loader_preserves_independent_output_order_and_video_audio(monkeypatch, tmp_path):
    def source(name, payload, mime):
        path = tmp_path / name
        path.write_bytes(payload)
        return {
            "path": name,
            "mime": mime,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    raw = {
        "version": 1,
        "items": {
            "img": {"id": "img", "kind": "image", "source": source("img.png", b"i", "image/png"), "caption": "", "visualEnabled": True},
            "vid": {"id": "vid", "kind": "video", "source": source("vid.mp4", b"v", "video/mp4"), "caption": "", "visualEnabled": True, "audioEnabled": True},
            "aud": {"id": "aud", "kind": "audio", "source": source("aud.wav", b"a", "audio/wav"), "caption": "", "audioEnabled": True},
        },
        "visualOrder": ["vid", "img"],
        "audioOrder": ["vid", "aud"],
        "videoAudioPolicy": "preserve",
    }
    state = parse_reference_state(raw)
    monkeypatch.setattr(
        reference_media,
        "_load_image",
        lambda path, *_args, **_kwargs: f"image:{path.name}",
    )
    monkeypatch.setattr(reference_media, "_load_video", lambda path, *_args: f"video:{path.name}")
    monkeypatch.setattr(
        reference_media,
        "_load_audio",
        lambda path, *_args, **_kwargs: f"audio:{path.name}",
    )

    loaded = reference_media.load_reference_media(state, input_directory=tmp_path)
    assert loaded.images == ("image:img.png",)
    assert loaded.videos == ("video:vid.mp4",)
    assert loaded.audios == ("audio:vid.mp4", "audio:aud.wav")


def test_materialized_image_edit_does_not_require_the_brush_mask_at_execution(
    monkeypatch,
    tmp_path,
):
    payload = b"materialized-edit"
    digest = hashlib.sha256(payload).hexdigest()
    edits = tmp_path / "reference_director" / "edits"
    edits.mkdir(parents=True)
    (edits / f"{digest}.png").write_bytes(payload)
    raw = {
        "version": 1,
        "items": {
            "img": {
                "id": "img",
                "kind": "image",
                "source": {
                    "path": f"reference_director/edits/{digest}.png",
                    "mime": "image/png",
                    "sha256": digest,
                    "size": len(payload),
                },
                "caption": "",
                "visualEnabled": True,
                "edit": {
                    "mask": {
                        "path": f"reference_director/sources/{'a' * 64}.png",
                        "mime": "image/png",
                        "sha256": "a" * 64,
                    },
                    "maskMode": "keep",
                    "revision": 1,
                },
            }
        },
        "visualOrder": ["img"],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
    }
    state = parse_reference_state(raw)
    seen = []
    monkeypatch.setattr(
        reference_media,
        "_load_image",
        lambda path, _source, _edit, mask_path, **_kwargs: seen.append((path, mask_path))
        or "image",
    )

    loaded = reference_media.load_reference_media(state, input_directory=tmp_path)

    assert loaded.images == ("image",)
    assert seen == [(edits / f"{digest}.png", None)]


def test_loader_passes_and_enforces_the_aggregate_tensor_memory_budget(
    monkeypatch,
    tmp_path,
):
    def source(name, payload):
        path = tmp_path / name
        path.write_bytes(payload)
        return {
            "path": name,
            "mime": "image/png",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    raw = {
        "version": 1,
        "items": {
            "a": {
                "id": "a",
                "kind": "image",
                "source": source("a.png", b"a"),
                "caption": "",
                "visualEnabled": True,
            },
            "b": {
                "id": "b",
                "kind": "image",
                "source": source("b.png", b"b"),
                "caption": "",
                "visualEnabled": True,
            },
        },
        "visualOrder": ["a", "b"],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
    }

    class SizedTensor:
        def numel(self):
            return 3

        def element_size(self):
            return 4

    budgets = []

    def load_image(_path, _source, _edit, _mask, *, max_output_bytes):
        budgets.append(max_output_bytes)
        return SizedTensor()

    monkeypatch.setattr(reference_media, "MAX_DECODED_OUTPUT_BYTES", 16)
    monkeypatch.setattr(reference_media, "_load_image", load_image)

    with pytest.raises(reference_media.ReferenceMediaError, match="aggregate"):
        reference_media.load_reference_media(
            parse_reference_state(raw),
            input_directory=tmp_path,
        )

    assert budgets == [16, 4]


def test_fingerprint_source_validation_detects_same_size_content_replacement(tmp_path):
    original = b"original"
    replacement = b"replaced"
    assert len(original) == len(replacement)
    source_path = tmp_path / "source.png"
    source_path.write_bytes(original)
    raw = {
        "version": 1,
        "items": {
            "img": {
                "id": "img",
                "kind": "image",
                "source": {
                    "path": "source.png",
                    "mime": "image/png",
                    "sha256": hashlib.sha256(original).hexdigest(),
                    "size": len(original),
                },
                "caption": "",
                "visualEnabled": True,
            }
        },
        "visualOrder": ["img"],
        "audioOrder": [],
        "videoAudioPolicy": "preserve",
    }
    state = parse_reference_state(raw)
    reference_media.validate_reference_sources(state, input_directory=tmp_path)

    source_path.write_bytes(replacement)

    with pytest.raises(reference_media.ReferenceMediaError, match="hash"):
        reference_media.validate_reference_sources(
            state,
            input_directory=tmp_path,
        )
