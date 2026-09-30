import importlib
import json

import pytest

from backend.core import InputNormalizationError, MediaBundle, MediaItem
from tests.backend.tensor_stub import VideoInputStub, silent_audio, solid_image
from tests.backend.test_extension_registration import (
    import_llama_cpp_decision_nodes,
)


def _load_nodes(monkeypatch):
    nodes = import_llama_cpp_decision_nodes(monkeypatch)

    class FakeSession:
        def __init__(self):
            self.calls = []
            self.close_calls = 0

        def decide(self, **request):
            self.calls.append(request)
            answers = request["answers"]
            return answers[0], {answer: 1 / len(answers) for answer in answers}

        def close(self):
            self.close_calls += 1

    monkeypatch.setattr(nodes, "LlamaCppSession", FakeSession)
    monkeypatch.setattr(nodes, "LlamaCppServerSession", FakeSession)
    return nodes, FakeSession


def _payload(question):
    return {
        "question": question,
        "answer": [f"{question} A", f"{question} B"],
    }


def _media_item(kind, index=0):
    return MediaItem(kind, index, f"{kind}/test", kind.encode(), {})


def test_media_sequential_keeps_video_audio_atomic_and_unloads_once(monkeypatch):
    nodes, fake_session = _load_nodes(monkeypatch)
    compact = importlib.import_module("backend.nodes.llama_cpp_compact")
    embedded_audio = _media_item("audio")
    video_frame = _media_item("video")
    normalize_video_calls = []

    def normalize_video(**values):
        normalize_video_calls.append(values)
        return MediaBundle((embedded_audio, video_frame))

    monkeypatch.setattr(compact, "normalize_media", normalize_video)
    session = fake_session()
    result = nodes.LlamaCppDecideMediaSequentialNode.execute(
        session=[session],
        system=["shared rules"],
        context=["image context", "audio context", "video context"],
        question=[_payload("shared question")],
        images=[solid_image(1, 1, 1, 3, 0.25)],
        audio=[{"waveform": silent_audio(1, 1, 8), "sample_rate": 16_000}],
        video=[VideoInputStub(b"video-with-owned-audio")],
        video_with_audio=[True],
        session_unload=[True],
    )

    assert len(normalize_video_calls) == 1
    assert normalize_video_calls[0]["video_with_audio"] is True
    assert [
        [item.kind for item in request["media"].items] for request in session.calls
    ] == [["image"], ["audio"], ["audio", "video"]]
    assert session.calls[-1]["media"].items == (embedded_audio, video_frame)
    assert [
        request["context"].split("\n\nContext:\n", 1)[1] for request in session.calls
    ] == ["image context", "audio context", "video context"]
    assert [request["question"] for request in session.calls] == ["shared question"] * 3
    assert all("reuse_kv_cache" not in request for request in session.calls)
    assert all("media_before_prompt" not in request for request in session.calls)
    assert result[0] == ["shared question A"] * 3
    assert len(result[1]) == len(result[2]) == len(result[3]) == 3
    assert result[4] is session
    assert session.close_calls == 1
    assert [json.loads(value)["model_unloaded"] for value in result[2]] == [
        False,
        False,
        True,
    ]
    assert [value["model_unloaded_after_response"] for value in result[3]] == [
        False,
        False,
        True,
    ]


def test_media_sequential_broadcasts_context_and_pairs_questions(monkeypatch):
    nodes, fake_session = _load_nodes(monkeypatch)
    session = fake_session()
    result = nodes.LlamaCppDecideMediaSequentialNode.execute(
        session=[session],
        system=["rules"],
        context=["shared context"],
        question=[_payload("first"), _payload("second")],
        images=[
            solid_image(1, 1, 1, 3, 0.25),
            solid_image(1, 1, 1, 3, 0.75),
        ],
    )

    assert [request["context"] for request in session.calls] == [
        "System:\nrules\n\nContext:\nshared context"
    ] * 2
    assert [request["question"] for request in session.calls] == [
        "first",
        "second",
    ]
    assert [len(request["media"].items) for request in session.calls] == [1, 1]
    assert result[0] == ["first A", "second A"]
    assert result[4] is session
    assert session.close_calls == 0


