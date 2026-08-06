import tomllib
from pathlib import Path

from conftest import load_package_from_path


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT_PATH = REPO_ROOT / "__init__.py"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def test_v3_entrypoint_exports_loader_and_frontend_directory():
    module = load_package_from_path(
        "ollama_image_list_entrypoint",
        ENTRYPOINT_PATH,
        repo_root=REPO_ROOT,
    )

    assert callable(module.comfy_entrypoint)
    assert module.WEB_DIRECTORY == "./js"
    assert module.__all__ == ["WEB_DIRECTORY", "comfy_entrypoint"]


def test_comfy_registry_metadata_matches_the_package():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "comfyui-ollama-image-list"
    assert pyproject["project"]["version"] == "0.1.0"
    assert pyproject["tool"]["comfy"] == {
        "PublisherId": "craftingmod",
        "DisplayName": "Ollama Image List",
        "requires-comfyui": ">=0.18.1",
    }
