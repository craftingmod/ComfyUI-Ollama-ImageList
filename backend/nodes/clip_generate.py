from __future__ import annotations

import inspect
from collections import deque
from typing import Any

from comfy_api.latest import io

from ..core import (
    DEFAULT_MEDIA_LIMITS,
    InputNormalizationError,
    unwrap_optional_scalar,
    unwrap_required_scalar,
)


GEMMA4_LIST_PR_URL = "https://github.com/Comfy-Org/ComfyUI/pull/15450"
MODEL_FORMATS = ["auto", "qwen3_vl", "qwen3_5", "gemma4"]


def _tensor_shape(value: Any, label: str) -> tuple[int, ...]:
    shape = getattr(value, "shape", None)
    if shape is None:
        raise InputNormalizationError(f"{label} is not a tensor-like IMAGE value.")
    try:
        result = tuple(int(dimension) for dimension in shape)
    except (TypeError, ValueError) as exc:
        raise InputNormalizationError(f"{label} has an invalid shape {shape!r}.") from exc
    if any(dimension < 0 for dimension in result):
        raise InputNormalizationError(f"{label} has an invalid shape {result!r}.")
    return result


def _collect_images(values: Any) -> list[Any]:
    """Flatten Comfy data lists and IMAGE batches without resizing any image."""
    images: list[Any] = []

    def visit(value: Any, path: str, depth: int) -> None:
        if value is None:
            return
        if depth > DEFAULT_MEDIA_LIMITS.max_list_depth:
            raise InputNormalizationError(
                "Image input nesting exceeds the configured limit of "
                f"{DEFAULT_MEDIA_LIMITS.max_list_depth}."
            )
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", depth + 1)
            return

        shape = _tensor_shape(value, f"Image input {path}")
        if len(shape) != 4:
            raise InputNormalizationError(
                f"Image input {path} has shape {shape}; expected [B,H,W,C]."
            )
        batch, height, width, channels = shape
        if batch <= 0 or height <= 0 or width <= 0:
            raise InputNormalizationError(f"Image input {path} has an empty dimension.")
        if channels not in (1, 3, 4):
            raise InputNormalizationError(
                f"Image input {path} has {channels} channels; expected 1, 3, or 4."
            )
        for batch_index in range(batch):
            if len(images) >= DEFAULT_MEDIA_LIMITS.max_images:
                raise InputNormalizationError(
                    "Image count exceeds the configured limit of "
                    f"{DEFAULT_MEDIA_LIMITS.max_images}."
                )
            images.append(value[batch_index : batch_index + 1])

    visit(values, "images", 0)
    return images


def _tokenizer_objects(clip: Any) -> list[Any]:
    """Return the small tokenizer object graph used by ComfyUI's CLIP wrapper."""
    root = getattr(clip, "tokenizer", None)
    if root is None:
        return []

    found: list[Any] = []
    queue: deque[tuple[Any, int]] = deque([(root, 0)])
    seen: set[int] = set()
    while queue:
        current, depth = queue.popleft()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        found.append(current)
        if depth >= 2:
            continue
        for value in getattr(current, "__dict__", {}).values():
            module = getattr(value.__class__, "__module__", "")
            if module.startswith("comfy"):
                queue.append((value, depth + 1))
    return found


def _detect_model_format(clip: Any) -> str | None:
    class_names = {
        base.__name__.lower()
        for tokenizer in _tokenizer_objects(clip)
        for base in tokenizer.__class__.__mro__
    }
    if any("gemma4" in name for name in class_names):
        return "gemma4"
    if any("qwen35" in name or "qwen3_5" in name for name in class_names):
        return "qwen3_5"
    if any("qwen3vl" in name or "qwen3_vl" in name for name in class_names):
        return "qwen3_vl"
    return None


def _supports_named_images(clip: Any) -> bool:
    for tokenizer in _tokenizer_objects(clip):
        method = getattr(tokenizer, "tokenize_with_weights", None)
        if not callable(method):
            continue
        try:
            if "images" in inspect.signature(method).parameters:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _same_image_shape(images: list[Any]) -> bool:
    return len({_tensor_shape(image, "Image")[-3:] for image in images}) <= 1


