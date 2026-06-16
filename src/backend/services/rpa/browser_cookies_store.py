"""Browser session cookies Redis-persistence (Sprint 21 W7, G-06 closure).

Источник: PLAN.md V22.2 §4 + G-06 closure (browser cookies leak on worker restart).

Назначение:
    Сохраняет playwright/patchright BrowserContext.cookies() в Redis hash
    ``browser:session:{tenant}:{user}:{domain}`` с TTL 24h для восстановления
    логин-сессии после рестарта worker'а. Закрывает S-L5-2 (нет session
    persistence) и часть G-17 (browser leak при scaling).

Архитектура:
    Standalone helper класс — НЕ модифицирует PlaywrightBrowserPool (избегаем
    Playwright runtime в hot-path тестов). Интеграция через DI или явный
    call в RPA-route processor.

Структура Redis-ключа:
    ``browser:session:{tenant}:{user}:{domain}`` — JSON-сериализованный
    список cookies (формат playwright: name/value/domain/path/expires/httpOnly/
    secure/sameSite). TTL 24h.

Feature-flag:
    ``browser_cookies_redis_persist`` (W0) — default-OFF.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from src.backend.core.logging import get_logger

__all__ = ("BrowserCookieStore", "RedisLike")

_logger = get_logger(__name__)


class RedisLike(Protocol):
    """Минимальный Redis API: hset/hget/expire/delete для unit-test mock."""

    async def set(self, key: str, value: str, ex: int | None = None) -> Any: ...
    async def get(self, key: str) -> Any: ...
    async def delete(self, *keys: str) -> Any: ...


class BrowserCookieStore:
    """Сохраняет/восстанавливает cookies для browser sessions.

    Args:
        redis: redis-like async client (с set/get/delete API).
        ttl_seconds: TTL для Redis-ключа (default 86400 = 24h).
        key_prefix: namespace prefix (default "browser:session:").
    """

    def __init__(
        self,
        redis: RedisLike,
        *,
        ttl_seconds: int = 86400,
        key_prefix: str = "browser:session:",
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds должен быть >= 1")
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _make_key(self, tenant_id: str, user_id: str, domain: str) -> str:
        """Строит Redis-ключ для конкретной browser session."""

        # Нормализуем чтобы избежать collision через empty parts
        def safe(v: Any) -> str:
            return str(v or "_")

        return f"{self._prefix}{safe(tenant_id)}:{safe(user_id)}:{safe(domain)}"

    async def save_cookies(
        self,
        *,
        tenant_id: str,
        user_id: str,
        domain: str,
        cookies: list[dict[str, Any]],
    ) -> None:
        """Сохраняет cookies в Redis с TTL.

        Args:
            tenant_id: multi-tenant scope.
            user_id: ID пользователя браузерной сессии.
            domain: domain для которого cookies применяются.
            cookies: список dict-cookies (playwright формат).
        """
        if not cookies:
            return
        key = self._make_key(tenant_id, user_id, domain)
        payload = json.dumps(cookies, ensure_ascii=False)
        try:
            await self._redis.set(key, payload, ex=self._ttl)
        except Exception as exc:
            _logger.warning("BrowserCookieStore.save_cookies failed: %s", exc)

    async def restore_cookies(
        self, *, tenant_id: str, user_id: str, domain: str
    ) -> list[dict[str, Any]]:
        """Возвращает cookies (пустой список если ключ не найден)."""
        key = self._make_key(tenant_id, user_id, domain)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            _logger.warning("BrowserCookieStore.restore_cookies failed: %s", exc)
            return []
        if raw is None:
            return []
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw)
        except TypeError, json.JSONDecodeError:
            _logger.warning("BrowserCookieStore.restore: malformed JSON key=%s", key)
            return []

    async def clear(self, *, tenant_id: str, user_id: str, domain: str) -> None:
        """Удаляет cookies (logout / explicit clear)."""
        key = self._make_key(tenant_id, user_id, domain)
        try:
            await self._redis.delete(key)
        except Exception as exc:
            _logger.warning("BrowserCookieStore.clear failed: %s", exc)
