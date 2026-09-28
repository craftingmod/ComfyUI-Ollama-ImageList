import asyncio
import json
import subprocess

import pytest

import backend.llama_cpp_runtime as runtime


class FakeProcess:
    stdin = None

    def __init__(self, *, fail_wait=False):
        self.fail_wait = fail_wait
        self.waited = False

    def poll(self):
        return None

    def wait(self, timeout):
        if self.fail_wait:
            raise subprocess.TimeoutExpired("llama-supervisor", timeout)
        self.waited = True
        return 0


class FreePortProbe:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def bind(self, _address):
        return None


def set_status_dependencies(monkeypatch, model_dir):
    monkeypatch.setattr(
        runtime, "_model_directory_options", lambda: ([model_dir], model_dir)
    )
    monkeypatch.setattr(runtime, "_llama_executable", lambda: "llama")
    monkeypatch.setattr(runtime, "_probe_llama_version", lambda _path: "test")


def test_restart_retries_failed_daemon_with_saved_settings(monkeypatch):
    model_dir = "C:/models/LLM"
    set_status_dependencies(monkeypatch, model_dir)
    old_process = FakeProcess()
    monkeypatch.setattr(runtime, "_auto_start", True)
    monkeypatch.setattr(runtime, "_ctx_size", 8192)
    monkeypatch.setattr(runtime, "_port", 18600)
    monkeypatch.setattr(runtime, "_model_dir", model_dir)
    monkeypatch.setattr(runtime, "_process", old_process)
    monkeypatch.setattr(runtime, "_active_port", None)
    monkeypatch.setattr(runtime, "_state", "failed")
    monkeypatch.setattr(runtime, "_start_attempted", True)
    monkeypatch.setattr(runtime, "_last_error", "previous startup failure")
    monkeypatch.setattr(
        runtime,
        "_save_runtime_settings",
        lambda *_args: pytest.fail("restart must not save settings"),
    )
    events = []

    def start(*, repair_model_dir):
        assert runtime._start_attempted is False
        assert repair_model_dir is False
        events.append(
            (
                "start",
                runtime._ctx_size,
                runtime._port,
                runtime._model_dir,
                repair_model_dir,
            )
        )
        monkeypatch.setattr(runtime, "_process", FakeProcess())
        monkeypatch.setattr(runtime, "_active_port", runtime._port)
        monkeypatch.setattr(runtime, "_state", "running")
        monkeypatch.setattr(runtime, "_last_error", None)
        monkeypatch.setattr(runtime, "_start_attempted", True)

    real_stop = runtime._stop_locked

    def stop():
        events.append(("stop",))
        return real_stop()

    monkeypatch.setattr(runtime, "_stop_locked", stop)
    monkeypatch.setattr(runtime, "_start_locked", start)

    status = runtime.restart_runtime()

    assert old_process.waited
    assert events == [
        ("stop",),
        ("start", 8192, 18600, model_dir, False),
    ]
    assert (
        runtime._auto_start,
        runtime._ctx_size,
        runtime._port,
        runtime._model_dir,
    ) == (
        True,
        8192,
        18600,
        model_dir,
    )
    assert status["state"] == "running"
    assert status["active_port"] == 18600


def test_restart_does_not_repair_or_save_an_unavailable_model_directory(monkeypatch):
    missing_model_dir = "C:/models/removed"
    default_model_dir = "C:/models/LLM"
    monkeypatch.setattr(
        runtime,
        "_model_directory_options",
        lambda: ([default_model_dir], default_model_dir),
    )
    monkeypatch.setattr(runtime, "_llama_executable", lambda: "llama")
    monkeypatch.setattr(runtime, "_probe_llama_version", lambda _path: "test")
    monkeypatch.setattr(runtime, "_auto_start", True)
    monkeypatch.setattr(runtime, "_ctx_size", 8192)
    monkeypatch.setattr(runtime, "_port", 18600)
    monkeypatch.setattr(runtime, "_model_dir", missing_model_dir)
    monkeypatch.setattr(runtime, "_process", None)
    monkeypatch.setattr(runtime, "_start_attempted", True)
    monkeypatch.setattr(runtime, "_state", "failed")
    monkeypatch.setattr(
        runtime,
        "_save_runtime_settings",
        lambda *_args: pytest.fail("restart must not save settings"),
    )

    monkeypatch.setattr(runtime.socket, "socket", lambda *_args: FreePortProbe())

    status = runtime.restart_runtime()

    assert status["state"] == "failed"
    assert "directory is unavailable" in status["error"]
    assert runtime._model_dir == missing_model_dir


