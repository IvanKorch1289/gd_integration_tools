"""Extension-safe infrastructure registry (S172 M3 — ARC-006).

Public API для ``extensions/<name>/`` plugins чтобы зарегистрировать
свой infrastructure-модуль в core DI registry.

Проблема (pre-M3):
    ``core/di/module_registry.py:INFRA_MODULES`` — static dict,
    populated only при загрузке модуля через import. Если extension
    хочет зарегистрировать свой DI-resolvable module, он не мог
    добавить запись в ``INFRA_MODULES`` без edit core.

Решение (S172 M3):
    Extension-safe facade c **plugin-path validation** — extensions
    могут регистрировать ТОЛЬКО модули внутри своего ``extensions/<name>/``
    namespace (path-prefix check). Core не может регистрировать
    extension-mapped modules через этот API — single-direction trust.

Security:
* ``register_extension_module(key, dotted_path)`` validates
  ``dotted_path`` начинается с ``extensions.`` (per V11.1 plugin rules).
* Если extension пытается зарегистрировать core / infrastructure /
  services prefix → ``PermissionError`` (хорошо для security).
* Idempotent — повторный register = no-op (no clobber).
* Thread-safe через :class:`threading.Lock` (DI вызывается из
  multiple asyncio tasks).

API (S172 M3):

    from src.backend.core.di.module_registry import (
        register_extension_module,
        unregister_extension_module,
        clear_extension_modules,
        list_extension_modules,
    )

    # В plugin.py:
    register_extension_module(
        "my_extension.metrics_collector",
        "extensions.my_extension.infrastructure.metrics_collector",
    )

Lifecycle:
    Extension lifecycle hook (``BasePlugin.on_load()``) → register.
    ``on_unload()`` → unregister. Idempotent.
"""

from __future__ import annotations

import threading
from re import Pattern
from typing import Final

from src.backend.core.logging import get_logger

__all__ = (
    "ExtensionRegistrationError",
    "clear_extension_modules",
    "is_extension_path",
    "list_extension_modules",
    "register_extension_module",
    "unregister_extension_module",
)

_logger = get_logger("core.di.extensions")


# Storage for extension-registered modules. Maps ``key`` → ``dotted_path``.
# Maintained separately from ``INFRA_MODULES`` static dict.
_extension_modules: dict[str, str] = {}

_extension_modules_lock: Final[threading.Lock] = threading.Lock()


# Разрешённые prefix'ы для extension-модулей. Закрытый whitelist (S172 M3):
# только под-плагины в ``extensions/<name>/...``.
EXTENSION_PATH_PREFIX: Final[str] = "extensions."

# Maximum length safety — extensions не могут регистрировать произвольно
# длинные strings (defense against typo / injection).
_MAX_DOTTED_PATH_LENGTH: Final[int] = 200

# Разрешённые символы в module path: lowercase letters, digits, dot,
# underscore. Никаких ``..``, ``/``, leading dot, trailing dot.
_MODULE_PATH_PATTERN: Final[Pattern[str]] = ...


class ExtensionRegistrationError(ValueError):
    """Ошибка регистрации extension-модуля.

    Поднимается на:
    * Non-``extensions.`` prefix.
    * Duplicate key (``re-raise``).
    * Path-contains-illegal-characters.
    * Длина пути > 200 chars.
    """


def is_extension_path(dotted_path: str) -> bool:
    """Проверить, что ``dotted_path`` — корректный extension module path.

    Returns:
        ``True`` если путь начинается с ``extensions.`` и содержит
        только разрешённые символы (lowercase letters / digits /
        dot / underscore). Hyphens, spaces и спец-символы запрещены
        (defense against typo-импортов вроде ``extensions.foo-bar``).
    """
    if not isinstance(dotted_path, str) or not dotted_path:
        return False
    if not dotted_path.startswith(EXTENSION_PATH_PREFIX):
        return False
    if len(dotted_path) > _MAX_DOTTED_PATH_LENGTH:
        return False
    # Disallow ``..``, leading/trailing dot, dot-adjacent.
    if ".." in dotted_path or dotted_path.endswith("."):
        return False
    # Defense against hyphen / space / unicode / uppercase typo-imports.
    # Разрешаем только [a-z0-9._].
    for ch in dotted_path:
        if not (ch.isascii() and (ch.islower() or ch.isdigit() or ch in "._")):
            return False
    return True


