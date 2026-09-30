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
    _sequential_media_bundles,
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


def _validated_question_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {"question", "answer"}:
        raise InputNormalizationError(
            "question must come from a [llama.cpp] Create Question From Input node."
        )
    return make_question_payload(payload["question"], payload["answer"])


def _decision_inputs(*, include_reuse_kv_cache: bool = False) -> list[Any]:
    inputs = [
        LlamaCppSessionType.Input("session"),
        io.String.Input("system", default="", multiline=True, dynamic_prompts=False),
        io.String.Input("context", default="", multiline=True, dynamic_prompts=False),
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
            tooltip="Runtime completion seed; Native prefill scoring is deterministic.",
        ),
        LlamaCppModelProfileType.Input(
            "model_profile",
            optional=True,
            tooltip=(
                "Optional override; server sessions apply sampling and explicit "
                "on/off reasoning settings per request."
            ),
        ),
    ]
    if include_reuse_kv_cache:
        inputs.append(
            io.Boolean.Input(
                "reuse_kv_cache",
                default=True,
                tooltip="Attempt common-prefix KV reuse across independent decisions.",
            )
        )
    inputs.append(
        io.Boolean.Input(
            "session_unload",
            default=False,
            label_on="Unload",
            label_off="Keep",
            tooltip=(
                "Unload the session after the decision sequence completes."
                if include_reuse_kv_cache
                else "Unload the session after the decision completes."
            ),
        )
    )
    return inputs


def _decision_outputs(*, is_output_list: bool = False) -> list[Any]:
    return [
        io.String.Output("selected", is_output_list=is_output_list),
        io.String.Output(
            "probabilities_json",
            display_name="probabilities_json",
            is_output_list=is_output_list,
        ),
        io.String.Output(
            "metrics_json", display_name="metrics", is_output_list=is_output_list
        ),
        LlamaCppMediaDiagnosticsType.Output(
            "media_diagnostics",
            display_name="media_diagnostics",
            is_output_list=is_output_list,
        ),
        LlamaCppSessionType.Output("session", display_name="session"),
    ]


def _flat_contexts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    if not values:
        raise InputNormalizationError("context must contain at least one string.")
    if any(not isinstance(item, str) for item in values):
        raise InputNormalizationError("context must be a flat list of strings.")
    return list(values)


def _flat_question_payloads(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, (list, tuple)) else [value]
    if not values:
        raise InputNormalizationError("question must contain at least one payload.")
    return [_validated_question_payload(item) for item in values]


def _broadcast_values(values: list[Any], count: int, name: str) -> list[Any]:
    if len(values) == 1:
        return values * count
    if len(values) == count:
        return values
    raise InputNormalizationError(
        f"{name} must contain one value or exactly {count} values."
    )


def _decision_context(system: str, context: str) -> str:
    context_parts = [
        f"System:\n{system}" if system else "",
        f"Context:\n{context}" if context else "",
    ]
    return "\n\n".join(part for part in context_parts if part)


def _run_decision(
    session: Any,
    payload: dict[str, Any],
    context: str,
    media: Any,
    seed: int,
    profile: Any,
    *,
    reuse_kv_cache: bool | None = None,
    media_before_prompt: bool | None = None,
) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = {
        "question": payload["question"],
        "context": context,
        "answers": payload["answer"],
        "media": media,
    }
    if isinstance(session, LlamaCppServerSession) and seed >= 0:
        request["seed"] = seed
    if profile is not None:
        request["model_profile"] = profile
    if reuse_kv_cache is not None:
        request["reuse_kv_cache"] = reuse_kv_cache
    if media_before_prompt is not None:
        request["media_before_prompt"] = media_before_prompt

    started = perf_counter()
    decision = session.decide(**request)
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
            "evaluated": {"image_count": 0, "audio_count": 0, "video_count": 0},
            "mtmd": {
                "completion_succeeded": True,
                "all_media_evaluated": not media.items,
                "verification": "no_media" if not media.items else "unverified",
            },
            "model_unloaded_after_response": False,
        }
    ordered_probabilities = {
        answer: probabilities[answer] for answer in payload["answer"]
    }
    return selected, ordered_probabilities, metrics, media_diagnostics


def _decision_output_values(
    result: tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]],
    seed: int,
    *,
    unloaded: bool,
) -> tuple[Any, str, str, dict[str, Any]]:
    selected, probabilities, metrics, media_diagnostics = result
    metrics.update(operation="decide", seed=seed, model_unloaded=unloaded)
    if isinstance(metrics.get("session"), dict):
        metrics["session"]["unload_required"] = not unloaded
    media_diagnostics["model_unloaded_after_response"] = unloaded
    return (
        selected,
        json.dumps(probabilities, ensure_ascii=False, indent=2),
        json.dumps(metrics, ensure_ascii=False, indent=2),
        media_diagnostics,
    )


def _decision_common_values(
    system: Any, seed: Any, model_profile: Any, session_unload: Any
) -> tuple[str, int, Any, bool]:
    resolved_system = unwrap_required_scalar("system", system)
    if not isinstance(resolved_system, str):
        raise InputNormalizationError("system must be a string.")
    resolved_seed = int(unwrap_required_scalar("seed", seed))
    if resolved_seed < -1 or resolved_seed > 0xFFFFFFFF:
        raise InputNormalizationError("seed must be between -1 and 4294967295.")
    profile_value = unwrap_optional_scalar("model_profile", model_profile, None)
    profile = (
        normalize_compact_model_profile(profile_value)
        if profile_value is not None
        else None
    )
    unload = bool(unwrap_required_scalar("session_unload", session_unload))
    return resolved_system, resolved_seed, profile, unload


