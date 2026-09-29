import asyncio
import sys
from types import ModuleType, SimpleNamespace

from backend import routes
from backend.core import BackendError


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def install_aiohttp_stub(monkeypatch):
    aiohttp = ModuleType("aiohttp")
    aiohttp.web = SimpleNamespace(
        json_response=lambda payload, status=200: SimpleNamespace(
            payload=payload,
            status=status,
        )
    )
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp)


def test_models_route_returns_model_names(monkeypatch):
    install_aiohttp_stub(monkeypatch)
    calls = []

    def list_models(**kwargs):
        calls.append(kwargs)
        return ["gemma3:latest", "qwen3:8b"]

    monkeypatch.setattr(routes, "list_models", list_models)

    response = asyncio.run(
        routes.fetch_models_endpoint(Request({"url": "http://127.0.0.1:11434"}))
    )

    assert response.status == 200
    assert response.payload == {"models": ["gemma3:latest", "qwen3:8b"]}
    assert calls == [
        {"url": "http://127.0.0.1:11434", "timeout_seconds": 10},
    ]


def test_llama_cpp_models_route_forwards_api_key(monkeypatch):
    install_aiohttp_stub(monkeypatch)
    calls = []

    def list_server_models(**kwargs):
        calls.append(kwargs)
        return ["model.gguf"]

    monkeypatch.setattr(routes, "list_server_models", list_server_models)
    response = asyncio.run(
        routes.fetch_llama_cpp_models_endpoint(
            Request(
                {
                    "url": "http://127.0.0.1:8080",
                    "api_key": "secret-token",
                }
            )
        )
    )

    assert response.status == 200
    assert response.payload == {"models": ["model.gguf"]}
    assert calls == [
        {
            "url": "http://127.0.0.1:8080",
            "api_key": "secret-token",
            "timeout_seconds": 10,
        },
    ]


def test_models_route_maps_backend_failure_without_exposing_request_body(monkeypatch):
    install_aiohttp_stub(monkeypatch)

    def fail(**_kwargs):
        raise BackendError("Could not reach Ollama: connection refused")

    monkeypatch.setattr(routes, "list_models", fail)
    response = asyncio.run(
        routes.fetch_models_endpoint(
            Request({"url": "http://user:secret@127.0.0.1:11434"})
        )
    )

    assert response.status == 502
    assert response.payload == {"error": "Could not reach Ollama: connection refused"}
    assert "secret" not in str(response.payload)
