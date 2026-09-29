import json
from threading import RLock

import pytest

from backend.backends.llama_cpp_server import (
    LlamaCppServerSession,
    OwnedLlamaCppServerSession,
    list_server_models,
    parse_models_response,
)
from backend.core import BackendError, MediaBundle
from backend.core.media import MediaItem
from backend.llama_cpp_session_cleanup import close_tracked_sessions


def test_server_session_parses_models_generates_multimodal_and_retries_unload(
    monkeypatch,
):
    calls = []
    unload_attempts = 0
    import backend.llama_cpp_session_cleanup as cleanup_module

    tracked = set()
    monkeypatch.setattr(cleanup_module, "_sessions", tracked)
    monkeypatch.setattr(cleanup_module, "_sessions_lock", RLock())

    def transport(url, method, body, timeout):
        nonlocal unload_attempts
        calls.append((url, method, body, timeout))
        if url.endswith("/health"):
            assert method == "GET"
            if "unhealthy" in url:
                return 200, b'{"status":"loading"}'
            return 200, b'{"status":"ok"}'
        if url.endswith("/models"):
            return 200, b'{"data":[{"id":"model-a"},{"id":"model-b"}]}'
        if url.endswith("/v1/chat/completions"):
            payload = json.loads(body)
            parts = payload["messages"][-1]["content"]
            assert payload["model"] == "model-a"
            assert payload["stream"] is False
            assert [part["type"] for part in parts] == [
                "text",
                "image_url",
                "input_audio",
                "input_video",
            ]
            return 200, json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "answer",
                                "reasoning_content": "thought",
                            }
                        }
                    ],
                    "usage": {"completion_tokens": 1},
                    "timings": {"predicted_n": 1},
                }
            ).encode()
        assert url.endswith("/models/unload")
        assert method == "POST"
        assert json.loads(body) == {"model": "model-a"}
        unload_attempts += 1
        if unload_attempts == 1:
            return 503, b'{"error":{"message":"server busy"}}'
        return 200, b'{"success":true}'

    assert list_server_models(url="http://localhost:8080", transport=transport) == [
        "model-a",
        "model-b",
    ]
    with pytest.raises(BackendError):
        parse_models_response(b'{"data":[{"id":4}]}')

    with pytest.raises(BackendError, match="health check failed"):
        LlamaCppServerSession(
            url="http://unhealthy:8080",
            model="model-a",
            transport=transport,
        )
    assert tracked == set()

    session = LlamaCppServerSession(
        url="http://localhost:8080",
        model="model-a",
        transport=transport,
    )
    result = session.generate(
        system="system",
        prompt="prompt",
        media=MediaBundle(
            (
                MediaItem("image", 0, "image/png", b"png", {}),
                MediaItem("audio", 1, "audio/wav", b"wav", {}),
                MediaItem("video", 2, "video/mp4", b"mp4", {}),
            )
        ),
        max_tokens=8,
        seed=-1,
        stop="",
    )
    assert (result.response, result.thinking) == ("answer", "thought")
    assert result.metrics["server_timings"] == {"predicted_n": 1}
    assert result.media_diagnostics["mtmd"]["verification"] == "unverified_remote"

    assert session in tracked
    close_tracked_sessions()
    assert session.closed is False
    assert session in tracked
    close_tracked_sessions()
    assert session.closed is True
    session.close()
    assert unload_attempts == 2
    assert session not in tracked


def test_owned_server_session_retries_shutdown_and_cleanup_idempotently(monkeypatch):
    import backend.llama_cpp_session_cleanup as cleanup_module

    tracked = set()
    monkeypatch.setattr(cleanup_module, "_sessions", tracked)
    monkeypatch.setattr(cleanup_module, "_sessions_lock", RLock())

    events = []
    requests = []

    class Process:
        close_calls = 0

        def close(self):
            self.close_calls += 1
            events.append("process")
            if self.close_calls == 1:
                raise RuntimeError("shutdown failed")

    process = Process()
    cleanup_calls = 0

    def cleanup():
        nonlocal cleanup_calls
        cleanup_calls += 1
        events.append("cleanup")
        if cleanup_calls == 1:
            raise RuntimeError("cleanup failed")

    def transport(url, method, body, timeout):
        requests.append((url, method))
        assert url.endswith("/health")
        return 200, b'{"status":"ok"}'

    session = OwnedLlamaCppServerSession(
        url="http://localhost:8080",
        model="model-a",
        process=process,
        cleanup=cleanup,
        transport=transport,
    )

    with pytest.raises(RuntimeError, match="shutdown failed"):
        session.close()
    assert session in tracked
    assert cleanup_calls == 0

    with pytest.raises(RuntimeError, match="cleanup failed"):
        session.close()
    assert session in tracked
    assert session.closed is False

    session.close()
    assert session.closed is True
    assert session not in tracked
    session.close()

    assert process.close_calls == 2
    assert cleanup_calls == 2
    assert events == ["process", "process", "cleanup", "cleanup"]
    assert requests == [("http://localhost:8080/health", "GET")]


def test_owned_server_session_closes_at_prompt_end(monkeypatch):
    import backend.llama_cpp_session_cleanup as cleanup_module

    tracked = set()
    monkeypatch.setattr(cleanup_module, "_sessions", tracked)
    monkeypatch.setattr(cleanup_module, "_sessions_lock", RLock())

    class Process:
        closed = False

        def close(self):
            self.closed = True

    process = Process()
    session = OwnedLlamaCppServerSession(
        url="http://localhost:8080",
        model="model-a",
        process=process,
    )

    assert session in tracked
    close_tracked_sessions()
    assert process.closed is True
    assert session.closed is True
    assert session not in tracked
