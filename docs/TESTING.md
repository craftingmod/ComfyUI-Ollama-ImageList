# Testing

Install the locked development dependencies and run the Python suite:

```bash
uv sync --locked --group dev
uv run pytest
```

The suite covers image/audio normalization and limits, PCM16 WAV encoding, Ollama request/response handling through a mock HTTP server, native llama.cpp sampling presets, image-only, audio-only, and mixed message construction plus unconditional cleanup through test doubles, the V3 node schemas and extension registration, and the thin package entrypoint. It does not launch a browser, Ollama, or a real GGUF model; schema registration is additionally checked against an installed ComfyUI environment during local development.
