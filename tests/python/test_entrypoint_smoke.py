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
    assert module.WEB_DIRECTORY == "./dist"
    assert module.__all__ == ["WEB_DIRECTORY", "comfy_entrypoint"]
