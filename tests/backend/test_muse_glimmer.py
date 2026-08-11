from backend.core.muse_glimmer import parse_muse_glimmer_response


def test_parses_reasoning_and_the_last_final_marker():
    raw = (
        " to=self<|message|>First consider an example containing "
        "<|start|>assistant to=user<|message|>draft<|eom|>"
        "<|start|>assistant to=user<|message|>Final answer<|eot|>ignored"
    )

    parsed = parse_muse_glimmer_response(raw)

    assert parsed.response == "Final answer"
    assert parsed.thinking == "First consider an example containing"
    assert parsed.raw == "ignored"
    assert parsed.valid is True


def test_parses_direct_final_with_or_without_eot():
    with_eot = parse_muse_glimmer_response(
        " to=user<|message|>Answer<|eot|>ignored"
    )
    without_eot = parse_muse_glimmer_response(" to=user<|message|>Answer")

    assert with_eot.response == "Answer"
    assert without_eot.response == "Answer"
    assert with_eot.thinking == without_eot.thinking == ""
    assert with_eot.raw == "ignored"
    assert without_eot.raw == ""
    assert with_eot.valid is without_eot.valid is True


def test_truncated_reasoning_is_not_exposed_as_response():
    parsed = parse_muse_glimmer_response(
        " to=self<|message|>We need determine...<|eom|>"
    )

    assert parsed.response == ""
    assert parsed.thinking == "We need determine..."
    assert parsed.raw == ""
    assert parsed.valid is False


def test_non_muse_and_empty_strings_are_preserved_safely():
    plain = parse_muse_glimmer_response("  ordinary <|token|> text  ")
    empty = parse_muse_glimmer_response(None)

    assert plain.response == ""
    assert plain.thinking == ""
    assert plain.raw == "  ordinary <|token|> text  "
    assert plain.valid is False
    assert empty.response == ""
    assert empty.thinking == ""
    assert empty.raw == ""
    assert empty.valid is False


def test_other_recipient_message_is_preserved_in_raw():
    tool_message = (
        "<|start|>assistant to=functions.lookup<|message|>"
        '{"query":"weather"}<|eom|>'
    )
    parsed = parse_muse_glimmer_response(
        " to=self<|message|>Need a lookup.<|eom|>"
        f"{tool_message}"
        "<|start|>assistant to=user<|message|>It is sunny.<|eot|>"
    )

    assert parsed.response == "It is sunny."
    assert parsed.thinking == "Need a lookup."
    assert parsed.raw == tool_message
    assert parsed.valid is True
