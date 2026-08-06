class MultimodalError(RuntimeError):
    """Base error for user-facing multimodal node failures."""


class InputNormalizationError(MultimodalError):
    """Raised when a ComfyUI input cannot be normalized safely."""


class BackendError(MultimodalError):
    """Raised when a remote inference backend fails."""
