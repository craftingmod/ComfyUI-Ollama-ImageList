import tomllib
from pathlib import Path
import pytest

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
