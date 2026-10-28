"""Path safety utility — защита от path traversal для файловых процессоров.

Проверяет что путь:
- Не содержит '..' (traversal)
- Начинается с allowed префикса (allowlist)
- Не абсолютный путь вне allowed областей

Allowed префиксы (Wave 13 Q7 A) конфигурируются в конфиг-системе:
``settings.dsl.allowed_paths`` (секция ``dsl:`` в ``config_profiles/*.yml``).
Env var ``DSL_ALLOWED_PATHS`` (разделитель ``:``) остаётся override'ом
поверх конфига.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ("PathTraversalError", "validate_path")


class PathTraversalError(ValueError):
    """Raised when path violates safety rules."""


def _default_allowed_prefixes() -> tuple[str, ...]:
    """Встроенные fallback-префиксы (когда конфиг недоступен)."""
    return (
        "/data/uploads",
        "/data/exports",
        os.path.join(tempfile.gettempdir(), "dsl"),
        "/var/data",
    )


def _get_allowed_prefixes() -> tuple[str, ...]:
    """Читает разрешённые префиксы: env → конфиг → defaults.

    Приоритет источников:
    1. env ``DSL_ALLOWED_PATHS`` (override, разделитель ``:``);
    2. конфиг ``settings.dsl.allowed_paths`` (YAML-профиль);
    3. встроенные defaults (конфиг недоступен).

    Returns:
        Кортеж разрешённых префиксов.

    """
    env = os.environ.get("DSL_ALLOWED_PATHS", "")
    if env:
        prefixes = tuple(p.strip() for p in env.split(":") if p.strip())
        if prefixes:
            return prefixes

    try:
        from src.backend.core.config.settings import settings

        configured = tuple(
            str(p).strip() for p in settings.dsl.allowed_paths if str(p).strip()
        )
    except Exception as exc:  # noqa: BLE001 - конфиг недоступен → defaults
        from src.backend.core.logging import get_logger

        get_logger("dsl.path_safety").warning(
            "allowed_paths: settings unavailable (%s) — fallback to defaults", exc
        )
        configured = ()
    if configured:
        return configured

    return _default_allowed_prefixes()


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
        if resolved_str == prefix_resolved or resolved_str.startswith(
            prefix_resolved + os.sep
        ):
            return resolved_str

    raise PathTraversalError(
        f"Path '{path}' is outside allowed directories. "
        f"Allowed prefixes: {', '.join(allowed)}"
    )
