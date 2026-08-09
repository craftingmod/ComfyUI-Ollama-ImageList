from __future__ import annotations

from fractions import Fraction
from io import BytesIO
from typing import Any


class TensorStub:
    def __init__(self, data: Any, shape: tuple[int, ...]):
        self._data = data
        self.shape = shape

    def __getitem__(self, index) -> "TensorStub":
        data = self._data[index]
        if isinstance(index, slice):
            return TensorStub(data, (len(data), *self.shape[1:]))
        return TensorStub(data, self.shape[1:])

    def element_size(self) -> int:
        return 4

    def tolist(self):
        return self._data


def solid_image(batch: int, height: int, width: int, channels: int, value: float) -> TensorStub:
    data = [
        [
            [[value for _ in range(channels)] for _ in range(width)]
            for _ in range(height)
        ]
        for _ in range(batch)
    ]
    return TensorStub(data, (batch, height, width, channels))


def silent_audio(batch: int, channels: int, samples: int) -> TensorStub:
    data = [
        [[0.0 for _ in range(samples)] for _ in range(channels)]
        for _ in range(batch)
    ]
    return TensorStub(data, (batch, channels, samples))


class VideoInputStub:
    def __init__(
        self,
        payload: bytes,
        *,
        container: str = "mp4",
        duration: float = 1.0,
        frame_count: int = 24,
        frame_rate: Fraction = Fraction(24, 1),
        dimensions: tuple[int, int] = (640, 360),
    ):
        self.stream = BytesIO(payload)
        self.container = container
        self.duration = duration
        self.frame_count = frame_count
        self.frame_rate = frame_rate
        self.dimensions = dimensions

    def get_stream_source(self):
        return self.stream

    def get_container_format(self):
        return self.container

    def get_duration(self):
        return self.duration

    def get_frame_count(self):
        return self.frame_count

    def get_frame_rate(self):
        return self.frame_rate

    def get_dimensions(self):
        return self.dimensions
