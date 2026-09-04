"""AuthResult — auth verification result data class (S61 M2-#1 split).

Extracted из :mod:`facade` (615 LOC god-object → split into data class
+ behavior class). AuthResult — pure data model, no methods, no I/O.

Re-exported из :mod:`facade` для backward-compat public API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class AuthResult:
    """S164 W2: нормализованный результат auth-проверки.

    Attributes:
        is_authenticated: True если JWT/SAML/API-key валиден.
        method: Метод auth (``"jwt"`` / ``"saml"`` / ``"api_key"``).
        subject: User identity (sub claim, saml NameID, API key id).
        tenant_id: Tenant ID (None если отсутствует).
        groups: Список групп пользователя (None если отсутствуют).
        capabilities: Список capabilities (None если RBAC не настроен).
        metadata: Дополнительные данные (raw claims / roles).

    """

    is_authenticated: bool
    method: str | None = None
    subject: str | None = None
    tenant_id: str | None = None
    groups: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ("AuthResult",)
