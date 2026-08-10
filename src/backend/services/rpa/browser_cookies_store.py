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

Security (Cycle 33 RPA1):
    Cookies **encrypted at rest** via Fernet (AES-128-CBC + HMAC-SHA256).
    Key derived from env var ``BROWSER_COOKIES_FERNET_KEY`` (44-byte URL-safe
    base64). If key not set in production: ``RuntimeError`` at construction.
    In dev_light profile: auto-generates ephemeral key (logs warning).

Feature-flag:
    ``browser_cookies_redis_persist`` (W0) — default-OFF.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from src.backend.core.logging import get_logger

__all__ = ("BrowserCookieStore", "RedisLike")

_logger = get_logger(__name__)


class RedisLike(Protocol):
    """Минимальный Redis API: hset/hget/expire/delete для unit-test mock."""

    async def set(self, key: str, value: str, ex: int | None = None) -> Any:
        """Сохранить cookie ``key=value`` (опц. ``ex`` seconds TTL)."""
        ...
    async def get(self, key: str) -> Any:
        """Получить cookie value по ``key``; None если отсутствует."""
        ...
    async def delete(self, *keys: str) -> Any:
        """Удалить один или несколько cookie keys."""
        ...


def _load_or_create_fernet_key() -> bytes:
    """Cycle 33 RPA1: load Fernet key from env or generate for dev.

    Production: requires ``BROWSER_COOKIES_FERNET_KEY`` env var (44-byte
    URL-safe base64, generate with ``Fernet.generate_key()``).
    dev_light: auto-generates ephemeral key, logs warning.

    Raises:
        RuntimeError: non-dev_light + no key configured.

    """
    from cryptography.fernet import Fernet

    from src.backend.core.config.profile import AppProfileChoices, get_active_profile

    key = os.environ.get("BROWSER_COOKIES_FERNET_KEY", "")
    if key:
        try:
            return Fernet(key.encode("ascii"))._key  # type: ignore[attr-defined]
        except Exception as exc:
            raise RuntimeError(
                f"BROWSER_COOKIES_FERNET_KEY invalid: {exc}. "
                "Generate a new key: Fernet.generate_key().decode()",
            ) from exc

    if get_active_profile() == AppProfileChoices.dev_light:
        new_key = Fernet.generate_key()
        _logger.warning(
            "BrowserCookieStore: BROWSER_COOKIES_FERNET_KEY not set in "
            "dev_light — auto-generating ephemeral key. DO NOT USE IN PROD. "
            "Generated key prefix: %s...",
            new_key[:12].decode("ascii", errors="replace"),
        )
        return new_key

    raise RuntimeError(
        "BROWSER_COOKIES_FERNET_KEY required in non-dev_light profile. "
        'Generate via: python -c "from cryptography.fernet import Fernet; '
        'print(Fernet.generate_key().decode())". Store in Vault or k8s '
        "secret and inject as env var.",
    )


class BrowserCookieStore:
    """Сохраняет/восстанавливает cookies для browser sessions.

    Args:
        redis: redis-like async client (с set/get/delete API).
        ttl_seconds: TTL для Redis-ключа (default 86400 = 24h).
        key_prefix: namespace prefix (default "browser:session:").
        fernet_key: Fernet key bytes (default: load from env).
            Pass explicitly to override (e.g. for testing).

    """

    def __init__(
        self,
        redis: RedisLike,
        *,
        ttl_seconds: int = 86400,
        key_prefix: str = "browser:session:",
        fernet_key: bytes | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds должен быть >= 1")
        from cryptography.fernet import Fernet

        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = key_prefix
        # Cycle 33 RPA1: Fernet for at-rest encryption.
        # Fernet(key) validates key length (44 bytes b64 = 32 bytes raw).
        self._fernet = Fernet(fernet_key or _load_or_create_fernet_key())

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
        """Сохраняет cookies в Redis с TTL (Fernet-encrypted at rest).

        Args:
            tenant_id: multi-tenant scope.
            user_id: ID пользователя браузерной сессии.
            domain: domain для которого cookies применяются.
            cookies: список dict-cookies (playwright формат).

        """
        if not cookies:
            return
        key = self._make_key(tenant_id, user_id, domain)
        # Cycle 35: deduplicate — only write if cookies actually changed
        # since last save. Avoids redundant Redis writes on every nav
        # event when browser context didn't accumulate new cookies.
        new_payload = json.dumps(
            sorted(cookies, key=lambda c: c.get("name", "")),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        new_ciphertext = self._fernet.encrypt(new_payload)
        try:
            existing_raw = await self._redis.get(key)
        except (ConnectionError, TimeoutError) as read_exc:
            # D-A1-04 fix (cycle 36): narrow exceptions + observability.
            # Bare `except Exception` маскировал Redis backend failures
            # (Redis down, timeout). Fallback: write fresh cookies.
            _logger.warning(
                "BrowserCookieStore.redis_get_failed",
                extra={"error": str(read_exc)},
            )
            existing_raw = None  # proceed with write if read fails
        if existing_raw is not None:
            try:
                existing_plain = self._fernet.decrypt(existing_raw)
            except (ValueError, TypeError) as decrypt_exc:
                # D-A1-04 fix (cycle 36): narrow exceptions + observability.
                # Bare `except Exception` маскировал corrupted ciphertext
                # (key rotation, tampering). Fallback: write fresh cookies.
                _logger.warning(
                    "BrowserCookieStore.fernet_decrypt_failed",
                    extra={"error": str(decrypt_exc)},
                )
                existing_plain = None  # corrupted → write new
            if existing_plain == new_payload:
                # No-op: cookies unchanged since last save.
                return
        try:
            await self._redis.set(key, new_ciphertext, ex=self._ttl)
        except Exception as exc:
            _logger.warning("BrowserCookieStore.save_cookies failed: %s", exc)

    async def restore_cookies(
        self, *, tenant_id: str, user_id: str, domain: str,
    ) -> list[dict[str, Any]]:
        """Возвращает cookies (пустой список если ключ не найден или decrypt fails)."""
        key = self._make_key(tenant_id, user_id, domain)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            _logger.warning("BrowserCookieStore.restore_cookies failed: %s", exc)
            return []
        if raw is None:
            return []
        # raw is bytes from Fernet.encrypt output.
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        try:
            plaintext = self._fernet.decrypt(raw)
            return json.loads(plaintext)
        except Exception as exc:
            _logger.warning(
                "BrowserCookieStore.restore: decrypt failed (key=%s): %s",
                key,
                exc,
            )
            return []

    async def clear(self, *, tenant_id: str, user_id: str, domain: str) -> None:
        """Удаляет cookies (logout / explicit clear)."""
        key = self._make_key(tenant_id, user_id, domain)
        try:
            await self._redis.delete(key)
        except Exception as exc:
            _logger.warning("BrowserCookieStore.clear failed: %s", exc)
