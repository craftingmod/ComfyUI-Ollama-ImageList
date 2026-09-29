from __future__ import annotations

import os
from typing import Any


def normalize_llm_model_directory(path: str) -> str:
    return os.path.abspath(os.path.normpath(path))


def get_default_llm_model_directory(folder_paths: Any) -> str:
    return normalize_llm_model_directory(os.path.join(folder_paths.models_dir, "LLM"))


def get_llm_model_directories(folder_paths: Any) -> list[str]:
    source_paths: list[str] = []
    for folder_name, (
        paths,
        _extensions,
    ) in folder_paths.folder_names_and_paths.items():
        if folder_name.casefold() == "llm":
            source_paths.extend(paths)
    source_paths.append(get_default_llm_model_directory(folder_paths))

    model_dirs: list[str] = []
    seen: set[str] = set()
    for path in source_paths:
        normalized = normalize_llm_model_directory(path)
        identity = os.path.normcase(normalized)
        if identity in seen:
            continue
        seen.add(identity)
        model_dirs.append(normalized)
    return model_dirs


def resolve_llm_model_directory(
    candidate: str,
    model_dirs: list[str],
) -> str | None:
    identity = os.path.normcase(normalize_llm_model_directory(candidate))
    return next(
        (path for path in model_dirs if os.path.normcase(path) == identity),
        None,
    )
