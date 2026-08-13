from __future__ import annotations

from pathlib import Path

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io


MINIMAX_PROMPT_TYPES = (
    "I2V",
    "FL2V",
    "FL2V_LOOP",
    "T2V",
    "R2V",
    "R2I",
    "R2A",
    "L2V",
)
REFERENCE_PROMPT_TYPES = frozenset({"R2V", "R2I", "R2A"})

PRESETS_DIRECTORY = Path(__file__).resolve().parents[2] / "presets"
BASE_PROMPT_PATH = PRESETS_DIRECTORY / "PROMPT_BASE.md"
REFERENCE_BASE_PROMPT_PATH = PRESETS_DIRECTORY / "PROMPT_REFERENCE_BASE.md"


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read MiniMax prompt preset: {path}") from exc


def load_minimax_system_prompt(prompt_type: str) -> str:
    if prompt_type not in MINIMAX_PROMPT_TYPES:
        raise ValueError(f"Unknown MiniMax prompt type: {prompt_type}")

    base_path = (
        REFERENCE_BASE_PROMPT_PATH
        if prompt_type in REFERENCE_PROMPT_TYPES
        else BASE_PROMPT_PATH
    )
    base_prompt = _read_prompt(base_path).rstrip("\r\n")
    type_prompt = _read_prompt(
        PRESETS_DIRECTORY / f"PROMPT_{prompt_type}.md"
    ).lstrip("\r\n")
    return f"{base_prompt}\n\n{type_prompt}"


class MiniMaxSystemPromptPresetNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_MiniMaxSystemPromptPreset",
            display_name="MiniMax System Prompt Preset",
            category="Ollama/prompt",
            description=(
                "Loads a packaged MiniMax prompt preset. Reference modes use their "
                "reference base; other modes use the common base. The selected base and "
                "mode prompt are joined with one blank line."
            ),
            inputs=[
                io.Combo.Input(
                    "type",
                    options=list(MINIMAX_PROMPT_TYPES),
                    default="I2V",
                    tooltip=(
                        "MiniMax prompting mode used when enum_string is not connected."
                    ),
                ),
                io.String.Input(
                    "enum_string",
                    optional=True,
                    force_input=True,
                    tooltip=(
                        "Optional exact preset name. When connected, this overrides type "
                        "and must be one of: " + ", ".join(MINIMAX_PROMPT_TYPES) + "."
                    ),
                ),
            ],
            outputs=[
                io.String.Output(
                    "system_prompt",
                    display_name="system prompt",
                    tooltip="Connect to a Generate node's system input.",
                ),
            ],
            search_aliases=["MiniMax prompt", "MiniMax system prompt"],
        )

    @classmethod
    def execute(cls, type: str, enum_string: str | None = None) -> io.NodeOutput:
        prompt_type = type if enum_string is None else enum_string
        if prompt_type not in MINIMAX_PROMPT_TYPES:
            expected = ", ".join(MINIMAX_PROMPT_TYPES)
            raise ValueError(
                f"Unknown MiniMax prompt preset {prompt_type!r}. Expected one of: "
                f"{expected}."
            )
        return io.NodeOutput(load_minimax_system_prompt(prompt_type))


__all__ = [
    "MINIMAX_PROMPT_TYPES",
    "REFERENCE_PROMPT_TYPES",
    "MiniMaxSystemPromptPresetNode",
    "load_minimax_system_prompt",
]
