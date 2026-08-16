from __future__ import annotations

import json
import os

try:
    from comfy_api.v0_0_2 import io
except ImportError:  # pragma: no cover - compatibility with newer ComfyUI development builds
    from comfy_api.latest import io

from ..backends.llama_cpp import HANDLER_NAMES, REASONING_STRENGTHS, run_chat
from ..core import (
    InputNormalizationError,
    normalize_media,
    unwrap_optional_scalar,
    unwrap_required_scalar,
)
from .llama_cpp_diagnostics import LlamaCppMediaDiagnosticsType
from .llama_cpp_ngram_speculative import LlamaCppNGramSpeculativeType
from .llama_cpp_runtime import LlamaCppGemma4RuntimeType, normalize_gemma4_runtime
from .llama_cpp_sampling import LlamaCppSamplingType, normalize_sampling

LLM_FOLDER_NAME = "ollama_image_list_llm"
NO_MODEL_OPTION = "[no GGUF models found]"
NO_MMPROJ_OPTION = "[none]"
NO_DRAFT_OPTION = "[none]"


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
    if selection in {NO_MODEL_OPTION, NO_MMPROJ_OPTION, NO_DRAFT_OPTION, ""}:
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


def _resolve_runtime_values(
    *,
    n_batch,
    override_n_ubatch,
    n_ubatch,
    override_image_max_tokens,
    image_max_tokens,
    runtime,
) -> dict[str, bool | int]:
    values: dict[str, bool | int] = {
        "n_batch": int(unwrap_optional_scalar("n_batch", n_batch, 512)),
        "override_n_ubatch": bool(
            unwrap_optional_scalar("override_n_ubatch", override_n_ubatch, False)
        ),
        "n_ubatch": int(unwrap_optional_scalar("n_ubatch", n_ubatch, 512)),
        "override_image_max_tokens": bool(
            unwrap_optional_scalar(
                "override_image_max_tokens", override_image_max_tokens, False
            )
        ),
        "image_max_tokens": int(
            unwrap_optional_scalar("image_max_tokens", image_max_tokens, 1120)
        ),
    }
    connected = unwrap_optional_scalar("runtime", runtime, None)
    return values if connected is None else normalize_gemma4_runtime(connected)


