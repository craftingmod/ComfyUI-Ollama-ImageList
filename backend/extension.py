from __future__ import annotations

try:
    from comfy_api.v0_0_2 import ComfyExtension, io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import ComfyExtension, io

from .nodes import (
    MultimodalOllamaMediaBundleNode,
    MultimodalOllamaConnectivityNode,
    MultimodalOllamaGenerateNode,
    MultimodalOllamaOptionsNode,
)
from .routes import register_routes


class MultimodalOllamaExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            MultimodalOllamaConnectivityNode,
            MultimodalOllamaOptionsNode,
            MultimodalOllamaMediaBundleNode,
            MultimodalOllamaGenerateNode,
        ]


async def comfy_entrypoint() -> MultimodalOllamaExtension:
    register_routes()
    return MultimodalOllamaExtension()
