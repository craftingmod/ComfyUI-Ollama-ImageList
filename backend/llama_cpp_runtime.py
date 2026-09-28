from __future__ import annotations

import atexit
import asyncio
import ipaddress
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

from .llm_model_paths import (
    get_default_llm_model_directory,
    get_llm_model_directories,
    resolve_llm_model_directory,
)

RUNTIME_ROUTE = "/ollama_image_list/llama_cpp/runtime"
_DEFAULT_PORT = 18582
_MIN_PORT = 1024
_MAX_PORT = 65535
_CONFIG_NAME = "settings.json"
_DEFAULT_CTX_SIZE = 16384
_MIN_CTX_SIZE = 512
_MAX_CTX_SIZE = 1048576
_VERSION_PROBE_TIMEOUT = 3
_VERSION_DISPLAY_LIMIT = 256
_logger = logging.getLogger(__name__)
_lock = Lock()
_auto_start = False
_ctx_size = _DEFAULT_CTX_SIZE
_port = _DEFAULT_PORT
_model_dir: str | None = None
_active_port: int | None = None
_start_attempted = False
_process: subprocess.Popen[bytes] | None = None
_last_error: str | None = None
_routes_registered = False
_version_probe_executable: str | None = None
_llama_version: str | None = None
_CONFIG_DIRECTORY_ERROR = (
    "This ComfyUI version does not provide the protected system user directory "
    "API; internal llama.cpp settings are unavailable."
)


def _config_path() -> Path:
    import folder_paths

    get_system_user_directory = getattr(
        folder_paths, "get_system_user_directory", None
    )
    if callable(get_system_user_directory):
        return Path(get_system_user_directory("llama_cpp")) / _CONFIG_NAME
    raise RuntimeError(_CONFIG_DIRECTORY_ERROR)


def _valid_ctx_size(value: Any) -> bool:
    return type(value) is int and _MIN_CTX_SIZE <= value <= _MAX_CTX_SIZE


def _valid_port(value: Any) -> bool:
    return type(value) is int and _MIN_PORT <= value <= _MAX_PORT


def _model_directory_options() -> tuple[list[str], str]:
    import folder_paths

    default_model_dir = get_default_llm_model_directory(folder_paths)
    model_dirs = get_llm_model_directories(folder_paths)
    default_identity = os.path.normcase(default_model_dir)
    ordered_model_dirs = [
        default_model_dir,
        *(path for path in model_dirs if os.path.normcase(path) != default_identity),
    ]
    return ordered_model_dirs, default_model_dir


def _load_runtime_settings(
    model_dirs: list[str], default_model_dir: str
) -> tuple[bool, int, int, str]:
    global _last_error
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, _DEFAULT_CTX_SIZE, _DEFAULT_PORT, default_model_dir
    except RuntimeError as exc:
        _last_error = str(exc)
        _logger.error("Internal llama.cpp configuration is unavailable: %s", exc)
        return False, _DEFAULT_CTX_SIZE, _DEFAULT_PORT, default_model_dir
    except (OSError, json.JSONDecodeError) as exc:
        _last_error = f"Could not read internal llama.cpp settings: {exc}"
        _logger.warning("Could not read internal llama.cpp settings: %s", exc)
        return False, _DEFAULT_CTX_SIZE, _DEFAULT_PORT, default_model_dir
    if not isinstance(data, dict):
        _logger.warning("Internal llama.cpp settings must be a JSON object.")
        return False, _DEFAULT_CTX_SIZE, _DEFAULT_PORT, default_model_dir
    ctx_size = data.get("ctx_size", _DEFAULT_CTX_SIZE)
    if not _valid_ctx_size(ctx_size):
        _logger.warning("Ignoring invalid context size in internal llama.cpp settings.")
        ctx_size = _DEFAULT_CTX_SIZE
    port = data.get("port", _DEFAULT_PORT)
    if not _valid_port(port):
        _logger.warning("Ignoring invalid port in internal llama.cpp settings.")
        port = _DEFAULT_PORT
    model_dir = data.get("model_dir", default_model_dir)
    resolved_model_dir = (
        resolve_llm_model_directory(model_dir, model_dirs)
        if isinstance(model_dir, str)
        else None
    )
    if resolved_model_dir is None:
        _logger.warning("Ignoring unavailable LLM model directory in settings.")
        resolved_model_dir = default_model_dir
    return data.get("auto_start") is True, ctx_size, port, resolved_model_dir


