from __future__ import annotations

import json

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..core import build_ollama_options

OptionsDictType = io.Custom("DICT")
_MAX_INT = 2_147_483_647


def _use_option(option_name: str) -> io.Boolean.Input:
    return io.Boolean.Input(
        f"use_{option_name}",
        display_name=f"use {option_name}",
        default=False,
        label_on="Include",
        label_off="Ignore",
        tooltip=f"Include {option_name} in the generated Ollama options object.",
    )


class OllamaImageListOptionsNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_Options",
            display_name="Ollama Image List Options",
            category="Ollama/Image List",
            description=(
                "Builds an Ollama options dictionary and JSON string from individually enabled "
                "runtime parameters. Disabled parameters are omitted."
            ),
            inputs=[
                _use_option("num_ctx"),
                io.Int.Input(
                    "num_ctx",
                    default=2048,
                    min=1,
                    max=_MAX_INT,
                    step=1,
                    tooltip="Context window size in tokens. Ollama documented default: 2048.",
                ),
                _use_option("num_predict"),
                io.Int.Input(
                    "num_predict",
                    default=-1,
                    min=-1,
                    max=_MAX_INT,
                    step=1,
                    tooltip="Maximum generated tokens. -1 means unlimited generation.",
                ),
                _use_option("temperature"),
                io.Float.Input(
                    "temperature",
                    default=0.8,
                    min=0.0,
                    max=10.0,
                    step=0.01,
                    round=0.001,
                    tooltip="Sampling temperature. Ollama documented default: 0.8.",
                ),
                _use_option("top_p"),
                io.Float.Input(
                    "top_p",
                    default=0.9,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    round=0.001,
                    tooltip="Nucleus sampling probability. Ollama documented default: 0.9.",
                ),
                _use_option("top_k"),
                io.Int.Input(
                    "top_k",
                    default=40,
                    min=0,
                    max=_MAX_INT,
                    step=1,
                    tooltip="Number of highest-probability tokens considered during sampling.",
                ),
                _use_option("min_p"),
                io.Float.Input(
                    "min_p",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    round=0.001,
                    tooltip="Minimum token probability relative to the most likely token.",
                ),
                _use_option("repeat_penalty"),
                io.Float.Input(
                    "repeat_penalty",
                    default=1.1,
                    min=0.0,
                    max=10.0,
                    step=0.01,
                    round=0.001,
                    tooltip="Penalty applied to repeated tokens. Ollama documented default: 1.1.",
                ),
                _use_option("repeat_last_n"),
                io.Int.Input(
                    "repeat_last_n",
                    default=64,
                    min=-1,
                    max=_MAX_INT,
                    step=1,
                    tooltip="Lookback for repetition penalties. 0 disables; -1 uses num_ctx.",
                ),
                _use_option("seed"),
                io.Int.Input(
                    "seed",
                    default=0,
                    min=0,
                    max=_MAX_INT,
                    step=1,
                    tooltip="Random seed. A fixed value makes identical prompts reproducible.",
                ),
                _use_option("stop"),
                io.String.Input(
                    "stop",
                    default="",
                    dynamic_prompts=False,
                    tooltip=(
                        "Single stop sequence. The JSON output converts this string to the "
                        "array required by the Ollama API."
                    ),
                ),
                _use_option("draft_num_predict"),
                io.Int.Input(
                    "draft_num_predict",
                    default=4,
                    min=0,
                    max=_MAX_INT,
                    step=1,
                    tooltip=(
                        "Maximum speculative draft tokens per step. 0 disables speculative "
                        "drafting."
                    ),
                ),
            ],
            outputs=[
                OptionsDictType.Output("options", display_name="options"),
                io.String.Output("options_json", display_name="options_json"),
            ],
        )

    @classmethod
    def execute(
        cls,
        use_num_ctx: bool,
        num_ctx: int,
        use_num_predict: bool,
        num_predict: int,
        use_temperature: bool,
        temperature: float,
        use_top_p: bool,
        top_p: float,
        use_top_k: bool,
        top_k: int,
        use_min_p: bool,
        min_p: float,
        use_repeat_penalty: bool,
        repeat_penalty: float,
        use_repeat_last_n: bool,
        repeat_last_n: int,
        use_seed: bool,
        seed: int,
        use_stop: bool,
        stop: str,
        use_draft_num_predict: bool,
        draft_num_predict: int,
    ) -> io.NodeOutput:
        options = build_ollama_options(locals())
        options_json = json.dumps(options, ensure_ascii=False, indent=2)
        return io.NodeOutput(options, options_json)


__all__ = ["OllamaImageListOptionsNode", "OptionsDictType"]