def register_extension_module(key: str, dotted_path: str) -> bool:
    """Зарегистрировать infrastructure-модуль extension'а в DI registry.

    Args:
        key: Логический ключ для ``resolve_module(key)`` /
            ``get_module_scope(key)``. Должен начинаться с имени extension'
            (например ``"my_plugin.metrics"``).
        dotted_path: Полный dotted-path модуля (например
            ``"extensions.my_plugin.infrastructure.metrics"``).
            Должен начинаться с ``extensions.`` prefix.

    Returns:
        ``True`` если registration applied (new key), ``False`` если
        key уже зарегистрирован (idempotent no-op).

    Raises:
        ExtensionRegistrationError: Если path validation fails.
        TypeError: Если ``key`` или ``dotted_path`` не str.

    Examples::

        # В extensions/my_plugin/plugin.py:
        from src.backend.core.di.module_registry import (
            register_extension_module,
        )

        def on_load() -> None:
            register_extension_module(
                "my_plugin.metrics",
                "extensions.my_plugin.infrastructure.metrics_collector",
            )

    Notes:
        * Idempotent: повторный register уже зарегистрированного ключа
          → ``False`` (no clobber, no exception).
        * Thread-safe.
        * Safe by default: extension не может зарегистрировать модуль
          вне ``extensions.`` prefix.
    """
    if not isinstance(key, str) or not key:
        raise TypeError(f"key must be non-empty str, got {type(key).__name__}")
    if not isinstance(dotted_path, str):
        raise TypeError(
            f"dotted_path must be str, got {type(dotted_path).__name__}"
        )
    if not is_extension_path(dotted_path):
        raise ExtensionRegistrationError(
            f"dotted_path must start with '{EXTENSION_PATH_PREFIX}' "
            f"and contain only [a-z0-9._] characters; "
            f"got {dotted_path!r}"
        )

    with _extension_modules_lock:
        if key in _extension_modules:
            if _extension_modules[key] == dotted_path:
                _logger.debug(
                    "register_extension_module: idempotent no-op "
                    "(key=%r already registered)",
                    key,
                )
                return False
            raise ExtensionRegistrationError(
                f"key={key!r} уже зарегистрирован с другим path "
                f"({_extension_modules[key]!r}); unregister первый"
            )
        _extension_modules[key] = dotted_path
        _logger.info(
            "register_extension_module: key=%r path=%r",
            key,
            dotted_path,
        )
        return True


def unregister_extension_module(key: str) -> bool:
    """Удалить extension module из DI registry.

    Args:
        key: Ключ модуля в extension-registry.

    Returns:
        ``True`` если registration удалена, ``False`` если ``key``
        не был зарегистрирован.
    """
    with _extension_modules_lock:
        if key not in _extension_modules:
            return False
        del _extension_modules[key]
        _logger.info("unregister_extension_module: key=%r", key)
        return True


def clear_extension_modules() -> int:
    """Удалить все extension-registrations.

    Используется в test fixtures (per-test isolation) и при production
    registry reset (rare, ops admin tool).

    Returns:
        Количество удалённых registrations (для diagnostics).

    Notes:
        M3.2 review O-6-3 fix: повышенный лог-уровень при bulk-clear
        (>10 entries) → warning, чтобы случайный global clear был
        виден в monitoring.
    """
    with _extension_modules_lock:
        count = len(_extension_modules)
        _extension_modules.clear()
        if count > 10:
            _logger.warning(
                "clear_extension_modules: bulk clear of %d entries "
                "(>10 threshold, suspicious)",
                count,
            )
        elif count:
            _logger.info(
                "clear_extension_modules: cleared %d entries", count
            )
        return count


def list_extension_modules() -> dict[str, str]:
    """Snapshot extension-registered modules (для diagnostics).

    Returns:
        Copy of ``{key: dotted_path}`` registry. Mutating возвращённый
        dict не влияет на внутреннее состояние.
    """
    with _extension_modules_lock:
        return dict(_extension_modules)


def is_extension_key_registered(key: str) -> bool:
    """Быстрый O(1) check — зарегистрирован ли key."""
    with _extension_modules_lock:
        return key in _extension_modules
