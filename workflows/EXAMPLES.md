# Examples
This document contains example workflows for beginner.

### Used model
[unsloth/gemma-4-E4B-it-qat-GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-qat-GGUF) with Multimodal vision, MTP support

### Required steps
If llama.cpp's `llama` executable exists on `PATH`, no additional step is needed.

If you dont' have any `llama` executable, you could download runtime from `Settings - llama-multimodal - Download llama.cpp`.

## Text Generation

![text workflow](./llamacpp_text.avif)

 * [Workflow](./llamacpp_text.json)

Input text prompt to generate text.

## Vision

![vision workflow](./llamacpp_vision.avif)

 * [Workflow](./llamacpp_vision.json)

Input text prompt + media to generate vision text.

## Choice (System-One)

![choice workflow](./llamacpp_choice.avif)

 * [Workflow](./llamacpp_choice.json)

Ask multiple questions to decide what answer should be positive.
