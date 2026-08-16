from __future__ import annotations

import re
from dataclasses import dataclass

MUSE_EOM = "<|eom|>"
MUSE_EOT = "<|eot|>"
MUSE_MESSAGE_START = re.compile(
    r"(?:<\|start\|>assistant)? to=(?P<recipient>[^<\s]+)<\|message\|>"
)


@dataclass(frozen=True)
class MuseGlimmerParsedResponse:
    response: str
    thinking: str
    raw: str
    valid: bool


def _split_terminated_message(body: str, terminator: str) -> tuple[str, str]:
    content, found, remainder = body.partition(terminator)
    return content.strip(), remainder if found else ""


def parse_muse_glimmer_response(raw: str | None) -> MuseGlimmerParsedResponse:
    """Split one non-streaming Muse Glimmer completion into public and private text."""
    raw = raw or ""
    matches = list(MUSE_MESSAGE_START.finditer(raw))
    if not matches:
        return MuseGlimmerParsedResponse("", "", raw, False)

    thinking_parts: list[str] = []
    raw_parts: list[str] = []
    response = ""
    found_user = False

    if matches[0].start() > 0:
        raw_parts.append(raw[: matches[0].start()])

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        segment = raw[match.start() : end]
        body = raw[match.end() : end]
        recipient = match.group("recipient")

        if recipient == "self":
            thinking, remainder = _split_terminated_message(body, MUSE_EOM)
            thinking_parts.append(thinking)
            if remainder:
                raw_parts.append(remainder)
        elif recipient == "user":
            response, remainder = _split_terminated_message(body, MUSE_EOT)
            found_user = True
            if remainder:
                raw_parts.append(remainder)
        else:
            raw_parts.append(segment)

    return MuseGlimmerParsedResponse(
        response=response,
        thinking="\n".join(part for part in thinking_parts if part),
        raw="".join(raw_parts),
        valid=found_user,
    )


__all__ = ["MuseGlimmerParsedResponse", "parse_muse_glimmer_response"]
