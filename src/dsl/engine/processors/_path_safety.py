"""Path safety utility — защита от path traversal для FileRead/FileWriteProcessor.

Проверяет что путь:
- Не содержит '..' (traversal)
- Начинается с allowed префикса (allowlist)
- Не абсолютный путь вне allowed областей

Allowed префиксы конфигурируются через env var DSL_ALLOWED_PATHS
(default: /data/uploads, /data/exports, /tmp/dsl).
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ("validate_path", "PathTraversalError")


class PathTraversalError(ValueError):
    """Raised when path violates safety rules."""


def _get_allowed_prefixes() -> tuple[str, ...]:
    """Читает разрешённые префиксы из env (fallback defaults)."""
    env = os.environ.get("DSL_ALLOWED_PATHS", "")
    if env:
        prefixes = tuple(p.strip() for p in env.split(":") if p.strip())
        if prefixes:
            return prefixes
    return ("/data/uploads", "/data/exports", "/tmp/dsl", "/var/data")


def validate_path(path: str) -> str:
    """Валидирует путь — raises PathTraversalError при нарушениях.

    Args:
        path: Пользовательский путь (может быть относительный).

    Returns:
        Нормализованный абсолютный путь (resolved).

    Raises:
        PathTraversalError: При попытке path traversal или выхода
            за пределы allowed префиксов.
    """
    if not isinstance(path, str) or not path:
        raise PathTraversalError("Path must be a non-empty string")

    if ".." in path.split("/"):
        raise PathTraversalError(f"Path traversal detected: {path}")

    try:
        resolved = Path(path).resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise PathTraversalError(f"Invalid path '{path}': {exc}") from exc

    resolved_str = str(resolved)
    allowed = _get_allowed_prefixes()
    for prefix in allowed:
        prefix_resolved = str(Path(prefix).resolve())
        if resolved_str == prefix_resolved or resolved_str.startswith(prefix_resolved + os.sep):
            return resolved_str

    raise PathTraversalError(
        f"Path '{path}' is outside allowed directories. "
        f"Allowed prefixes: {', '.join(allowed)}"
    )
