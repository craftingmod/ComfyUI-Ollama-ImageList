import base64
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.backends.ollama import chat
from backend.core import BackendError, InputNormalizationError, normalize_images
from tests.backend.tensor_stub import solid_image


def png_dimensions(payload: bytes) -> tuple[int, int]:
    return struct.unpack(">II", payload[16:24])


def test_chat_sends_all_images_in_exactly_one_request_and_parses_outputs():
    bundle = normalize_images(
        [solid_image(1, 2, 3, 3, 0.1), solid_image(1, 4, 1, 3, 0.9)]
    )
    calls = []

    def transport(url: str, body: bytes, timeout: float):
        calls.append((url, json.loads(body), timeout))
        return 200, json.dumps(
            {
                "model": "gemma3",
                "message": {"role": "assistant", "content": "완료", "thinking": "검토"},
                "done": True,
                "total_duration": 123,
                "prompt_eval_count": 20,
                "eval_count": 3,
            }
        ).encode()

    result = chat(
        url="http://user:secret@localhost:11434/",
        model="gemma3",
        system="  시스템 그대로  ",
        prompt="이미지 둘을 비교해줘\n",
        media=bundle,
        options_json='{"temperature":0.2,"seed":7}',
        format_json="json",
        think="medium",
        keep_alive="5m",
        timeout_seconds=12,
        transport=transport,
    )

    assert len(calls) == 1
    url, request, timeout = calls[0]
    assert url == "http://user:secret@localhost:11434/api/chat"
    assert timeout == 12
    assert request["messages"][0]["content"] == "  시스템 그대로  "
    assert request["messages"][1]["content"] == "이미지 둘을 비교해줘\n"
    decoded = [base64.b64decode(value) for value in request["messages"][1]["images"]]
    assert [png_dimensions(payload) for payload in decoded] == [(3, 2), (1, 4)]
    assert request["stream"] is False
    assert request["think"] == "medium"
    assert request["format"] == "json"
    assert request["options"] == {"temperature": 0.2, "seed": 7}
    assert result.response == "완료"
    assert result.thinking == "검토"
    assert result.metrics["eval_count"] == 3
    assert result.request_manifest["url"] == "http://localhost:11434"
    assert "시스템" not in json.dumps(result.request_manifest, ensure_ascii=False)
    assert "images" not in result.request_manifest["messages"][1]


def test_non_success_response_preserves_short_error_without_payload_leak():
    encoded = "A" * 256

    def transport(_url: str, _body: bytes, _timeout: float):
        return 400, json.dumps({"error": f"unsupported {encoded}"}).encode()

    with pytest.raises(BackendError) as error:
        chat(
            url="http://localhost:11434",
            model="text-only",
            system="",
            prompt="test",
            media=normalize_images(None),
            transport=transport,
        )

    assert "HTTP 400" in str(error.value)
    assert encoded not in str(error.value)
    assert "<redacted-base64>" in str(error.value)


def test_default_http_transport_calls_a_mock_ollama_server_once():
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append({"path": self.path, "body": json.loads(self.rfile.read(length))})
            response = json.dumps(
                {"message": {"role": "assistant", "content": "ok"}, "done": True}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = chat(
            url=f"http://127.0.0.1:{server.server_port}",
            model="gemma3",
            system="system",
            prompt="prompt",
            media=normalize_images(solid_image(1, 1, 2, 3, 0.5)),
            timeout_seconds=2,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.response == "ok"
    assert len(received) == 1
    assert received[0]["path"] == "/api/chat"
    assert len(received[0]["body"]["messages"][1]["images"]) == 1


def test_audio_is_rejected_by_default_instead_of_changing_request_meaning():
    from backend.core import normalize_audio
    from tests.backend.tensor_stub import silent_audio

    bundle = normalize_audio({"waveform": silent_audio(1, 1, 8), "sample_rate": 8_000})
    with pytest.raises(InputNormalizationError, match="no documented native audio field"):
        chat(
            url="http://localhost:11434",
            model="model",
            system="",
            prompt="transcribe",
            media=bundle,
        )
