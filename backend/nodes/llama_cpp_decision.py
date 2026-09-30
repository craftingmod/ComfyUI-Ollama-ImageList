from __future__ import annotations

import json
from collections.abc import Mapping
from time import perf_counter
from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI builds
    from comfy_api.latest import io

from ..backends.llama_cpp import LlamaCppDecisionResult, LlamaCppSession
from ..backends.llama_cpp_server import LlamaCppServerSession
from ..core import (
    InputNormalizationError,
    normalize_media,
    unwrap_optional_scalar,
    unwrap_required_scalar,
)
from .llama_cpp_compact import (
    BASE_CATEGORY,
    LlamaCppModelProfileType,
    normalize_compact_model_profile,
)
from .llama_cpp_diagnostics import LlamaCppMediaDiagnosticsType
from .llama_cpp_session import LlamaCppSessionType

LlamaCppQuestionType = io.Custom("OLLAMA_IMAGE_LIST_LLAMA_CPP_QUESTION")
MAX_ANSWERS = 26


def make_question_payload(question: Any, answers: Any) -> dict[str, Any]:
    if not isinstance(question, str) or not question.strip():
        raise InputNormalizationError("question must be a non-empty string.")
    if not isinstance(answers, (list, tuple)):
        raise InputNormalizationError("answer must be a list of strings.")
    if not 2 <= len(answers) <= MAX_ANSWERS:
        raise InputNormalizationError("answer must contain between 2 and 26 values.")
    if any(not isinstance(answer, str) for answer in answers):
        raise InputNormalizationError("answer values must be strings.")
    if any(not answer.strip() for answer in answers):
        raise InputNormalizationError("answer values must be non-empty strings.")
    if len(set(answers)) != len(answers):
        raise InputNormalizationError("answer values must be unique.")
    return {"question": question, "answer": list(answers)}


def _question_from_input_lists(question: Any, answers: Any) -> dict[str, Any]:
    if not isinstance(question, list) or len(question) != 1:
        raise InputNormalizationError(
            "question must resolve to exactly one STRING value."
        )
    if not isinstance(answers, list) or any(
        isinstance(value, (list, tuple)) for value in answers
    ):
        raise InputNormalizationError("answer must be one flat ComfyUI STRING list.")
    return make_question_payload(question[0], answers)


class LlamaCppCreateQuestionFromInputNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LlamaCppMtmd_CreateQuestionFromInput",
            display_name="[llama.cpp] Create Question From Input",
            category=f"{BASE_CATEGORY}/decision",
            description=(
                "Combines one STRING question with a flat ComfyUI STRING list of answers."
            ),
            is_input_list=True,
            is_experimental=True,
            inputs=[
                io.String.Input(
                    "question",
                    default="",
                    multiline=True,
                    dynamic_prompts=False,
                    force_input=True,
                ),
                io.String.Input("answer", force_input=True),
            ],
            outputs=[LlamaCppQuestionType.Output("question")],
        )

    @classmethod
    def execute(cls, question: Any, answer: Any) -> io.NodeOutput:
        return io.NodeOutput(_question_from_input_lists(question, answer))


class LlamaCppDecideSessionNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LlamaCppMtmd_Decide",
            display_name="[llama.cpp] Decide",
            category=f"{BASE_CATEGORY}/decision",
            description=(
                "Scores letter-token choices with a Native Session prefill or a Runtime "
                "or Connect Session's constrained llama-server completion. Optional media "
                "is added to the context; question and answers remain text-only."
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
                    "context", default="", multiline=True, dynamic_prompts=False
                ),
                LlamaCppQuestionType.Input("question"),
                io.Image.Input("images", optional=True),
                io.Audio.Input("audio", optional=True),
                io.Video.Input("video", optional=True),
                io.Boolean.Input("video_with_audio", default=False),
                io.Int.Input(
                    "seed",
                    default=-1,
                    min=-1,
                    max=0xFFFFFFFF,
                    step=1,
                    tooltip=(
                        "Runtime completion seed; Native prefill scoring is deterministic."
                    ),
                ),
                LlamaCppModelProfileType.Input(
                    "model_profile",
                    optional=True,
                    tooltip=(
                        "Optional override; server sessions apply sampling and explicit "
                        "on/off reasoning settings per request."
                    ),
                ),
                io.Boolean.Input(
                    "session_unload",
                    default=False,
                    label_on="Unload",
                    label_off="Keep",
                    tooltip="Unload the session after the decision completes.",
                ),
            ],
            outputs=[
                io.String.Output("selected"),
                io.String.Output(
                    "probabilities_json", display_name="probabilities_json"
                ),
                io.String.Output("metrics_json", display_name="metrics"),
                LlamaCppMediaDiagnosticsType.Output(
                    "media_diagnostics", display_name="media_diagnostics"
                ),
                LlamaCppSessionType.Output("session", display_name="session"),
            ],
        )

    @classmethod
    def execute(
        cls,
        session: Any,
        system: Any,
        context: Any,
        question: Any,
        images: Any = None,
        audio: Any = None,
        video: Any = None,
        video_with_audio: Any = False,
        seed: Any = -1,
        model_profile: Any = None,
        session_unload: Any = False,
    ) -> io.NodeOutput:
        resolved_session = unwrap_required_scalar("session", session)
        if not isinstance(
            resolved_session, (LlamaCppSession, LlamaCppServerSession)
        ):
            raise InputNormalizationError(
                "Decide requires [llama.cpp] Create Native Session or "
                "a llama.cpp server session."
            )
        payload = unwrap_required_scalar("question", question)
        if not isinstance(payload, Mapping) or set(payload) != {"question", "answer"}:
            raise InputNormalizationError(
                "question must come from a [llama.cpp] Create Question From Input node."
            )
        validated = make_question_payload(payload["question"], payload["answer"])
        resolved_system = unwrap_required_scalar("system", system)
        resolved_context = unwrap_required_scalar("context", context)
        if not isinstance(resolved_system, str) or not isinstance(
            resolved_context, str
        ):
            raise InputNormalizationError("system and context must be strings.")
        profile_value = unwrap_optional_scalar("model_profile", model_profile, None)
        profile = (
            normalize_compact_model_profile(profile_value)
            if profile_value is not None
            else None
        )
        context_parts = [
            f"System:\n{resolved_system}" if resolved_system else "",
            f"Context:\n{resolved_context}" if resolved_context else "",
        ]
        decision_context = "\n\n".join(part for part in context_parts if part)
        media = normalize_media(
            images=images,
            audio=audio,
            video=video,
            video_with_audio=bool(
                unwrap_required_scalar("video_with_audio", video_with_audio)
            ),
            audio_sample_rate=16_000,
            audio_channels=1,
        )
        request = {
            "question": validated["question"],
            "context": decision_context,
            "answers": validated["answer"],
            "media": media,
        }
        resolved_seed = int(unwrap_required_scalar("seed", seed))
        if resolved_seed < -1 or resolved_seed > 0xFFFFFFFF:
            raise InputNormalizationError("seed must be between -1 and 4294967295.")
        if (
            isinstance(resolved_session, LlamaCppServerSession) and resolved_seed >= 0
        ):
            request["seed"] = resolved_seed
        if profile is not None:
            request["model_profile"] = profile
        started = perf_counter()
        decision = resolved_session.decide(**request)
        elapsed_ms = (perf_counter() - started) * 1000
        if isinstance(decision, LlamaCppDecisionResult):
            selected = decision.selected
            probabilities = decision.probabilities
            metrics = dict(decision.metrics)
            media_diagnostics = dict(decision.media_diagnostics)
        else:
            selected, probabilities = decision
            metrics = {"decision_duration_ms": elapsed_ms}
            media_diagnostics = {
                "schema_version": 1,
                "backend": "llama.cpp-decision",
                "requested": media.manifest(),
                "evaluated": {
                    "image_count": 0,
                    "audio_count": 0,
                    "video_count": 0,
                },
                "mtmd": {
                    "completion_succeeded": True,
                    "all_media_evaluated": not media.items,
                    "verification": "no_media" if not media.items else "unverified",
                },
                "model_unloaded_after_response": False,
            }
        ordered_probabilities = {
            answer: probabilities[answer] for answer in validated["answer"]
        }
        unloaded = bool(unwrap_required_scalar("session_unload", session_unload))
        if unloaded:
            resolved_session.close()
        metrics.update(
            operation="decide",
            seed=resolved_seed,
            model_unloaded=unloaded,
        )
        if isinstance(metrics.get("session"), dict):
            metrics["session"]["unload_required"] = not unloaded
        media_diagnostics["model_unloaded_after_response"] = unloaded
        return io.NodeOutput(
            selected,
            json.dumps(ordered_probabilities, ensure_ascii=False, indent=2),
            json.dumps(metrics, ensure_ascii=False, indent=2),
            media_diagnostics,
            resolved_session,
        )


__all__ = [
    "LlamaCppCreateQuestionFromInputNode",
    "LlamaCppDecideSessionNode",
    "LlamaCppQuestionType",
    "MAX_ANSWERS",
    "make_question_payload",
]
