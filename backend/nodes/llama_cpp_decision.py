from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI builds
    from comfy_api.latest import io

from ..backends.llama_cpp import LlamaCppSession
from ..core import InputNormalizationError, unwrap_required_scalar
from .llama_cpp_compact import BASE_CATEGORY
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
        raise InputNormalizationError(
            "answer must be one flat ComfyUI STRING list."
        )
    return make_question_payload(question[0], answers)


class LlamaCppCreateQuestionNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppCreateQuestion",
            display_name="[llama.cpp] Create Question",
            category=f"{BASE_CATEGORY}/decision",
            description=(
                "Builds a decision question with 2–26 answers. Hidden answers remain saved "
                "when inputcount is reduced and return when it is increased."
            ),
            is_experimental=True,
            inputs=[
                io.String.Input(
                    "question", default="", multiline=True, dynamic_prompts=False
                ),
                io.Int.Input("inputcount", default=2, min=2, max=MAX_ANSWERS, step=1),
                *[
                    io.String.Input(
                        f"answer_{index}",
                        default="",
                        optional=True,
                        dynamic_prompts=False,
                    )
                    for index in range(1, MAX_ANSWERS + 1)
                ],
            ],
            outputs=[LlamaCppQuestionType.Output("question")],
        )

    @classmethod
    def execute(cls, question: Any, inputcount: Any, **answers: Any) -> io.NodeOutput:
        resolved_count = unwrap_required_scalar("inputcount", inputcount)
        if type(resolved_count) is not int or not 2 <= resolved_count <= MAX_ANSWERS:
            raise InputNormalizationError("inputcount must be an integer from 2 to 26.")
        values = [
            answers.get(f"answer_{index}", "")
            for index in range(1, resolved_count + 1)
        ]
        return io.NodeOutput(make_question_payload(question, values))


class LlamaCppCreateQuestionFromInputNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_LlamaCppCreateQuestionFromInput",
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
            node_id="OllamaImageList_LlamaCppDecideSession",
            display_name="[llama.cpp] Decide (Session)",
            category=f"{BASE_CATEGORY}/decision",
            description=(
                "Scores letter-token choices with a retained Native Session prefill. "
                "Runtime and Connect Sessions do not expose prefill logits."
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
            ],
            outputs=[
                io.String.Output("selected"),
                io.String.Output("probabilities_json", display_name="probabilities JSON"),
                LlamaCppSessionType.Output("session", display_name="session"),
            ],
        )

    @classmethod
    def execute(
        cls, session: Any, system: Any, context: Any, question: Any
    ) -> io.NodeOutput:
        resolved_session = unwrap_required_scalar("session", session)
        if not isinstance(resolved_session, LlamaCppSession):
            raise InputNormalizationError(
                "Decide (Session) requires [llama.cpp] Create Native Session; "
                "Runtime and Connect Sessions do not expose prefill logits."
            )
        payload = unwrap_required_scalar("question", question)
        if not isinstance(payload, Mapping) or set(payload) != {"question", "answer"}:
            raise InputNormalizationError(
                "question must come from a [llama.cpp] Create Question node."
            )
        validated = make_question_payload(payload["question"], payload["answer"])
        resolved_system = unwrap_required_scalar("system", system)
        resolved_context = unwrap_required_scalar("context", context)
        if not isinstance(resolved_system, str) or not isinstance(resolved_context, str):
            raise InputNormalizationError("system and context must be strings.")
        context_parts = [
            f"System:\n{resolved_system}" if resolved_system else "",
            f"Context:\n{resolved_context}" if resolved_context else "",
        ]
        decision_context = "\n\n".join(part for part in context_parts if part)
        selected, probabilities = resolved_session.decide(
            question=validated["question"],
            context=decision_context,
            answers=validated["answer"],
        )
        ordered_probabilities = {
            answer: probabilities[answer] for answer in validated["answer"]
        }
        return io.NodeOutput(
            selected,
            json.dumps(ordered_probabilities, ensure_ascii=False, indent=2),
            resolved_session,
        )


__all__ = [
    "LlamaCppCreateQuestionNode",
    "LlamaCppCreateQuestionFromInputNode",
    "LlamaCppDecideSessionNode",
    "LlamaCppQuestionType",
    "MAX_ANSWERS",
    "make_question_payload",
]
