import json
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
    assert '"web"' in build_script
    assert '"js"' not in build_script
    assert 'web/index.js' in build_script
    assert '& $bun.Source run build' in build_script
    assert '[switch]$SkipFrontendBuild' in build_script

    publish_workflow = (
        REPO_ROOT / ".github" / "workflows" / "publish_action.yaml"
    ).read_text(encoding="utf-8")
    assert '      - "v*"' in publish_workflow
    assert "contents: write" in publish_workflow
    assert "./scripts/build-custom-node-zip.ps1" in publish_workflow
    assert "dist/ComfyUI-Ollama-ImageList-$version.zip" in publish_workflow
    assert "gh release create" in publish_workflow
    assert 'skip_checkout: "true"' in publish_workflow
    assert "--verify-tag" in publish_workflow
    assert "--generate-notes" in publish_workflow
    assert "windows-latest" not in publish_workflow
    assert publish_workflow.count("runs-on: ubuntu-latest") == 2
    assert publish_workflow.count("shell: pwsh") == 2


def test_frontend_toolchain_and_published_bundle_are_pinned():
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["packageManager"] == "bun@1.3.14"
    assert package["devDependencies"]["vite"].startswith("^8.")

    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yaml").read_text(
        encoding="utf-8"
    )
    publish_workflow = (
        REPO_ROOT / ".github" / "workflows" / "publish_action.yaml"
    ).read_text(encoding="utf-8")
    assert ci_workflow.count('bun-version: "1.3.14"') == 1
    assert "git diff --exit-code -- web/index.js" in ci_workflow
    assert publish_workflow.count('bun-version: "1.3.14"') == 2
    assert (REPO_ROOT / "web" / "index.js").is_file()
    assert list((REPO_ROOT / "web").rglob("*.js")) == [
        REPO_ROOT / "web" / "index.js"
    ]
