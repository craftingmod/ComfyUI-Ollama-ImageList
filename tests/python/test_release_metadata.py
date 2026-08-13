import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_identity_and_archive_defaults_are_stable():
    metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "ollama-image-list"
    assert metadata["project"]["version"] == "0.6.0"
    assert metadata["project"]["description"] == (
        "Analyze ComfyUI image, audio, and video lists with Ollama, llama.cpp GGUF, "
        "or native generative CLIP backends"
    )

    build_script = (REPO_ROOT / "scripts" / "build-custom-node-zip.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert '[string]$PackageName = "ComfyUI-Ollama-ImageList"' in build_script
    assert '"CHANGELOG.md"' in build_script
    assert '"docs"' in build_script
    assert '"presets"' in build_script
    assert '"workflows"' in build_script

    publish_workflow = (
        REPO_ROOT / ".github" / "workflows" / "publish_action.yaml"
    ).read_text(encoding="utf-8")
    assert '      - "v*"' in publish_workflow
    assert "contents: write" in publish_workflow
    assert "./scripts/build-custom-node-zip.ps1" in publish_workflow
    assert "dist/ComfyUI-Ollama-ImageList-$version.zip" in publish_workflow
    assert "gh release create" in publish_workflow
    assert "--verify-tag" in publish_workflow
    assert "--generate-notes" in publish_workflow
    assert "windows-latest" not in publish_workflow
    assert publish_workflow.count("runs-on: ubuntu-latest") == 2
    assert publish_workflow.count("shell: pwsh") == 2
