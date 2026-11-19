"""DEPRECATED shim — реальная implementation переехала в ``core.auth.auth_selector``.

S96 W1: ``core.auth.auth_selector`` стал каноническим путём. Этот модуль
оставлен для backward compat (10 файлов импортируют ``require_auth``,
``set_default_auth``, ``verify_request``, ``AuthMethod``, ``AuthContext``
отсюда). Удалится в S99+ — к этому моменту все импорты должны быть
переведены на ``src.backend.core.auth.gateway`` или
``src.backend.core.auth.auth_selector``.

Issue: S96 W1 — downward layer violation ``core/auth/gateway.py →
entrypoints/api/dependencies/auth_selector``. Resolved by relocating
implementation to core.

Используйте ``src.backend.core.auth.gateway`` в новых расширениях::

    from src.backend.core.auth.gateway import (
        AuthContext,
        AuthMethod,
        require_auth,
        set_default_auth,
        verify_request,
    )

Ленивый re-export (PEP 562), волна 36
-------------------------------------
Раньше шим делал eager-``from src.backend.core.auth.auth_selector import ...``,
из-за чего объект-функция в шиме и в фасаде ``core.auth.gateway`` могли
разъехаться: любой ``importlib.reload`` шима пересоздавал его re-export'ы,
а фасад ``core.auth.gateway`` продолжал держать прежний объект. Инвариант
«``gateway.verify_request is auth_selector.verify_request``» (его проверяет
``tests/unit/core/auth/test_gateway_facade.py``) после reload'а становился
ложным — order-dependent падение. Теперь шим резолвит имена **на лету**
через канонический фасад ``core.auth.gateway``, поэтому объект всегда тот
же самый, независимо от reload'ов.
"""

from __future__ import annotations

import importlib
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для статического анализа (mypy)
    from src.backend.core.auth.gateway import (
        AuthContext,
        AuthMethod,
        require_auth,
        set_default_auth,
        verify_request,
    )

#: Имя символа → модуль-канон. Ленивый re-export (PEP 562).
_LAZY_EXPORTS: dict[str, str] = {
    "AuthContext": "src.backend.core.auth.gateway",
    "AuthMethod": "src.backend.core.auth.gateway",
    "require_auth": "src.backend.core.auth.gateway",
    "set_default_auth": "src.backend.core.auth.gateway",
    "verify_request": "src.backend.core.auth.gateway",
}


def __getattr__(name: str) -> Any:
    """Ленивый re-export публичного API канонического фасада (PEP 562).

    Args:
        name: Имя экспортируемого символа.

    Returns:
        Объект из ``src.backend.core.auth.gateway``.

    Raises:
        AttributeError: Символ не входит в публичный API шима.

    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Список публичных символов шима (для автодополнения)."""
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


warnings.warn(
    "Importing from src.backend.entrypoints.api.dependencies.auth_selector "
    "is deprecated. Use src.backend.core.auth.gateway instead "
    "(S96 W1 — implementation relocated to core.auth.auth_selector).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "AuthContext",
    "AuthMethod",
    "require_auth",
    "set_default_auth",
    "verify_request",
)
