from __future__ import annotations

from typing import Any


class TensorStub:
    def __init__(self, data: Any, shape: tuple[int, ...]):
        self._data = data
        self.shape = shape

    def __getitem__(self, index: int) -> "TensorStub":
        return TensorStub(self._data[index], self.shape[1:])

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