def _batch_images(images: list[Any]) -> Any | None:
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    if not _same_image_shape(images):
        raise InputNormalizationError(
            "This CLIP tokenizer cannot accept a LIST containing different image "
            "resolutions. Update to a ComfyUI build with explicit images= support. "
            f"Gemma 4 tracking PR: {GEMMA4_LIST_PR_URL}"
        )
    try:
        import torch

        return torch.cat(images, dim=0)
    except (ImportError, RuntimeError, TypeError, ValueError) as exc:
        raise InputNormalizationError("The IMAGE list could not be combined into one batch.") from exc


def _escape_template_text(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def _qwen_template(system: str, image_count: int) -> str:
    vision = "<|vision_start|><|image_pad|><|vision_end|>" * image_count
    return (
        f"<|im_start|>system\n{_escape_template_text(system)}<|im_end|>\n"
        f"<|im_start|>user\n{vision}{{}}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _gemma_video_media(frame_count: int, fps: int = 24) -> str:
    sampled = max(1, (frame_count + fps - 1) // fps)
    markers = []
    for index in range(sampled):
        timestamp = f"{index // 60:02d}:{index % 60:02d}"
        markers.append(f"{timestamp} <|image><|video|><image|>")
    return "\n\n" + " ".join(markers) + "\n\n"


def _gemma_template(
    system: str,
    *,
    image_count: int,
    video_frame_count: int,
    thinking: bool,
) -> str:
    system_body = _escape_template_text(system)
    if thinking:
        system_body += "\n<|think|>"
    media = ""
    if video_frame_count:
        media = _gemma_video_media(video_frame_count)
    elif image_count:
        media = "\n\n" + "\n\n\n\n".join(
            "<|image><|image|><image|>" for _ in range(image_count)
        ) + "\n\n"
    model_open = "" if thinking else "<|channel>thought\n<channel|>"
    return (
        f"<|turn>system\n{system_body}<turn|>\n"
        f"<|turn>user\n{{}}{media}<turn|>\n"
        f"<|turn>model\n{model_open}"
    )


def _resolve_media_kwargs(
    clip: Any,
    model_format: str | None,
    images: list[Any],
    video: Any,
    audio: Any,
) -> dict[str, Any]:
    if model_format in {"qwen3_vl", "qwen3_5"}:
        if video is not None or audio is not None:
            raise InputNormalizationError(
                f"{model_format} Generate Text supports IMAGE input, not VIDEO or AUDIO."
            )
        return {"images": images} if images else {}

    if model_format == "gemma4":
        if images and video is not None:
            raise InputNormalizationError(
                "Gemma 4 gives VIDEO precedence over IMAGE; connect only one of them."
            )
        if images and _supports_named_images(clip):
            return {"images": images, "video": video, "audio": audio}
        return {"image": _batch_images(images), "video": video, "audio": audio}

    return {"image": _batch_images(images), "video": video, "audio": audio}


class ClipImageListGenerateNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        sampling_options = [
            io.DynamicCombo.Option(
                key="on",
                inputs=[
                    io.Float.Input("temperature", default=0.7, min=0.01, max=2.0, step=0.000001),
                    io.Int.Input("top_k", default=64, min=0, max=1000),
                    io.Float.Input("top_p", default=0.95, min=0.0, max=1.0, step=0.01),
                    io.Float.Input("min_p", default=0.05, min=0.0, max=1.0, step=0.01),
                    io.Float.Input(
                        "repetition_penalty", default=1.05, min=0.0, max=5.0, step=0.01
                    ),
                    io.Int.Input(
                        "seed",
                        default=0,
                        min=0,
                        max=0xFFFFFFFFFFFFFFFF,
                        control_after_generate=True,
                    ),
                    io.Float.Input(
                        "presence_penalty",
                        optional=True,
                        default=0.0,
                        min=0.0,
                        max=5.0,
                        step=0.01,
                    ),
                ],
            ),
            io.DynamicCombo.Option(key="off", inputs=[]),
        ]
        return io.Schema(
            node_id="OllamaImageList_CLIPGenerateText",
            display_name="CLIP Generate Text (Image List)",
            category="Ollama/CLIP",
            description=(
                "Extends ComfyUI Generate Text with a system role and one-call IMAGE LIST support."
            ),
            inputs=[
                io.Clip.Input("clip"),
                io.String.Input("system", multiline=True, dynamic_prompts=False, default=""),
                io.String.Input("prompt", multiline=True, dynamic_prompts=True, default=""),
                io.Image.Input("images", optional=True),
                io.Image.Input(
                    "video",
                    optional=True,
                    tooltip="Video frames as one IMAGE batch; assumed to be 24 FPS.",
                ),
                io.Audio.Input("audio", optional=True),
                io.Combo.Input(
                    "model_format",
                    options=MODEL_FORMATS,
                    default="auto",
                    tooltip="Auto-detect the tokenizer, or manually select its chat format.",
                ),
                io.Int.Input("max_length", default=512, min=1, max=32768),
                io.DynamicCombo.Input(
                    "sampling_mode", options=sampling_options, display_name="Sampling Mode"
                ),
                io.Boolean.Input(
                    "thinking",
                    optional=True,
                    default=False,
                    tooltip="Operate in thinking mode if the model supports it.",
                ),
                io.Boolean.Input(
                    "use_default_template",
                    optional=True,
                    default=True,
                    tooltip=(
                        "Apply the model chat template. Disable only when prompt already contains "
                        "the complete model-specific template."
                    ),
                    advanced=True,
                ),
            ],
            outputs=[io.String.Output("generated_text", display_name="generated_text")],
            is_input_list=True,
        )

    @classmethod
    def execute(
        cls,
        clip,
        system,
        prompt,
        model_format,
        max_length,
        sampling_mode,
        images=None,
        video=None,
        audio=None,
        thinking=False,
        use_default_template=True,
    ) -> io.NodeOutput:
        clip_value = unwrap_required_scalar("clip", clip)
        system_value = str(unwrap_required_scalar("system", system))
        prompt_value = str(unwrap_required_scalar("prompt", prompt))
        requested_format = str(unwrap_required_scalar("model_format", model_format))
        if requested_format not in MODEL_FORMATS:
            raise InputNormalizationError(
                f"model_format must be one of {', '.join(MODEL_FORMATS)}."
            )
        max_length_value = int(unwrap_required_scalar("max_length", max_length))
        sampling = unwrap_required_scalar("sampling_mode", sampling_mode)
        thinking_value = bool(unwrap_optional_scalar("thinking", thinking, False))
        use_template = bool(
            unwrap_optional_scalar("use_default_template", use_default_template, True)
        )
        video_value = unwrap_optional_scalar("video", video, None)
        audio_value = unwrap_optional_scalar("audio", audio, None)
        image_values = _collect_images(images)

        detected_format = _detect_model_format(clip_value)
        resolved_format = detected_format if requested_format == "auto" else requested_format
        if requested_format == "auto" and system_value and resolved_format is None:
            raise InputNormalizationError(
                "The CLIP tokenizer is not recognized, so its system-role format cannot be "
                "selected automatically. Choose a model_format manually."
            )
        if not use_template and system_value:
            raise InputNormalizationError(
                "system must be empty when use_default_template is disabled; include the full "
                "system turn in prompt instead."
            )

        media_kwargs = _resolve_media_kwargs(
            clip_value, resolved_format, image_values, video_value, audio_value
        )
        tokenize_kwargs: dict[str, Any] = {
            "skip_template": not use_template,
            "min_length": 1,
            "thinking": thinking_value,
            **media_kwargs,
        }
        if use_template and system_value:
            if resolved_format in {"qwen3_vl", "qwen3_5"}:
                tokenize_kwargs["llama_template"] = _qwen_template(
                    system_value, len(image_values)
                )
            elif resolved_format == "gemma4":
                if audio_value is not None:
                    raise InputNormalizationError(
                        "Gemma 4 system-role formatting with AUDIO is not supported because "
                        "ComfyUI does not expose a public audio placeholder formatter. Leave "
                        "system empty to use the official model template."
                    )
                video_frames = (
                    _tensor_shape(video_value, "Video input")[0]
                    if video_value is not None
                    else 0
                )
                tokenize_kwargs["llama_template"] = _gemma_template(
                    system_value,
                    image_count=len(image_values),
                    video_frame_count=video_frames,
                    thinking=thinking_value,
                )

        tokens = clip_value.tokenize(prompt_value, **tokenize_kwargs)
        do_sample = sampling.get("sampling_mode") == "on"
        generated_ids = clip_value.generate(
            tokens,
            do_sample=do_sample,
            max_length=max_length_value,
            temperature=sampling.get("temperature", 1.0),
            top_k=sampling.get("top_k", 50),
            top_p=sampling.get("top_p", 1.0),
            min_p=sampling.get("min_p", 0.0),
            repetition_penalty=sampling.get("repetition_penalty", 1.0),
            presence_penalty=sampling.get("presence_penalty", 0.0),
            seed=sampling.get("seed"),
        )
        return io.NodeOutput(clip_value.decode(generated_ids))
