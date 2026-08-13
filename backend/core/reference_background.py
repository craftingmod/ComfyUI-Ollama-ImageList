from __future__ import annotations

import importlib.util
import threading
from typing import Any


class ReferenceBackgroundRemovalError(RuntimeError):
    """Raised when automatic foreground extraction cannot be completed."""


class ReferenceBackgroundRemovalUnavailable(ReferenceBackgroundRemovalError):
    """Raised when the optional rembg runtime is not installed."""


_SESSION: Any | None = None
_SESSION_LOCK = threading.Lock()


def remove_reference_background(image: Any) -> Any:
    """Return a same-sized RGBA foreground using a lazily cached rembg session."""

    global _SESSION
    if (
        importlib.util.find_spec("rembg") is None
        or importlib.util.find_spec("onnxruntime") is None
    ):
        raise ReferenceBackgroundRemovalUnavailable(
            'Automatic background removal requires the optional "rembg" extra. '
            'Install this project with `pip install ".[rembg]"` in the ComfyUI environment.'
        )
    with _SESSION_LOCK:
        try:
            from rembg import new_session, remove
        except (ImportError, ModuleNotFoundError, SystemExit) as exc:
            raise ReferenceBackgroundRemovalUnavailable(
                'Automatic background removal requires rembg with a CPU or GPU ONNX runtime.'
            ) from exc
        try:
            if _SESSION is None:
                _SESSION = new_session()
            result = remove(image.convert("RGBA"), session=_SESSION)
        except Exception as exc:
            raise ReferenceBackgroundRemovalError(
                "rembg could not remove the image background."
            ) from exc
    if not hasattr(result, "convert") or getattr(result, "size", None) != getattr(
        image, "size", None
    ):
        raise ReferenceBackgroundRemovalError("rembg returned an invalid image result.")
    return result.convert("RGBA")


__all__ = [
    "ReferenceBackgroundRemovalError",
    "ReferenceBackgroundRemovalUnavailable",
    "remove_reference_background",
]
