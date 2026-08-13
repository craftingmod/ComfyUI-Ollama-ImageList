from __future__ import annotations

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..core.muse_glimmer import parse_muse_glimmer_response


class MuseGlimmerResponseParserNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_MuseGlimmerResponseParser",
            display_name="Muse Glimmer Response Parser",
            category="Ollama/llama_cpp/utils",
            description=(
                "Splits a non-streaming Muse Glimmer response into final response and "
                "thinking text while preserving other recipients as raw text. Streaming "
                "and tool-call interpretation are not supported."
            ),
            inputs=[
                io.String.Input(
                    "muse_response",
                    default="",
                    multiline=True,
                    dynamic_prompts=False,
                    force_input=True,
                    tooltip="Raw response string produced by Muse Glimmer.",
                ),
            ],
            outputs=[
                io.String.Output("response", display_name="response"),
                io.String.Output("thinking", display_name="thinking"),
                io.String.Output(
                    "raw",
                    display_name="raw",
                    tooltip=(
                        "Unclassified text and complete messages addressed to recipients "
                        "other than self or user."
                    ),
                ),
                io.Boolean.Output(
                    "valid",
                    display_name="valid",
                    tooltip=(
                        "True when a complete Muse Glimmer final-response marker was parsed. "
                        "False for truncated reasoning or non-Muse text."
                    ),
                ),
            ],
        )

    @classmethod
    def execute(cls, muse_response: str) -> io.NodeOutput:
        parsed = parse_muse_glimmer_response(muse_response)
        return io.NodeOutput(
            parsed.response,
            parsed.thinking,
            parsed.raw,
            parsed.valid,
        )


__all__ = ["MuseGlimmerResponseParserNode"]
