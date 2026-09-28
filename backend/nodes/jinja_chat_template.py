from __future__ import annotations

from pathlib import Path

try:
    from comfy_api.v0_0_2 import io
except (
    ImportError
):  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io


PRESETS_DIRECTORY = Path(__file__).resolve().parents[2] / "presets" / "chat_template"


def get_chat_template_presets() -> list[str]:
    if not PRESETS_DIRECTORY.exists():
        return []
    return sorted(
        [
            p.name
            for p in PRESETS_DIRECTORY.iterdir()
            if p.is_file() and p.name.endswith(".jinja")
        ]
    )


def load_chat_template(template_name: str) -> str:
    template_filename = (
        template_name if template_name.endswith(".jinja") else f"{template_name}.jinja"
    )
    resolved_path = (PRESETS_DIRECTORY / template_filename).resolve()

    if (
        not resolved_path.is_file()
        or not resolved_path.name.endswith(".jinja")
        or resolved_path.parent != PRESETS_DIRECTORY.resolve()
    ):
        expected = ", ".join(get_chat_template_presets())
        raise ValueError(
            f"Unknown Jinja chat template preset {template_name!r}. Expected one of: "
            f"{expected}."
        )

    try:
        return resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Could not read Jinja chat template preset: {resolved_path}"
        ) from exc


class JinjaChatTemplatePresetNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        presets = get_chat_template_presets()
        display_presets = [preset.removesuffix(".jinja") for preset in presets]
        default_preset = display_presets[0] if display_presets else ""
        return io.Schema(
            node_id="OllamaImageList_JinjaChatTemplatePreset",
            display_name="Jinja Chat Template Preset",
            category="Ollama/preset",
            description=(
                "Loads a packaged Jinja chat template preset from presets/chat_template."
            ),
            inputs=[
                io.Combo.Input(
                    "template",
                    options=display_presets,
                    default=default_preset,
                    tooltip="Jinja chat template preset to load.",
                ),
            ],
            outputs=[
                io.String.Output(
                    "chat_template",
                    display_name="chat template",
                    tooltip=(
                        "Connect to [llama.cpp] Model Profile's custom_chat_template input."
                    ),
                ),
            ],
            search_aliases=[
                "Jinja chat template",
                "chat template preset",
                "Jinja preset",
            ],
        )

    @classmethod
    def execute(cls, template: str) -> io.NodeOutput:
        return io.NodeOutput(load_chat_template(template))


__all__ = [
    "JinjaChatTemplatePresetNode",
    "get_chat_template_presets",
    "load_chat_template",
]
