class ImageListError(RuntimeError):
    """Base error for user-facing Ollama Image List node failures."""


class InputNormalizationError(ImageListError):
    """Raised when a ComfyUI input cannot be normalized safely."""


class BackendError(ImageListError):
    """Raised when a remote inference backend fails."""
