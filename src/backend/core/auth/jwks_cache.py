"""JWKS-кеш для верификации JWT с асимметричной подписью (RS256/ES256).

Получает JSON Web Key Set по HTTPS, кеширует на ``ttl`` секунд, защищён
``asyncio.Lock`` от двойного fetch'а при concurrent-cold-cache. При
network-failure возвращает stale-значение, если оно есть, — лучше
старый JWKS, чем 5xx на все JWT-запросы.

Wave [s2/k1-2-jwt-jwks] — V7 Auth-стек R1 (JWT + JWKS).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

__all__ = ("HttpJwksFetcher", "JwksCache", "JwksFetchError")

_logger = logging.getLogger(__name__)


class JwksFetchError(RuntimeError):
    """Ошибка получения JWKS из удалённого endpoint'а."""


class _HttpFetcher(Protocol):
    """Минимальный контракт HTTP-клиента: get(url) -> dict[str, Any]."""

    async def fetch(self, url: str) -> dict[str, Any]: ...


class HttpJwksFetcher:
    """HTTP-fetcher для JWKS-документа через :class:`OutboundHttpClient`.

    Используется по умолчанию; в тестах подменяется fake-fetcher'ом.
    """

    def __init__(self, http: Any | None = None) -> None:
        self._http = http

    async def fetch(self, url: str) -> dict[str, Any]:
        # Lazy-import — модуль ядра не должен зависеть от services/.
        if self._http is None:
            from src.backend.core.net.outbound_http import OutboundHttpClient

            self._http = OutboundHttpClient()
        response = await self._http.get(url, timeout=5.0)
        # Поддержка двух форм клиента: httpx.Response / dict-like.
        if hasattr(response, "json"):
            payload = response.json()
        else:
            payload = response
        if not isinstance(payload, dict):
            raise JwksFetchError(f"Некорректный JWKS payload: {type(payload).__name__}")
        return payload


class JwksCache:
    """Кеш JWKS-документа с TTL и stale-fallback.

    Args:
        url: URL JWKS endpoint'а (например, ``https://auth.example/.well-known/jwks.json``).
        ttl: Время жизни записи в секундах. По умолчанию 300 (5 минут).
        fetcher: HTTP-fetcher; если ``None`` — создаётся :class:`HttpJwksFetcher`.

    Attrs:
        url: URL JWKS endpoint'а.
    """

    def __init__(
        self, url: str, *, ttl: int = 300, fetcher: _HttpFetcher | None = None
    ) -> None:
        self.url = url
        self._ttl = ttl
        self._fetcher = fetcher or HttpJwksFetcher()
        self._lock = asyncio.Lock()
        self._cache: dict[str, Any] | None = None
        self._expires_at: float = 0.0

    def _is_fresh(self) -> bool:
        return self._cache is not None and time.monotonic() < self._expires_at

    async def _refresh(self) -> None:
        try:
            payload = await self._fetcher.fetch(self.url)
        except Exception as exc:
            if self._cache is not None:
                _logger.warning("JWKS refresh failed (%s); используем stale cache", exc)
                return
            raise JwksFetchError(
                f"Не удалось получить JWKS из {self.url}: {exc}"
            ) from exc
        self._cache = payload
        self._expires_at = time.monotonic() + self._ttl

    async def get_keys(self) -> dict[str, Any]:
        """Возвращает свежий JWKS-документ (с автоматическим refresh)."""
        if self._is_fresh():
            assert self._cache is not None
            return self._cache
        async with self._lock:
            if not self._is_fresh():
                await self._refresh()
            assert self._cache is not None
            return self._cache

    async def get_key(self, kid: str) -> dict[str, Any] | None:
        """Возвращает конкретный ключ JWKS по ``kid``.

        Args:
            kid: Идентификатор ключа из JWT header ``kid``.

        Returns:
            Словарь JWK или ``None`` если ключ не найден.
        """
        jwks = await self.get_keys()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None