def test_restart_reports_running_only_after_health_check(monkeypatch, tmp_path):
    model_dir = str(tmp_path)
    set_status_dependencies(monkeypatch, model_dir)
    monkeypatch.setattr(runtime, "_auto_start", True)
    monkeypatch.setattr(runtime, "_ctx_size", 8192)
    monkeypatch.setattr(runtime, "_port", 18600)
    monkeypatch.setattr(runtime, "_model_dir", model_dir)
    monkeypatch.setattr(runtime, "_process", None)
    monkeypatch.setattr(runtime, "_start_attempted", True)
    monkeypatch.setattr(runtime, "_state", "failed")
    monkeypatch.setattr(runtime.socket, "socket", lambda *_args: FreePortProbe())
    monkeypatch.setattr(
        runtime, "_save_runtime_settings", lambda *_args: pytest.fail("must not save")
    )
    commands = []

    def start_supervisor(command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(runtime.subprocess, "Popen", start_supervisor)
    health_checks = []
    monkeypatch.setattr(
        runtime,
        "_server_ready",
        lambda port: health_checks.append(port) or port == 18600,
    )

    status = runtime.restart_runtime()

    assert health_checks == [18600]
    assert "--ctx-size" in commands[0]
    assert commands[0][commands[0].index("--ctx-size") + 1] == "8192"
    assert status["state"] == "running"
    assert status["active_port"] == 18600


def test_restart_reports_failed_when_health_check_never_succeeds(monkeypatch, tmp_path):
    model_dir = str(tmp_path)
    set_status_dependencies(monkeypatch, model_dir)
    monkeypatch.setattr(runtime, "_auto_start", True)
    monkeypatch.setattr(runtime, "_port", 18600)
    monkeypatch.setattr(runtime, "_model_dir", model_dir)
    monkeypatch.setattr(runtime, "_process", None)
    monkeypatch.setattr(runtime, "_start_attempted", True)
    monkeypatch.setattr(runtime, "_state", "failed")
    monkeypatch.setattr(runtime.socket, "socket", lambda *_args: FreePortProbe())
    monkeypatch.setattr(runtime, "_STARTUP_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(runtime, "_HEALTH_POLL_INTERVAL_SECONDS", 0.005)
    monkeypatch.setattr(runtime, "_server_ready", lambda _port: False)
    monkeypatch.setattr(
        runtime, "_save_runtime_settings", lambda *_args: pytest.fail("must not save")
    )
    supervisor = FakeProcess()
    monkeypatch.setattr(
        runtime.subprocess, "Popen", lambda _command, **_kwargs: supervisor
    )

    status = runtime.restart_runtime()

    assert supervisor.waited
    assert status["state"] == "failed"
    assert status["active_port"] is None
    assert "did not become ready" in status["error"]


def test_restart_does_not_start_if_supervisor_will_not_stop(monkeypatch):
    model_dir = "C:/models/LLM"
    set_status_dependencies(monkeypatch, model_dir)
    monkeypatch.setattr(runtime, "_auto_start", True)
    monkeypatch.setattr(runtime, "_ctx_size", 4096)
    monkeypatch.setattr(runtime, "_port", 18582)
    monkeypatch.setattr(runtime, "_model_dir", model_dir)
    monkeypatch.setattr(runtime, "_process", FakeProcess(fail_wait=True))
    monkeypatch.setattr(runtime, "_state", "running")
    monkeypatch.setattr(runtime, "_start_attempted", True)
    monkeypatch.setattr(runtime, "_SUPERVISOR_SHUTDOWN_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(
        runtime,
        "_start_locked",
        lambda **_kwargs: pytest.fail(
            "must not start before the old supervisor stops"
        ),
    )

    status = runtime.restart_runtime()

    assert status["state"] == "failed"
    assert "shutdown timeout" in status["error"]


class LocalRequest:
    headers = {}
    remote = "127.0.0.1"
    host = "127.0.0.1"


def test_restart_endpoint_requires_local_request_and_enabled_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "_auto_start", False)

    remote_request = LocalRequest()
    remote_request.remote = "192.168.1.20"
    remote_response = asyncio.run(runtime.restart_runtime_endpoint(remote_request))
    assert remote_response.status == 403

    local_response = asyncio.run(runtime.restart_runtime_endpoint(LocalRequest()))
    assert local_response.status == 409
    assert "Enable" in json.loads(local_response.text)["error"]