def _sequential_decision_output(
    session: Any,
    results: list[tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]],
    seed: int,
    *,
    unload: bool,
) -> io.NodeOutput:
    if unload:
        session.close()
    output_values = [
        _decision_output_values(
            result, seed, unloaded=unload and index == len(results) - 1
        )
        for index, result in enumerate(results)
    ]
    return io.NodeOutput(
        [values[0] for values in output_values],
        [values[1] for values in output_values],
        [values[2] for values in output_values],
        [values[3] for values in output_values],
        session,
    )


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
            inputs=_decision_inputs(),
            outputs=_decision_outputs(),
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
        if not isinstance(resolved_session, (LlamaCppSession, LlamaCppServerSession)):
            raise InputNormalizationError(
                "Decide requires [llama.cpp] Create Native Session or "
                "a llama.cpp server session."
            )
        validated = _validated_question_payload(
            unwrap_required_scalar("question", question)
        )
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
        decision_context = _decision_context(resolved_system, resolved_context)
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
        resolved_seed = int(unwrap_required_scalar("seed", seed))
        if resolved_seed < -1 or resolved_seed > 0xFFFFFFFF:
            raise InputNormalizationError("seed must be between -1 and 4294967295.")
        result = _run_decision(
            resolved_session,
            validated,
            decision_context,
            media,
            resolved_seed,
            profile,
        )
        unloaded = bool(unwrap_required_scalar("session_unload", session_unload))
        if unloaded:
            resolved_session.close()
        return io.NodeOutput(
            *_decision_output_values(result, resolved_seed, unloaded=unloaded),
            resolved_session,
        )


class LlamaCppDecideMediaSequentialNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LlamaCppMtmd_DecideMediaSequential",
            display_name="[llama.cpp] Decide (Media Sequential)",
            category=f"{BASE_CATEGORY}/decision",
            description=(
                "Runs one decision per atomic IMAGE, AUDIO, or VIDEO bundle in modality "
                "order. A single context or question is shared, or provide one per item."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=_decision_inputs(),
            outputs=_decision_outputs(is_output_list=True),
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
        if not isinstance(resolved_session, (LlamaCppSession, LlamaCppServerSession)):
            raise InputNormalizationError(
                "Decide requires [llama.cpp] Create Native Session or "
                "a llama.cpp server session."
            )
        contexts = _flat_contexts(context)
        questions = _flat_question_payloads(question)
        resolved_system, resolved_seed, profile, unload = _decision_common_values(
            system, seed, model_profile, session_unload
        )
        bundles = _sequential_media_bundles(
            images=images,
            audio=audio,
            video=video,
            video_with_audio=bool(
                unwrap_required_scalar("video_with_audio", video_with_audio)
            ),
        )
        contexts = _broadcast_values(contexts, len(bundles), "context")
        questions = _broadcast_values(questions, len(bundles), "question")
        results = [
            _run_decision(
                resolved_session,
                payload,
                _decision_context(resolved_system, item_context),
                bundle,
                resolved_seed,
                profile,
            )
            for bundle, item_context, payload in zip(
                bundles, contexts, questions, strict=True
            )
        ]
        return _sequential_decision_output(
            resolved_session,
            results,
            resolved_seed,
            unload=unload,
        )


class LlamaCppDecidePromptSequentialNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LlamaCppMtmd_DecidePromptSequential",
            display_name="[llama.cpp] Decide (Prompt Sequential)",
            category=f"{BASE_CATEGORY}/decision",
            description=(
                "Runs paired context and question lists independently against the same "
                "complete media bundle. Common-prefix KV reuse is attempted by default."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_experimental=True,
            inputs=_decision_inputs(include_reuse_kv_cache=True),
            outputs=_decision_outputs(is_output_list=True),
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
        reuse_kv_cache: Any = True,
        session_unload: Any = False,
    ) -> io.NodeOutput:
        resolved_session = unwrap_required_scalar("session", session)
        if not isinstance(resolved_session, (LlamaCppSession, LlamaCppServerSession)):
            raise InputNormalizationError(
                "Decide requires [llama.cpp] Create Native Session or "
                "a llama.cpp server session."
            )
        contexts = _flat_contexts(context)
        questions = _flat_question_payloads(question)
        count = max(len(contexts), len(questions))
        contexts = _broadcast_values(contexts, count, "context")
        questions = _broadcast_values(questions, count, "question")
        resolved_system, resolved_seed, profile, unload = _decision_common_values(
            system, seed, model_profile, session_unload
        )
        reuse_value = unwrap_required_scalar("reuse_kv_cache", reuse_kv_cache)
        if not isinstance(reuse_value, bool):
            raise InputNormalizationError("reuse_kv_cache must be a boolean.")
        video_audio = bool(unwrap_required_scalar("video_with_audio", video_with_audio))
        media = normalize_media(
            images=images,
            audio=audio,
            video=video,
            video_with_audio=video_audio,
            audio_sample_rate=16_000,
            audio_channels=1,
        )
        results = [
            _run_decision(
                resolved_session,
                payload,
                _decision_context(resolved_system, item_context),
                media,
                resolved_seed,
                profile,
                reuse_kv_cache=reuse_value,
                media_before_prompt=True,
            )
            for item_context, payload in zip(contexts, questions, strict=True)
        ]
        return _sequential_decision_output(
            resolved_session,
            results,
            resolved_seed,
            unload=unload,
        )


__all__ = [
    "LlamaCppCreateQuestionFromInputNode",
    "LlamaCppDecideMediaSequentialNode",
    "LlamaCppDecidePromptSequentialNode",
    "LlamaCppDecideSessionNode",
    "LlamaCppQuestionType",
    "MAX_ANSWERS",
    "make_question_payload",
]
