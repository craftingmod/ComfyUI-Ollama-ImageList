from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
import zlib
from typing import Any

from .errors import InputNormalizationError


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _as_cpu_value(value: Any) -> Any:
    result = value
    if hasattr(result, "detach"):
        result = result.detach()
    if hasattr(result, "cpu"):
        result = result.cpu()
    return result


def _encode_png_numpy(image: Any, height: int, width: int, channels: int) -> bytes | None:
    try:
        import numpy as np
    except ModuleNotFoundError:
        return None

    array = np.asarray(_as_cpu_value(image), dtype=np.float32)
    if array.shape != (height, width, channels):
        raise InputNormalizationError(
            f"Image data shape changed during encoding: expected {(height, width, channels)}, got {array.shape}."
        )
    if not np.isfinite(array).all():
        raise InputNormalizationError("Image contains NaN or infinite values.")
    pixels = np.rint(np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8, copy=False)
    rows = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))
    return _build_png(width, height, channels, rows)


def _encode_png_python(image: Any, height: int, width: int, channels: int) -> bytes:
    value = _as_cpu_value(image)
    if hasattr(value, "tolist"):
        value = value.tolist()

    rows = bytearray()
    try:
        for y in range(height):
            rows.append(0)
            for x in range(width):
                pixel = value[y][x]
                for channel in range(channels):
                    sample = float(pixel[channel])
                    if not math.isfinite(sample):
                        raise InputNormalizationError("Image contains NaN or infinite values.")
                    rows.append(round(max(0.0, min(1.0, sample)) * 255.0))
    except (IndexError, TypeError) as exc:
        raise InputNormalizationError("Image data does not match its declared H×W×C shape.") from exc
    return _build_png(width, height, channels, bytes(rows))


def _build_png(width: int, height: int, channels: int, rows: bytes) -> bytes:
    color_types = {1: 0, 3: 2, 4: 6}
    header = struct.pack(">IIBBBBB", width, height, 8, color_types[channels], 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, level=6))
        + _png_chunk(b"IEND", b"")
    )


def encode_image_png(image: Any, *, height: int, width: int, channels: int) -> tuple[bytes, str]:
    if channels not in (1, 3, 4):
        raise InputNormalizationError(f"Unsupported image channel count {channels}; expected 1, 3, or 4.")
    payload = _encode_png_numpy(image, height, width, channels)
    if payload is None:
        payload = _encode_png_python(image, height, width, channels)
    return payload, hashlib.sha256(payload).hexdigest()


def _audio_numpy_bytes(waveform: Any, channels: int, samples: int) -> bytes | None:
    try:
        import numpy as np
    except ModuleNotFoundError:
        return None

    array = np.asarray(_as_cpu_value(waveform), dtype=np.float32)
    if array.shape != (channels, samples):
        raise InputNormalizationError(
            f"Audio data shape changed during encoding: expected {(channels, samples)}, got {array.shape}."
        )
    if not np.isfinite(array).all():
        raise InputNormalizationError("Audio contains NaN or infinite values.")
    pcm = np.rint(np.clip(array, -1.0, 1.0) * 32767.0).astype("<i2")
    return pcm.T.tobytes()


def _audio_python_bytes(waveform: Any, channels: int, samples: int) -> bytes:
    value = _as_cpu_value(waveform)
    if hasattr(value, "tolist"):
        value = value.tolist()
    frames = bytearray()
    try:
        for sample_index in range(samples):
            for channel in range(channels):
                sample = float(value[channel][sample_index])
                if not math.isfinite(sample):
                    raise InputNormalizationError("Audio contains NaN or infinite values.")
                frames.extend(struct.pack("<h", round(max(-1.0, min(1.0, sample)) * 32767.0)))
    except (IndexError, TypeError) as exc:
        raise InputNormalizationError("Audio data does not match its declared C×T shape.") from exc
    return bytes(frames)


def encode_audio_wav(
    waveform: Any,
    *,
    sample_rate: int,
    channels: int,
    samples: int,
) -> tuple[bytes, str]:
    frames = _audio_numpy_bytes(waveform, channels, samples)
    if frames is None:
        frames = _audio_python_bytes(waveform, channels, samples)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    payload = buffer.getvalue()
    return payload, hashlib.sha256(payload).hexdigest()
