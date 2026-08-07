# Testing

Install the locked development dependencies and run the Python suite:

```bash
uv sync --locked --group dev
uv run pytest
```

The suite covers image-list normalization and limits, Ollama request/response handling through a mock HTTP server, native llama.cpp sampling presets, message construction and unconditional cleanup through test doubles, the V3 node schemas and extension registration, and the thin package entrypoint. It does not install or launch ComfyUI, a browser, Ollama, or a real GGUF model.