def _save_runtime_settings(
    auto_start: bool, ctx_size: int, port: int, model_dir: str
) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "auto_start": auto_start,
                "ctx_size": ctx_size,
                "port": port,
                "model_dir": model_dir,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _llama_executable() -> str | None:
    executable = shutil.which("llama")
    return str(Path(executable).resolve()) if executable else None


def _probe_llama_version(executable: str | None) -> str | None:
    global _version_probe_executable, _llama_version
    if not executable:
        return None
    if executable == _version_probe_executable:
        return _llama_version

    _version_probe_executable = executable
    _llama_version = None
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERSION_PROBE_TIMEOUT,
            check=True,
            shell=False,
        )
        lines = (result.stdout + "\n" + result.stderr).splitlines()
        version_line = next(
            (
                line.strip()
                for line in lines
                if line.strip().lower().startswith("version:")
            ),
            next((line.strip() for line in lines if line.strip()), None),
        )
        _llama_version = (
            version_line[:_VERSION_DISPLAY_LIMIT] if version_line else None
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _logger.warning("Could not probe llama version: %s", exc)
    return _llama_version


def _stop_locked() -> None:
    global _process, _active_port, _start_attempted, _last_error
    process = _process
    _process = None
    _active_port = None
    _start_attempted = False
    _last_error = None
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start_locked() -> None:
    global _process, _active_port, _start_attempted, _last_error, _model_dir
    if _process is not None and _process.poll() is None:
        return
    if _start_attempted:
        return
    _start_attempted = True

    executable = _llama_executable()
    if executable is None:
        _active_port = None
        _last_error = "'llama' executable was not found in PATH."
        _logger.warning("Internal llama.cpp auto-start failed: %s", _last_error)
        return

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
            port_probe.bind(("127.0.0.1", _port))
        model_dirs, default_model_dir = _model_directory_options()
        models_dir_path = (
            resolve_llm_model_directory(_model_dir, model_dirs)
            if _model_dir
            else None
        )
        if models_dir_path is None:
            _model_dir = default_model_dir
            _save_runtime_settings(_auto_start, _ctx_size, _port, _model_dir)
            models_dir_path = default_model_dir
        models_dir = Path(models_dir_path)
        models_dir.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(_port),
            "--models-dir",
            str(models_dir),
            "--models-max",
            "1",
            "--ctx-size",
            str(_ctx_size),
            "--cors-origins",
            "localhost",
        ]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        _process = process
        _active_port = _port
        time.sleep(0.2)
        exit_code = process.poll()
        if exit_code is not None:
            _process = None
            _active_port = None
            _last_error = (
                f"llama server exited during startup with code {exit_code} on "
                f"port {_port}; the port may already be in use."
            )
            _logger.error("Internal llama.cpp auto-start failed: %s", _last_error)
        else:
            _last_error = None
    except OSError as exc:
        _active_port = None
        _last_error = f"Could not start llama server on port {_port}: {exc}"
        _logger.error("%s", _last_error, exc_info=True)


def initialize_llama_cpp_runtime() -> None:
    global _auto_start, _ctx_size, _port, _model_dir
    with _lock:
        model_dirs, default_model_dir = _model_directory_options()
        _auto_start, _ctx_size, _port, _model_dir = _load_runtime_settings(
            model_dirs, default_model_dir
        )
        if _auto_start:
            _start_locked()


def _runtime_status_locked() -> dict[str, Any]:
    global _process, _active_port, _last_error
    if _process is not None:
        exit_code = _process.poll()
        if exit_code is not None:
            _process = None
            _active_port = None
            _last_error = f"llama server exited with code {exit_code}."
    executable = _llama_executable()
    model_dirs, default_model_dir = _model_directory_options()
    model_dir = (
        resolve_llm_model_directory(_model_dir, model_dirs) if _model_dir else None
    )
    if model_dir is None:
        model_dir = default_model_dir
    return {
        "auto_start": _auto_start,
        "ctx_size": _ctx_size,
        "port": _port,
        "active_port": _active_port,
        "model_dir": model_dir,
        "model_dirs": model_dirs,
        "default_model_dir": default_model_dir,
        "llama_available": executable is not None,
        "llama_executable": executable,
        "llama_version": _probe_llama_version(executable),
        "running": _process is not None,
        "error": _last_error,
    }


