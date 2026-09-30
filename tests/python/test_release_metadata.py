import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_registry_runtime_avoids_dynamic_import_scanner_trigger():
    runtime_sources = [
        REPO_ROOT / "__init__.py",
        *(REPO_ROOT / "backend").rglob("*.py"),
    ]

    for source_path in runtime_sources:
        source = source_path.read_text(encoding="utf-8")
        assert "importlib.import_module" not in source, source_path.relative_to(
            REPO_ROOT
        )


def test_release_identity_and_archive_defaults_are_stable():
    metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "ollama-image-list"
    assert metadata["project"]["version"] == "0.7.0"
    assert metadata["project"]["description"] == (
        "Analyze ComfyUI image, audio, and video lists with Ollama, llama.cpp GGUF, "
        "or native generative CLIP backends"
    )
    assert metadata["tool"]["comfy"]["includes"] == [
        "dist",
        "locales",
        "subgraphs",
        "presets",
    ]

    package = (REPO_ROOT / "package.json").read_text(encoding="utf-8")
    assert '"name": "ollama-image-list"' in package
    assert '"build:custom-node"' in package
    assert '"release:check"' in package

    build_script = (REPO_ROOT / "scripts" / "build-custom-nodes.ts").read_text(
        encoding="utf-8"
    )
    assert "zipSync" in build_script
    assert "pyproject.toml" in build_script

    publish_workflow = (
        REPO_ROOT / ".github" / "workflows" / "publish_action.yaml"
    ).read_text(encoding="utf-8")
    assert '      - "v*"' in publish_workflow
    assert "contents: write" in publish_workflow
    assert "gh release create" in publish_workflow
    assert "--verify-tag" in publish_workflow
    assert "--generate-notes" in publish_workflow
    assert "bun run release:check" in publish_workflow
    assert "bun run build" in publish_workflow
    assert "publish-node-action@main" in publish_workflow
    assert "windows-latest" not in publish_workflow
