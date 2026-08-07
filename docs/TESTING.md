# Testing

Install the locked development dependencies and run the Python suite:

```bash
uv sync --locked --group dev
uv run pytest
```

The suite covers image/audio/video normalization and limits, PCM16 WAV encoding, Ollama request/response handling through a mock HTTP server, native llama.cpp sampling presets, image-only, audio-only, video-only, and mixed message construction, typed MTMD diagnostics, unconditional cleanup through test doubles, the V3 node schemas and extension registration, and the thin package entrypoint. It does not launch a browser or Ollama. Schema registration and short E4B multimodal inferences are additionally checked against the installed ComfyUI/fork environment during local development.
