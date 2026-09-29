from __future__ import annotations

import asyncio
from typing import Any

from .backends.llama_cpp_server import list_server_models
from .backends.ollama import list_models
from .core.errors import BackendError, InputNormalizationError

MODELS_ROUTE = "/ollama_image_list/models"
LLAMA_CPP_MODELS_ROUTE = "/ollama_image_list/llama_cpp/models"
_routes_registered = False


async def fetch_models_endpoint(request: Any):
    from aiohttp import web

    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Request body must be valid JSON."}, status=400
        )

    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        return web.json_response({"error": "url must be a string."}, status=400)

    try:
        models = await asyncio.to_thread(
            list_models,
            url=data["url"],
            timeout_seconds=10,
        )
    except InputNormalizationError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except BackendError as exc:
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({"models": models})


async def fetch_llama_cpp_models_endpoint(request: Any):
    from aiohttp import web

    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Request body must be valid JSON."}, status=400
        )
    if not isinstance(data, dict) or not isinstance(data.get("url"), str):
        return web.json_response({"error": "url must be a string."}, status=400)
    api_key = data.get("api_key", "")
    if not isinstance(api_key, str):
        return web.json_response({"error": "api_key must be a string."}, status=400)

    try:
        models = await asyncio.to_thread(
            list_server_models,
            url=data["url"],
            api_key=api_key or None,
            timeout_seconds=10,
        )
    except InputNormalizationError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except BackendError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    return web.json_response({"models": models})


def register_routes() -> None:
    global _routes_registered
    if _routes_registered:
        return

    from server import PromptServer

    PromptServer.instance.routes.post(MODELS_ROUTE)(fetch_models_endpoint)
    PromptServer.instance.routes.post(LLAMA_CPP_MODELS_ROUTE)(
        fetch_llama_cpp_models_endpoint
    )
    _routes_registered = True


__all__ = [
    "LLAMA_CPP_MODELS_ROUTE",
    "MODELS_ROUTE",
    "fetch_llama_cpp_models_endpoint",
    "fetch_models_endpoint",
    "register_routes",
]
