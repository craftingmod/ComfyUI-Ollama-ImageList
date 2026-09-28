from __future__ import annotations

import atexit
import asyncio
import ipaddress
import json
import logging
import shutil
import socket
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

RUNTIME_ROUTE = "/ollama_image_list/llama_cpp/runtime"
_PORT = 8080
_CONFIG_NAME = "settings.json"
_VERSION_PROBE_TIMEOUT = 3
_VERSION_DISPLAY_LIMIT = 256
_logger = logging.getLogger(__name__)
_lock = Lock()
_auto_start = False
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


def _load_auto_start() -> bool:
    global _last_error
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except RuntimeError as exc:
        _last_error = str(exc)
        _logger.error("Internal llama.cpp configuration is unavailable: %s", exc)
        return False
    except (OSError, json.JSONDecodeError) as exc:
        _last_error = f"Could not read internal llama.cpp settings: {exc}"
        _logger.warning("Could not read internal llama.cpp settings: %s", exc)
        return False
    return isinstance(data, dict) and data.get("auto_start") is True


def _save_auto_start(value: bool) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"auto_start": value}, indent=2) + "\n", encoding="utf-8"
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
    global _process, _start_attempted, _last_error
    process = _process
    _process = None
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
    global _process, _start_attempted, _last_error
    if _process is not None and _process.poll() is None:
        return
    if _start_attempted:
        return
    _start_attempted = True

    executable = _llama_executable()
    if executable is None:
        _last_error = "'llama' executable was not found in PATH."
        _logger.warning("Internal llama.cpp auto-start failed: %s", _last_error)
        return

    try:
        import folder_paths

        with socket.socket() as port_probe:
            port_probe.bind(("127.0.0.1", _PORT))
        models_dir = Path(folder_paths.models_dir) / "LLM"
        models_dir.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(_PORT),
            "--models-dir",
            str(models_dir),
            "--models-max",
            "1",
            "--ctx-size",
            "16384",
            "--cors-origins",
            "localhost",
        ]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        _process = process
        time.sleep(0.2)
        exit_code = process.poll()
        if exit_code is not None:
            _process = None
            _last_error = (
                f"llama server exited during startup with code {exit_code} on "
                f"port {_PORT}; the port may already be in use."
            )
            _logger.error("Internal llama.cpp auto-start failed: %s", _last_error)
        else:
            _last_error = None
    except OSError as exc:
        _last_error = f"Could not start llama server on port {_PORT}: {exc}"
        _logger.error("%s", _last_error, exc_info=True)


def initialize_llama_cpp_runtime() -> None:
    global _auto_start
    with _lock:
        _auto_start = _load_auto_start()
        if _auto_start:
            _start_locked()


def _runtime_status_locked() -> dict[str, Any]:
    global _process, _last_error
    if _process is not None:
        exit_code = _process.poll()
        if exit_code is not None:
            _process = None
            _last_error = f"llama server exited with code {exit_code}."
    executable = _llama_executable()
    return {
        "auto_start": _auto_start,
        "llama_available": executable is not None,
        "llama_executable": executable,
        "llama_version": _probe_llama_version(executable),
        "running": _process is not None,
        "error": _last_error,
    }


def get_runtime_status() -> dict[str, Any]:
    with _lock:
        return _runtime_status_locked()


def set_auto_start(value: bool) -> dict[str, Any]:
    global _auto_start
    with _lock:
        _save_auto_start(value)
        _auto_start = value
        if value:
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
    if not isinstance(data, dict) or not isinstance(data.get("auto_start"), bool):
        return web.json_response(
            {"error": "auto_start must be a boolean."}, status=400
        )
    try:
        status = await asyncio.to_thread(set_auto_start, data["auto_start"])
        return web.json_response(status)
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
    "set_auto_start",
    "update_runtime_endpoint",
]
