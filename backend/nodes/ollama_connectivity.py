from __future__ import annotations

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io


class OllamaImageListConnectivityNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OllamaImageList_Connectivity",
            display_name="Ollama Image List Connectivity",
            category="Ollama/Image List",
            description=(
                "Fetches the models available from an Ollama server and outputs the selected "
                "server URL and model name."
            ),
            inputs=[
                io.String.Input(
                    "url",
                    default="http://127.0.0.1:11434",
                    tooltip="Ollama base URL. Only HTTP and HTTPS are accepted.",
                ),
                io.Combo.Input(
                    "available_models",
                    options=[],
                    default="",
                    tooltip="Models reported by the configured Ollama server.",
                ),
                io.String.Input(
                    "model",
                    default="",
                    tooltip=(
                        "Model name output. Selecting available_models copies its value here; "
                        "a model name can also be entered manually."
                    ),
                ),
            ],
            outputs=[
                io.String.Output("url", display_name="URL"),
                io.String.Output("model", display_name="model"),
            ],
        )

    @classmethod
    def validate_inputs(cls, available_models: str) -> bool:
        # The frontend fills this COMBO dynamically, so any serialized string is valid.
        return True

    @classmethod
    def execute(cls, url: str, available_models: str, model: str) -> io.NodeOutput:
        return io.NodeOutput(str(url), str(model))


__all__ = ["OllamaImageListConnectivityNode"]
