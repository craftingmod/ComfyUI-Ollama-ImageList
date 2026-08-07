from __future__ import annotations

import json
import os

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..backends.llama_cpp import HANDLER_NAMES, run_chat
from ..core import (
    InputNormalizationError,
    normalize_media,
    unwrap_optional_scalar,
    unwrap_required_scalar,
)
from .llama_cpp_diagnostics import LlamaCppMediaDiagnosticsType
from .llama_cpp_sampling import LlamaCppSamplingType, normalize_sampling


LLM_FOLDER_NAME = "ollama_image_list_llm"
NO_MODEL_OPTION = "[no GGUF models found]"
NO_MMPROJ_OPTION = "[none]"


def _get_folder_paths():
    try:
        import folder_paths
    except ImportError:
        return None
    return folder_paths


def _register_llm_folder(folder_paths) -> None:
    source_paths: list[str] = []
    for folder_name, (paths, _extensions) in folder_paths.folder_names_and_paths.items():
        if folder_name.casefold() == "llm":
            source_paths.extend(paths)
    source_paths.append(os.path.join(folder_paths.models_dir, "LLM"))

    models_dirs: list[str] = []
    seen: set[str] = set()
    for path in source_paths:
        normalized = os.path.abspath(os.path.normpath(path))
        identity = os.path.normcase(normalized)
        if identity in seen:
            continue
        seen.add(identity)
        models_dirs.append(normalized)

    registered = folder_paths.folder_names_and_paths.get(LLM_FOLDER_NAME)
    if registered != (models_dirs, {".gguf"}):
        folder_paths.folder_names_and_paths[LLM_FOLDER_NAME] = (
            models_dirs,
            {".gguf"},
        )


def _gguf_options() -> tuple[list[str], list[str]]:
    folder_paths = _get_folder_paths()
    if folder_paths is None:
        return [NO_MODEL_OPTION], [NO_MMPROJ_OPTION]

    _register_llm_folder(folder_paths)
    filenames = folder_paths.get_filename_list(LLM_FOLDER_NAME)
    projector_options = sorted(
        filenames,
        key=lambda filename: "mmproj" not in os.path.basename(filename).casefold(),
    )
    return filenames or [NO_MODEL_OPTION], [NO_MMPROJ_OPTION, *projector_options]


def _resolve_gguf_selection(selection: str, *, label: str, required: bool) -> str:
    if selection == NO_MMPROJ_OPTION and not required:
        return ""
    if selection in {NO_MODEL_OPTION, NO_MMPROJ_OPTION, ""}:
        if required:
            raise InputNormalizationError(
                f"No {label} is selected. Place a compatible GGUF file under "
                "ComfyUI/models/LLM and refresh the node list."
            )
        return ""

    folder_paths = _get_folder_paths()
    if folder_paths is None:
        raise InputNormalizationError(
            f"Cannot resolve {label} because ComfyUI folder_paths is unavailable."
        )
    _register_llm_folder(folder_paths)
    try:
        return folder_paths.get_full_path_or_raise(LLM_FOLDER_NAME, selection)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise InputNormalizationError(
            f"Selected {label} was not found under ComfyUI/models/LLM: {selection}"
        ) from exc


def _resolve_sampling_values(
    *,
    temperature,
    top_p,
    top_k,
    min_p,
    repeat_penalty,
    sampling,
) -> dict[str, float | int]:
    values: dict[str, float | int] = {
        "temperature": float(unwrap_optional_scalar("temperature", temperature, 0.2)),
        "top_p": float(unwrap_optional_scalar("top_p", top_p, 0.95)),
        "top_k": int(unwrap_optional_scalar("top_k", top_k, 40)),
        "min_p": float(unwrap_optional_scalar("min_p", min_p, 0.05)),
        "repeat_penalty": float(
            unwrap_optional_scalar("repeat_penalty", repeat_penalty, 1.0)
        ),
    }
    connected = unwrap_optional_scalar("sampling", sampling, None)
    return values if connected is None else normalize_sampling(connected)


class LlamaCppImageListGenerateNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        model_options, mmproj_options = _gguf_options()
        return io.Schema(
            node_id="OllamaImageList_LlamaCppGenerate",
            display_name="Llama.cpp Generate (Multimodal)",
            category="Ollama/Image List",
            description=(
                "Loads one local GGUF model, analyzes optional image, audio, and video inputs in "
                "one llama-cpp-python chat request, then closes and releases the model "
                "immediately. No model cache is retained."
            ),
            is_input_list=True,
            not_idempotent=True,
            inputs=[
                io.Combo.Input(
                    "model_path",
                    options=model_options,
                    default=model_options[0],
                    tooltip=(
                        "Main model GGUF from ComfyUI's registered LLM paths. The list is "
                        "not filtered by filename; choose a compatible main model."
                    ),
                ),
                io.Combo.Input(
                    "mmproj_path",
                    options=mmproj_options,
                    default=NO_MMPROJ_OPTION,
                    tooltip=(
                        "Optional multimodal projector GGUF from the same unfiltered list. "
                        "Choose [none] for text-only requests."
                    ),
                ),
                io.Combo.Input(
                    "handler",
                    options=list(HANDLER_NAMES),
                    default="auto",
                    tooltip=(
                        "auto uses the model metadata and the fork's generic MTMD handler. "
                        "Select a model-specific handler when its template requires one."
                    ),
                ),
                LlamaCppSamplingType.Input(
                    "sampling",
                    optional=True,
                    tooltip=(
                        "Optional output from Llama.cpp Sampling Preset. When connected, "
                        "it overrides temperature, top_p, top_k, min_p, and repeat_penalty."
                    ),
                ),
                io.String.Input(
                    "system",
                    default="",
                    multiline=True,
                    dynamic_prompts=False,
                    tooltip="Optional system message sent without trimming or rewriting.",
                ),
                io.String.Input(
                    "prompt",
                    default="",
                    multiline=True,
                    dynamic_prompts=False,
                    tooltip="User message sent without trimming or rewriting.",
                ),
                io.Int.Input(
                    "n_ctx",
                    default=8192,
                    min=512,
                    max=1_048_576,
                    step=512,
                    tooltip="Context window in tokens, including media tokens and output.",
                ),
                io.Int.Input(
                    "max_tokens",
                    default=512,
                    min=1,
                    max=131_072,
                    step=1,
                    tooltip="Maximum number of generated tokens.",
                ),
                io.Combo.Input(
                    "gpu_layers",
                    options=["all", "auto", "cpu"],
                    default="all",
                    advanced=True,
                    tooltip="Offload all layers, let llama.cpp decide, or use CPU only.",
                ),
                io.Float.Input(
                    "temperature",
                    default=0.2,
                    min=0.0,
                    max=5.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Float.Input(
                    "top_p",
                    default=0.95,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Int.Input(
                    "top_k",
                    default=40,
                    min=0,
                    max=10_000,
                    step=1,
                    advanced=True,
                ),
                io.Float.Input(
                    "min_p",
                    default=0.05,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Float.Input(
                    "repeat_penalty",
                    default=1.0,
                    min=0.0,
                    max=5.0,
                    step=0.01,
                    advanced=True,
                ),
                io.Int.Input(
                    "seed",
                    default=-1,
                    min=-1,
                    max=0xFFFFFFFF,
                    step=1,
                    tooltip="-1 uses llama.cpp's random seed behavior.",
                ),
                io.String.Input(
                    "stop",
                    default="",
                    advanced=True,
                    tooltip="Optional single stop string.",
                ),
                io.Int.Input(
                    "n_batch",
                    default=512,
                    min=1,
                    max=65_536,
                    step=1,
                    advanced=True,
                ),
                io.Int.Input(
                    "main_gpu",
                    default=0,
                    min=0,
                    max=31,
                    step=1,
                    advanced=True,
                ),
                io.Int.Input(
                    "n_threads",
                    default=0,
                    min=0,
                    max=1024,
                    step=1,
                    advanced=True,
                    tooltip="0 lets llama-cpp-python choose the CPU thread count.",
                ),
                io.Combo.Input(
                    "flash_attention",
                    options=["auto", "enabled", "disabled"],
                    default="auto",
                    advanced=True,
                ),
                io.Boolean.Input(
                    "use_mmap",
                    default=True,
                    advanced=True,
                    tooltip="Memory-map the GGUF while loaded; the mapping is closed after the response.",
                ),
                io.Boolean.Input(
                    "verbose",
                    default=False,
                    advanced=True,
                    tooltip=(
                        "Print llama.cpp model, timing, and multimodal chat-handler "
                        "diagnostics to the ComfyUI console."
                    ),
                ),
                io.Image.Input(
                    "images",
                    optional=True,
                    tooltip="IMAGE single, batch, list, nested list, or ComfyUI data list.",
                ),
                io.Audio.Input(
                    "audio",
                    optional=True,
                    tooltip=(
                        "Optional ComfyUI AUDIO single, batch, list, or nested list. Audio "
                        "is encoded as lossless PCM16 WAV and requires an audio-capable mmproj."
                    ),
                ),
                io.Video.Input(
                    "video",
                    optional=True,
                    tooltip=(
                        "Optional ComfyUI VIDEO input. The original encoded stream is passed to "
                        "llama.cpp for FFmpeg frame extraction and requires a video-capable build "
                        "and mmproj. Embedded audio is not ingested; connect AUDIO separately."
                    ),
                ),
            ],
            outputs=[
                io.String.Output("response", display_name="response"),
                io.String.Output("thinking", display_name="thinking"),
                io.String.Output("raw_json", display_name="raw JSON"),
                io.String.Output("metrics_json", display_name="metrics"),
                LlamaCppMediaDiagnosticsType.Output(
                    "media_diagnostics",
                    display_name="media diagnostics",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        model_path,
        mmproj_path,
        handler,
        system,
        prompt,
        n_ctx,
        max_tokens,
        gpu_layers,
        temperature,
        top_p,
        top_k,
        min_p,
        repeat_penalty,
        seed,
        stop,
        n_batch,
        main_gpu,
        n_threads,
        flash_attention,
        use_mmap,
        verbose,
        images=None,
        audio=None,
        video=None,
        sampling=None,
    ) -> io.NodeOutput:
        bundle = normalize_media(images=images, audio=audio, video=video)
        model_selection = str(unwrap_required_scalar("model_path", model_path))
        mmproj_selection = str(unwrap_optional_scalar("mmproj_path", mmproj_path, NO_MMPROJ_OPTION))
        sampling_values = _resolve_sampling_values(
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            repeat_penalty=repeat_penalty,
            sampling=sampling,
        )
        result = run_chat(
            model_path=_resolve_gguf_selection(
                model_selection,
                label="model GGUF",
                required=True,
            ),
            mmproj_path=_resolve_gguf_selection(
                mmproj_selection,
                label="mmproj GGUF",
                required=False,
            ),
            handler=str(unwrap_optional_scalar("handler", handler, "auto")),
            system=str(unwrap_required_scalar("system", system)),
            prompt=str(unwrap_required_scalar("prompt", prompt)),
            media=bundle,
            n_ctx=int(unwrap_optional_scalar("n_ctx", n_ctx, 8192)),
            n_batch=int(unwrap_optional_scalar("n_batch", n_batch, 512)),
            gpu_layers=str(unwrap_optional_scalar("gpu_layers", gpu_layers, "all")),
            main_gpu=int(unwrap_optional_scalar("main_gpu", main_gpu, 0)),
            n_threads=int(unwrap_optional_scalar("n_threads", n_threads, 0)),
            flash_attention=str(
                unwrap_optional_scalar("flash_attention", flash_attention, "auto")
            ),
            use_mmap=bool(unwrap_optional_scalar("use_mmap", use_mmap, True)),
            max_tokens=int(unwrap_optional_scalar("max_tokens", max_tokens, 512)),
            temperature=float(sampling_values["temperature"]),
            top_p=float(sampling_values["top_p"]),
            top_k=int(sampling_values["top_k"]),
            min_p=float(sampling_values["min_p"]),
            repeat_penalty=float(sampling_values["repeat_penalty"]),
            seed=int(unwrap_optional_scalar("seed", seed, -1)),
            stop=str(unwrap_optional_scalar("stop", stop, "")),
            verbose=bool(unwrap_optional_scalar("verbose", verbose, False)),
        )
        return io.NodeOutput(
            result.response,
            result.thinking,
            json.dumps(result.raw, ensure_ascii=False, indent=2),
            json.dumps(result.metrics, ensure_ascii=False, indent=2),
            result.media_diagnostics,
        )


__all__ = ["LlamaCppImageListGenerateNode"]