class LlamaCppImageListGenerateNode(io.ComfyNode):
    _supports_ngram_speculative = True

    @classmethod
    def _prepare_backend_execution(cls) -> dict[str, object]:
        return {}

    @classmethod
    def define_schema(cls) -> io.Schema:
        model_options, mmproj_options = _gguf_options()
        return io.Schema(
            node_id="OllamaImageList_LlamaCppGenerate",
            display_name="Llama.cpp Generate (Multimodal)",
            category="Ollama/llama_cpp/legacy",
            description=(
                "Loads one local GGUF model, analyzes optional image, audio, and video inputs in "
                "one llama-cpp-python chat request, then closes and releases the model "
                "immediately. No model cache is retained."
            ),
            is_input_list=True,
            not_idempotent=True,
            is_dev_only=True,
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
                io.Boolean.Input(
                    "thinking",
                    default=False,
                    label_on="Enabled",
                    label_off="Disabled",
                    tooltip=(
                        "Explicitly request thinking through the selected handler's template "
                        "control. Gemma 4 uses enable_thinking and Qwen 3 VL uses "
                        "force_reasoning. A checkpoint that does not support switching may "
                        "ignore this value."
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
                LlamaCppGemma4RuntimeType.Input(
                    "runtime",
                    optional=True,
                    tooltip=(
                        "Optional output from Llama.cpp Gemma 4 Runtime Preset. When connected, "
                        "it overrides the Advanced n_batch, n_ubatch, image_max_tokens, and "
                        "both override switches. Connect the preset's separate n_ctx and "
                        "max_tokens outputs to apply those visible values."
                    ),
                ),
                LlamaCppNGramSpeculativeType.Input(
                    "ngram_speculative",
                    optional=True,
                    tooltip=(
                        "Optional output from Llama.cpp N-gram Speculative Preset. This "
                        "model-free mode uses repeated context patterns and no draft GGUF. "
                        "It is separate from Experimental native DFlash/DSpark decoding."
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
                    tooltip=(
                        "Logical prompt batch size. When image_max_tokens is overridden, this "
                        "must be at least that value."
                    ),
                ),
                io.Boolean.Input(
                    "override_n_ubatch",
                    default=False,
                    label_on="Override",
                    label_off="Use backend default",
                    advanced=True,
                    tooltip=(
                        "Pass n_ubatch explicitly. Leave disabled to use llama-cpp-python's "
                        "default."
                    ),
                ),
                io.Int.Input(
                    "n_ubatch",
                    default=512,
                    min=1,
                    max=65_536,
                    step=1,
                    advanced=True,
                    tooltip=(
                        "Physical batch size used only when override_n_ubatch is enabled. "
                        "Gemma 4 vision requires it to cover the selected image token chunk."
                    ),
                ),
                io.Boolean.Input(
                    "override_image_max_tokens",
                    default=False,
                    label_on="Override",
                    label_off="Use mmproj default",
                    advanced=True,
                    tooltip=(
                        "Pass an explicit dynamic-resolution image token ceiling to the MTMD "
                        "handler. Leave disabled to read the projector's default."
                    ),
                ),
                io.Int.Input(
                    "image_max_tokens",
                    default=1120,
                    min=1,
                    max=65_536,
                    step=1,
                    advanced=True,
                    tooltip=(
                        "Per-image or per-video-frame token ceiling used only when its "
                        "override is enabled. n_batch and effective n_ubatch must be at least "
                        "this value."
                    ),
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
                        "llama.cpp's native libmtmd video helper and requires a wheel built with "
                        "MTMD_VIDEO support plus a compatible mmproj. Embedded audio is not "
                        "ingested; connect AUDIO separately."
                    ),
                ),
                io.Combo.Input(
                    "reasoning_strength",
                    options=list(REASONING_STRENGTHS),
                    default="auto",
                    advanced=True,
                    tooltip=(
                        "Optional reasoning effort hint for templates such as "
                        "Muse-Glimmer. auto omits the hint so the model template uses "
                        "its own default. Ignored when thinking is disabled."
                    ),
                ),
                io.Int.Input(
                    "reasoning_budget",
                    default=0,
                    min=0,
                    max=65536,
                    step=1,
                    advanced=True,
                    tooltip=(
                        "Maximum reasoning tokens for supported Qwen/Gemma reasoning "
                        "formats. 0 applies no budget. Ignored when thinking is disabled."
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
        thinking,
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
        override_n_ubatch,
        n_ubatch,
        override_image_max_tokens,
        image_max_tokens,
        main_gpu,
        n_threads,
        flash_attention,
        use_mmap,
        verbose,
        images=None,
        audio=None,
        video=None,
        sampling=None,
        runtime=None,
        ngram_speculative=None,
        draft_model=None,
        spec_type=None,
        spec_n_max=None,
        spec_n_min=None,
        spec_p_min=None,
        mtp_provider="off",
        reasoning_strength="auto",
        reasoning_budget=0,
    ) -> io.NodeOutput:
        resolved_spec_type = str(
            unwrap_optional_scalar("spec_type", spec_type, "none")
        )
        backend_execution_values = (
            {} if resolved_spec_type == "none" else cls._prepare_backend_execution()
        )
        bundle = normalize_media(images=images, audio=audio, video=video)
        model_selection = str(unwrap_required_scalar("model_path", model_path))
        mmproj_selection = str(unwrap_optional_scalar("mmproj_path", mmproj_path, NO_MMPROJ_OPTION))
        resolved_mmproj_path = (
            _resolve_gguf_selection(
                mmproj_selection,
                label="mmproj GGUF",
                required=False,
            )
            if bundle.items
            else ""
        )
        sampling_values = _resolve_sampling_values(
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            repeat_penalty=repeat_penalty,
            sampling=sampling,
        )
        runtime_values = _resolve_runtime_values(
            n_batch=n_batch,
            override_n_ubatch=override_n_ubatch,
            n_ubatch=n_ubatch,
            override_image_max_tokens=override_image_max_tokens,
            image_max_tokens=image_max_tokens,
            runtime=runtime,
        )
        ngram_speculative_values = {}
        if cls._supports_ngram_speculative:
            ngram_speculative_values["ngram_speculative"] = unwrap_optional_scalar(
                "ngram_speculative",
                ngram_speculative,
                None,
            )
        draft_selection = unwrap_optional_scalar(
            "draft_model",
            draft_model,
            NO_DRAFT_OPTION,
        )
        selected_mtp_provider = str(
            unwrap_optional_scalar("mtp_provider", mtp_provider, "off")
        )
        resolved_mtp_provider = (
            selected_mtp_provider if resolved_spec_type == "draft-mtp" else "off"
        )
        speculative_values = {}
        if draft_model is not None or resolved_mtp_provider != "off":
            draft_required = resolved_spec_type in {"draft-dflash", "draft-dspark"} or (
                resolved_spec_type == "draft-mtp"
                and resolved_mtp_provider == "external_gemma4"
            )
            speculative_values = {
                "draft_model_path": (
                    _resolve_gguf_selection(
                        str(draft_selection),
                        label=(
                            "Gemma 4 MTP assistant GGUF"
                            if resolved_mtp_provider == "external_gemma4"
                            else "draft model GGUF"
                        ),
                        required=draft_required,
                    )
                    if resolved_spec_type != "none"
                    else ""
                ),
                "spec_type": resolved_spec_type,
                "spec_n_max": int(
                    unwrap_optional_scalar("spec_n_max", spec_n_max, 2)
                ),
                "spec_n_min": int(
                    unwrap_optional_scalar("spec_n_min", spec_n_min, 0)
                ),
                "spec_p_min": float(
                    unwrap_optional_scalar("spec_p_min", spec_p_min, 0.0)
                ),
                "mtp_provider": resolved_mtp_provider,
            }
        result = run_chat(
            model_path=_resolve_gguf_selection(
                model_selection,
                label="model GGUF",
                required=True,
            ),
            mmproj_path=resolved_mmproj_path,
            handler=str(unwrap_optional_scalar("handler", handler, "auto")),
            thinking=bool(unwrap_optional_scalar("thinking", thinking, False)),
            reasoning_strength=str(
                unwrap_optional_scalar(
                    "reasoning_strength",
                    reasoning_strength,
                    "auto",
                )
            ),
            reasoning_budget=int(
                unwrap_optional_scalar(
                    "reasoning_budget",
                    reasoning_budget,
                    0,
                )
            ),
            system=str(unwrap_required_scalar("system", system)),
            prompt=str(unwrap_required_scalar("prompt", prompt)),
            media=bundle,
            n_ctx=int(unwrap_optional_scalar("n_ctx", n_ctx, 8192)),
            n_batch=int(runtime_values["n_batch"]),
            override_n_ubatch=bool(runtime_values["override_n_ubatch"]),
            n_ubatch=int(runtime_values["n_ubatch"]),
            override_image_max_tokens=bool(
                runtime_values["override_image_max_tokens"]
            ),
            image_max_tokens=int(runtime_values["image_max_tokens"]),
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
            **ngram_speculative_values,
            **speculative_values,
            **backend_execution_values,
        )
        return io.NodeOutput(
            result.response,
            result.thinking,
            json.dumps(result.raw, ensure_ascii=False, indent=2),
            json.dumps(result.metrics, ensure_ascii=False, indent=2),
            result.media_diagnostics,
        )


__all__ = ["LlamaCppImageListGenerateNode"]
