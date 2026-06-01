"""AuthBackend Protocol — единый контракт для всех auth-механизмов.

Каждый backend (API-Key, JWT, mTLS, SAML) реализует :class:`AuthBackend`
и возвращает :class:`AuthContext` либо ``None`` при отсутствии credentials.

Используется в ``entrypoints/api/dependencies/auth_selector`` —
``_verify_*`` функции становятся тонкими адаптерами вокруг ``backend.verify(request)``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import Request

from src.backend.core.auth import AuthContext, AuthMethod

__all__ = ("AuthBackend",)


@runtime_checkable
class AuthBackend(Protocol):
    """Контракт верификатора авторизации.

    Каждая реализация декларирует :attr:`method` и реализует :meth:`verify`,
    которая возвращает :class:`AuthContext` при успехе и ``None`` если
    credentials отсутствуют или невалидны (вызывающий слой решит, бросать
    ли 401/403 или попробовать следующий backend).
    """

    method: AuthMethod

    async def verify(self, request: Request) -> AuthContext | None:
        """Проверяет credentials в запросе.

        Args:
            request: FastAPI request с headers/cookies/state.

        Returns:
            :class:`AuthContext` при успехе или ``None`` если credentials
            отсутствуют или невалидны.
        """
        ...
