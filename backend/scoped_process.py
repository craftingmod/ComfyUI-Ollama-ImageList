from __future__ import annotations

import ctypes
import logging
import os
import signal
import subprocess
from typing import Any

_logger = logging.getLogger(__name__)
_TERMINATE_TIMEOUT_SECONDS = 5


def _create_kill_on_close_job() -> tuple[Any, Any]:
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        handle,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(handle)
        raise error
    return kernel32, handle


class ScopedProcess:
    """Own one process and the process tree created inside its OS scope."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        job_api: Any = None,
        job_handle: Any = None,
        process_group_id: int | None = None,
    ) -> None:
        self._process = process
        self._job_api = job_api
        self._job_handle = job_handle
        self._process_group_id = process_group_id
        self._closed = False

    @classmethod
    def start(cls, *args: Any, **kwargs: Any) -> ScopedProcess:
        job_api = job_handle = None
        if os.name == "nt":
            try:
                job_api, job_handle = _create_kill_on_close_job()
            except (AttributeError, OSError) as exc:
                _logger.warning(
                    "Could not create a Windows Job Object; falling back to "
                    "direct-process cleanup: %s",
                    exc,
                )
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(*args, **kwargs)
        except BaseException:
            if job_handle is not None:
                job_api.CloseHandle(job_handle)
            raise

        if job_handle is not None:
            try:
                process_id = getattr(process, "pid", None)
                if not isinstance(process_id, int):
                    raise OSError("spawned process did not expose its process ID")
                _assign_process_to_job(job_api, job_handle, process_id)
            except OSError as exc:
                _logger.warning(
                    "Could not assign llama-server supervisor to a Windows Job "
                    "Object; falling back to direct-process cleanup: %s",
                    exc,
                )
                job_api.CloseHandle(job_handle)
                job_api = job_handle = None

        process_group_id = None
        if os.name != "nt":
            try:
                process_id = getattr(process, "pid", None)
                if isinstance(process_id, int):
                    process_group_id = os.getpgid(process_id)
            except OSError:
                # start_new_session makes the child its own session and group leader.
                process_group_id = process_id
        return cls(
            process,
            job_api=job_api,
            job_handle=job_handle,
            process_group_id=process_group_id,
        )

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def stdin(self):
        return self._process.stdin

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def graceful_shutdown(self, timeout: float = 8) -> bool:
        if self.poll() is not None:
            return True
        owner_pipe = self._process.stdin
        if owner_pipe is not None and not owner_pipe.closed:
            try:
                owner_pipe.close()
            except OSError:
                _logger.debug("Could not close process lifetime pipe", exc_info=True)
                self._send_graceful_signal()
        else:
            self._send_graceful_signal()
        try:
            self.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    def terminate(self) -> None:
        if self.poll() is not None:
            return
        if os.name == "nt":
            try:
                self._process.send_signal(signal.CTRL_BREAK_EVENT)
                return
            except (AttributeError, OSError, ValueError):
                if self._job_handle is None:
                    terminate = getattr(self._process, "terminate", None)
                    if callable(terminate):
                        terminate()
                return
        try:
            process_group_id = os.getpgid(self.pid)
            os.killpg(process_group_id, signal.SIGTERM)
        except (AttributeError, OSError):
            if self.poll() is None:
                terminate = getattr(self._process, "terminate", None)
                if callable(terminate):
                    terminate()

    def kill(self) -> None:
        if self._job_handle is not None:
            if self._job_api.TerminateJobObject(self._job_handle, 1):
                return
        if os.name != "nt":
            try:
                process_group_id = (
                    os.getpgid(self.pid)
                    if self.poll() is None
                    else self._process_group_id
                )
                if process_group_id is not None:
                    os.killpg(process_group_id, signal.SIGKILL)
                return
            except (AttributeError, OSError):
                pass
        if self.poll() is None:
            kill = getattr(self._process, "kill", None)
            if callable(kill):
                kill()

    def close(
        self,
        graceful_timeout: float = 8,
        terminate_timeout: float = _TERMINATE_TIMEOUT_SECONDS,
    ) -> None:
        if self._closed:
            return
        try:
            if not self.graceful_shutdown(timeout=graceful_timeout):
                try:
                    self.terminate()
                except OSError:
                    _logger.debug("Could not terminate process scope", exc_info=True)
                try:
                    self.wait(timeout=terminate_timeout)
                except subprocess.TimeoutExpired:
                    self.kill()
                    self.wait(timeout=terminate_timeout)
        finally:
            self._close_job()
        self._closed = True

    def _send_graceful_signal(self) -> None:
        if self.poll() is not None:
            return
        try:
            if os.name == "nt":
                self._process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(self.pid), signal.SIGINT)
        except (AttributeError, OSError, ValueError):
            _logger.debug("Could not send a graceful stop signal", exc_info=True)

    def _close_job(self) -> None:
        if self._job_handle is None:
            return
        if not self._job_api.CloseHandle(self._job_handle):
            _logger.warning(
                "Could not close the llama-server Job Object; terminating its "
                "process tree"
            )
            self._job_api.TerminateJobObject(self._job_handle, 1)
            if not self._job_api.CloseHandle(self._job_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        self._job_handle = None
        self._job_api = None


def _assign_process_to_job(job_api: Any, job_handle: Any, pid: int) -> None:
    from ctypes import wintypes

    job_api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    job_api.OpenProcess.restype = wintypes.HANDLE
    job_api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    job_api.AssignProcessToJobObject.restype = wintypes.BOOL
    job_api.CloseHandle.argtypes = (wintypes.HANDLE,)
    job_api.CloseHandle.restype = wintypes.BOOL

    process_handle = job_api.OpenProcess(0x0001 | 0x0100, False, pid)
    if not process_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not job_api.AssignProcessToJobObject(job_handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        job_api.CloseHandle(process_handle)
