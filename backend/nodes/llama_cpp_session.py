from __future__ import annotations

import json
import time
from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI builds
    from comfy_api.latest import io

from ..backends.llama_cpp import LlamaCppSession
from ..backends.llama_cpp_server import LlamaCppServerSession
from ..core import normalize_media, unwrap_required_scalar
from .llama_cpp_compact import (
    COMPACT_CATEGORY,
    LlamaCppHardwareRuntimeProfileType,
    LlamaCppModelProfileType,
    LlamaCppReasoningConfigType,
    LlamaCppSpeculativeConfigType,
    build_compact_session_kwargs,
)
from .llama_cpp_diagnostics import LlamaCppMediaDiagnosticsType
from .llama_cpp_generate import NO_MMPROJ_OPTION, _gguf_options

LlamaCppSessionType = io.Custom("OLLAMA_IMAGE_LIST_LLAMA_CPP_SESSION")


class LlamaCppConnectSessionNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppConnectSession",
            display_name="[llama.cpp] Connect Session",
            category=f"{COMPACT_CATEGORY}/session",
            description=(
                "Creates a session handle for a llama.cpp server. Connect fetches model IDs; "
                "the saved model string remains the value used for generation."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=[
                io.String.Input(
                    "url",
                    default="http://127.0.0.1:8080",
                    tooltip="llama.cpp server base URL. Only HTTP and HTTPS are accepted.",
                ),
                io.Combo.Input(
                    "available_models",
                    options=[],
                    default="",
                    tooltip="Models reported by the configured llama.cpp server.",
                ),
                io.String.Input(
                    "model",
                    default="",
                    tooltip=(
                        "Saved model ID used for generation. Selecting available_models "
                        "copies its ID here."
                    ),
                ),
            ],
            outputs=[LlamaCppSessionType.Output("session", display_name="session")],
        )

    @classmethod
    def fingerprint_inputs(cls, **_kwargs: Any) -> int:
        return time.monotonic_ns()

    @classmethod
    def validate_inputs(cls, available_models: str) -> bool:
        del available_models
        return True

    @classmethod
    def execute(cls, url: Any, available_models: Any, model: Any) -> io.NodeOutput:
        resolved_url = unwrap_required_scalar("url", url)
        resolved_model = unwrap_required_scalar("model", model)
        del available_models
        return io.NodeOutput(
            LlamaCppServerSession(
                url=str(resolved_url),
                model=str(resolved_model),
            )
        )


class LlamaCppCreateSessionNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        model_options, mmproj_options = _gguf_options()
        return io.Schema(
            node_id="OllamaImageList_LlamaCppCreateSession",
            display_name="[llama.cpp] Create Session",
            category=f"{COMPACT_CATEGORY}/session",
            description=(
                "Keeps one Llama.cpp model resident until Llama.cpp Unload Session. "
                "Sessions left open during an interrupted workflow unload at prompt end. "
                "Place this before Start Loop and carry its session through End Loop."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=[
                io.Combo.Input(
                    "model_path", options=model_options, default=model_options[0]
                ),
                io.Combo.Input(
                    "mmproj_path", options=mmproj_options, default=NO_MMPROJ_OPTION
                ),
                LlamaCppModelProfileType.Input("model_profile"),
                LlamaCppHardwareRuntimeProfileType.Input(
                    "hardware_profile", optional=True
                ),
                LlamaCppReasoningConfigType.Input("reasoning", optional=True),
                LlamaCppSpeculativeConfigType.Input("speculative", optional=True),
                io.Int.Input("n_ctx", default=8_192, min=512, max=1_048_576, step=512),
                io.Int.Input("image_min_tokens", default=0, min=0, max=65_536),
                io.Int.Input("image_max_tokens", default=0, min=0, max=65_536),
                io.Boolean.Input("verbose", default=False, advanced=True),
            ],
            outputs=[LlamaCppSessionType.Output("session", display_name="session")],
        )

    @classmethod
    def fingerprint_inputs(cls, **_kwargs: Any) -> int:
        return time.monotonic_ns()

    @classmethod
    def execute(cls, **values: Any) -> io.NodeOutput:
        return io.NodeOutput(LlamaCppSession(**build_compact_session_kwargs(**values)))


class LlamaCppSessionGenerateNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppSessionGenerate",
            display_name="[llama.cpp] Generate (Session)",
            category=f"{COMPACT_CATEGORY}/session",
            description=(
                "Runs one request on a local or server-backed llama.cpp session and "
                "carries it forward."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=[
                LlamaCppSessionType.Input("session"),
                io.String.Input(
                    "system", default="", multiline=True, dynamic_prompts=False
                ),
                io.String.Input(
                    "prompt", default="", multiline=True, dynamic_prompts=False
                ),
                io.Int.Input("max_tokens", default=512, min=1, max=131_072, step=1),
                io.Int.Input("seed", default=-1, min=-1, max=0xFFFFFFFF, step=1),
                io.String.Input("stop", default="", advanced=True),
                io.Image.Input("images", optional=True),
                io.Audio.Input("audio", optional=True),
                io.Video.Input("video", optional=True),
                io.Boolean.Input("video_with_audio", default=False),
            ],
            outputs=[
                io.String.Output("response", display_name="response"),
                io.String.Output("thinking", display_name="thinking"),
                io.String.Output("raw_json", display_name="raw JSON"),
                io.String.Output("metrics_json", display_name="metrics"),
                LlamaCppMediaDiagnosticsType.Output(
                    "media_diagnostics", display_name="media diagnostics"
                ),
                LlamaCppSessionType.Output("session", display_name="session"),
            ],
        )

    @classmethod
    def execute(
        cls,
        session: Any,
        system: Any,
        prompt: Any,
        max_tokens: Any,
        seed: Any,
        stop: Any,
        images: Any = None,
        audio: Any = None,
        video: Any = None,
        video_with_audio: Any = False,
    ) -> io.NodeOutput:
        resolved_session = unwrap_required_scalar("session", session)
        if not isinstance(resolved_session, (LlamaCppSession, LlamaCppServerSession)):
            raise TypeError("session must be a Llama.cpp Create or Connect Session output.")
        bundle = normalize_media(
            images=images,
            audio=audio,
            video=video,
            video_with_audio=bool(
                unwrap_required_scalar("video_with_audio", video_with_audio)
            ),
            audio_sample_rate=16_000,
            audio_channels=1,
        )
        result = resolved_session.generate(
            system=str(unwrap_required_scalar("system", system)),
            prompt=str(unwrap_required_scalar("prompt", prompt)),
            media=bundle,
            max_tokens=int(unwrap_required_scalar("max_tokens", max_tokens)),
            seed=int(unwrap_required_scalar("seed", seed)),
            stop=str(unwrap_required_scalar("stop", stop)),
        )
        return io.NodeOutput(
            result.response,
            result.thinking,
            json.dumps(result.raw, ensure_ascii=False, indent=2),
            json.dumps(result.metrics, ensure_ascii=False, indent=2),
            result.media_diagnostics,
            resolved_session,
        )


class LlamaCppUnloadSessionNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppUnloadSession",
            display_name="[llama.cpp] Unload Session",
            category=f"{COMPACT_CATEGORY}/session",
            description=(
                "Unloads a local or server-backed Llama.cpp session. Connect session and "
                "a final End Loop result to timing so unloading runs after the loop."
            ),
            is_input_list=True,
            is_output_node=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=[
                LlamaCppSessionType.Input("session"),
                io.Custom("*").Input(
                    "timing",
                    optional=True,
                    tooltip="Optional execution dependency. Its value is ignored.",
                ),
            ],
            outputs=[],
        )

    @classmethod
    def execute(cls, session: Any, timing: Any = None) -> io.NodeOutput:
        del timing
        resolved_session = unwrap_required_scalar("session", session)
        if not isinstance(resolved_session, (LlamaCppSession, LlamaCppServerSession)):
            raise TypeError("session must be a Llama.cpp Create or Connect Session output.")
        resolved_session.close()
        return io.NodeOutput()


__all__ = [
    "LlamaCppConnectSessionNode",
    "LlamaCppCreateSessionNode",
    "LlamaCppSessionGenerateNode",
    "LlamaCppSessionType",
    "LlamaCppUnloadSessionNode",
]