def get_runtime_status() -> dict[str, Any]:
    with _lock:
        return _runtime_status_locked()


def update_runtime_settings(
    auto_start: bool | None = None,
    ctx_size: int | None = None,
    port: int | None = None,
    model_dir: str | None = None,
) -> dict[str, Any]:
    global _auto_start, _ctx_size, _port, _model_dir
    with _lock:
        next_auto_start = _auto_start if auto_start is None else auto_start
        next_ctx_size = _ctx_size if ctx_size is None else ctx_size
        next_port = _port if port is None else port
        next_model_dir = _model_dir
        if model_dir is not None:
            model_dirs, _default_model_dir = _model_directory_options()
            next_model_dir = resolve_llm_model_directory(model_dir, model_dirs)
            if next_model_dir is None:
                raise ValueError(
                    "model_dir must be one of the available LLM directories."
                )
        if next_model_dir is None:
            _model_dirs, next_model_dir = _model_directory_options()
        assert next_model_dir is not None
        _save_runtime_settings(
            next_auto_start, next_ctx_size, next_port, next_model_dir
        )
        _auto_start, _ctx_size, _port, _model_dir = (
            next_auto_start,
            next_ctx_size,
            next_port,
            next_model_dir,
        )
        if auto_start is not None:
            if auto_start:
                _start_locked()
            else:
                _stop_locked()
        return _runtime_status_locked()


def _is_local_request(request: Any) -> bool:
    if any(
        name.lower() == "forwarded"
        or name.lower().startswith("x-forwarded-")
        or name.lower() in {"x-real-ip", "x-client-ip"}
        for name in request.headers
    ):
        return False
    remote = request.remote
    if not remote:
        return False
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    mapped_address = getattr(address, "ipv4_mapped", None)
    if not (address.is_loopback or (mapped_address and mapped_address.is_loopback)):
        return False
    host = urlsplit(f"//{request.host}").hostname
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def runtime_status_endpoint(request: Any):
    if not _is_local_request(request):
        return web.json_response(
            {"error": "Runtime status is only available locally."}, status=403
        )
    return web.json_response(await asyncio.to_thread(get_runtime_status))


async def update_runtime_endpoint(request: Any):
    if not _is_local_request(request):
        return web.json_response(
            {"error": "This setting can only be changed locally."}, status=403
        )
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Request body must be valid JSON."}, status=400
        )
    if (
        not isinstance(data, dict)
        or not data
        or data.keys() - {"auto_start", "ctx_size", "port", "model_dir"}
        or (
            "auto_start" in data
            and not isinstance(data["auto_start"], bool)
        )
        or ("ctx_size" in data and not _valid_ctx_size(data["ctx_size"]))
        or ("port" in data and not _valid_port(data["port"]))
        or ("model_dir" in data and not isinstance(data["model_dir"], str))
    ):
        return web.json_response(
            {
                "error": (
                    "Provide auto_start as a boolean, ctx_size as an integer "
                    f"from {_MIN_CTX_SIZE} to {_MAX_CTX_SIZE}, port as an "
                    f"integer from {_MIN_PORT} to {_MAX_PORT}, and/or model_dir "
                    "as an available LLM directory."
                )
            },
            status=400,
        )
    try:
        status = await asyncio.to_thread(
            update_runtime_settings,
            auto_start=data.get("auto_start"),
            ctx_size=data.get("ctx_size"),
            port=data.get("port"),
            model_dir=data.get("model_dir"),
        )
        return web.json_response(status)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (OSError, RuntimeError) as exc:
        _logger.exception("Could not save internal llama.cpp settings.")
        return web.json_response({"error": str(exc)}, status=500)


def register_runtime_routes() -> None:
    global _routes_registered
    if _routes_registered:
        return
    from server import PromptServer

    PromptServer.instance.routes.get(RUNTIME_ROUTE)(runtime_status_endpoint)
    PromptServer.instance.routes.post(RUNTIME_ROUTE)(update_runtime_endpoint)
    _routes_registered = True


def _stop_at_exit() -> None:
    with _lock:
        _stop_locked()


atexit.register(_stop_at_exit)


__all__ = [
    "RUNTIME_ROUTE",
    "get_runtime_status",
    "initialize_llama_cpp_runtime",
    "register_runtime_routes",
    "runtime_status_endpoint",
    "update_runtime_endpoint",
    "update_runtime_settings",
]