def test_media_sequential_without_media_runs_one_text_decision(monkeypatch):
    nodes, fake_session = _load_nodes(monkeypatch)
    session = fake_session()

    result = nodes.LlamaCppDecideMediaSequentialNode.execute(
        session=[session],
        system=["rules"],
        context=["text context"],
        question=[_payload("text question")],
    )

    assert len(session.calls) == 1
    assert session.calls[0]["media"] == MediaBundle()
    assert result[0] == ["text question A"]
    assert result[4] is session


def test_prompt_sequential_pairs_contexts_and_questions_and_reuses_one_media_bundle(
    monkeypatch,
):
    nodes, fake_session = _load_nodes(monkeypatch)
    normalized = []
    normalize = nodes.normalize_media

    def normalize_once(**values):
        bundle = normalize(**values)
        normalized.append(bundle)
        return bundle

    monkeypatch.setattr(nodes, "normalize_media", normalize_once)
    session = fake_session()
    contexts = ["first context", "second context"]
    questions = [_payload("first question"), _payload("second question")]
    result = nodes.LlamaCppDecidePromptSequentialNode.execute(
        session=[session],
        system=["rules"],
        context=contexts,
        question=questions,
        images=[solid_image(1, 1, 1, 3, 0.5)],
        session_unload=[True],
    )

    assert len(normalized) == 1
    assert len(session.calls) == 2
    assert all(request["media"] is normalized[0] for request in session.calls)
    assert [
        (request["context"].split("\n\nContext:\n", 1)[1], request["question"])
        for request in session.calls
    ] == list(zip(contexts, [item["question"] for item in questions], strict=True))
    assert all(request["reuse_kv_cache"] is True for request in session.calls)
    assert all(request["media_before_prompt"] is True for request in session.calls)
    assert result[0] == ["first question A", "second question A"]
    assert len(result[1]) == len(result[2]) == len(result[3]) == 2
    assert result[4] is session
    assert session.close_calls == 1
    assert [json.loads(value)["model_unloaded"] for value in result[2]] == [
        False,
        True,
    ]


def test_prompt_sequential_allows_cache_off_and_no_media(monkeypatch):
    nodes, fake_session = _load_nodes(monkeypatch)
    session = fake_session()

    result = nodes.LlamaCppDecidePromptSequentialNode.execute(
        session=[session],
        system=["rules"],
        context=["shared context"],
        question=[_payload("first"), _payload("second")],
        reuse_kv_cache=[False],
    )

    assert len(session.calls) == 2
    assert all(request["media"] == MediaBundle() for request in session.calls)
    assert all(request["reuse_kv_cache"] is False for request in session.calls)
    assert all(request["media_before_prompt"] is True for request in session.calls)
    assert [request["context"] for request in session.calls] == [
        "System:\nrules\n\nContext:\nshared context"
    ] * 2
    assert result[0] == ["first A", "second A"]
    assert result[4] is session
    assert session.close_calls == 0


def test_decision_sequential_rejects_malformed_and_mismatched_inputs_before_calls(
    monkeypatch,
):
    nodes, fake_session = _load_nodes(monkeypatch)
    session = fake_session()
    base = {
        "session": [session],
        "system": ["rules"],
        "images": [
            solid_image(1, 1, 1, 3, 0.1),
            solid_image(1, 1, 1, 3, 0.2),
            solid_image(1, 1, 1, 3, 0.3),
        ],
    }

    for context, question in (
        (["one", "two"], [_payload("first")]),
        (["one"], [_payload("first"), _payload("second")]),
        (["one", ["nested"]], [_payload("first")]),
        (["one"], [{"question": "missing answer"}]),
    ):
        with pytest.raises(InputNormalizationError):
            nodes.LlamaCppDecideMediaSequentialNode.execute(
                **base, context=context, question=question
            )
    assert session.calls == []

    for context, question in (
        (
            ["one", "two"],
            [_payload("first"), _payload("second"), _payload("third")],
        ),
        (["one", "two", "three"], [_payload("first"), _payload("second")]),
        (["one"], [{"question": "missing answer"}]),
    ):
        with pytest.raises(InputNormalizationError):
            nodes.LlamaCppDecidePromptSequentialNode.execute(
                **base,
                context=context,
                question=question,
            )
    assert session.calls == []
