"""JWKS-кеш для верификации JWT с асимметричной подписью (RS256/ES256).

Получает JSON Web Key Set по HTTPS, кеширует на ``ttl`` секунд, защищён
``asyncio.Lock`` от двойного fetch'а при concurrent-cold-cache. При
network-failure возвращает stale-значение, если оно есть, — лучше
старый JWKS, чем 5xx на все JWT-запросы.

ADR-0419 (волна 24, кластер F4) — два ужесточения:

* **Предельное окно stale-fallback.** Stale-кеш больше не бессрочный:
  после последнего успешного refresh он допустим не дольше
  ``max_stale_seconds`` (консервативное значение по умолчанию). Иначе
  отозванный ``kid`` оставался бы валидным неограниченно долго.
* **HTTPS-only + SSRF-guard для ``jwks_url``.** ``http://`` — ошибка
  конфигурации (``JwksConfigurationError``), а не молчаливый downgrade;
  хост проверяется каноническим guard'ом ``core.net.url_guard``.

Wave [s2/k1-2-jwt-jwks] — V7 Auth-стек R1 (JWT + JWKS).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from src.backend.core.logging import get_logger
from src.backend.core.net.url_guard import UrlNotAllowedError, assert_safe_url

__all__ = (
    "DEFAULT_MAX_STALE_SECONDS",
    "HttpJwksFetcher",
    "JwksCache",
    "JwksConfigurationError",
    "JwksFetchError",
)

_logger = get_logger(__name__)

#: Предельное окно stale-fallback (сек) по умолчанию. Консервативно:
#: отозванный ``kid`` не остаётся валидным дольше окна после истечения
#: TTL (ADR-0419).
DEFAULT_MAX_STALE_SECONDS: Final = 600


class JwksFetchError(RuntimeError):
    """Ошибка получения JWKS из удалённого endpoint'а."""


class JwksConfigurationError(ValueError):
    """Некорректная конфигурация JWKS (URL/окно stale).

    Наследует :class:`ValueError` — конфигурационная ошибка должна быть
    видна сразу при старте, а не «молча» деградировать в рантайме.
    """


def _validate_jwks_url(url: str) -> str:
    """Проверить JWKS URL: только HTTPS + SSRF-guard (ADR-0419).

    Args:
        url: Конфигурируемый URL JWKS endpoint'а.

    Returns:
        Обрезанный URL (без пробелов по краям).

    Raises:
        JwksConfigurationError: Если URL пуст, схема не ``https`` либо хост
            нарушает SSRF-политику ``core.net.url_guard``.

    """
    candidate = (url or "").strip()
    if not candidate:
        raise JwksConfigurationError("jwks_url не может быть пустым")
    scheme = urlsplit(candidate).scheme.lower()
    if scheme != "https":
        raise JwksConfigurationError(
            f"jwks_url должен использовать схему https:// (получено "
            f"{scheme or 'none'!r}): {candidate!r}. Молчаливый downgrade "
            "на http запрещён."
        )
    try:
        # allow_private=True: JWKS-IdP — операторская конфигурация, внутренние
        # хосты (single-label / private-IP) допустимы. Заблокированы при этом
        # metadata-endpoint'ы и loopback-имена (``_BLOCKED_HOSTS``).
        assert_safe_url(candidate, allow_private=True)
    except UrlNotAllowedError as exc:
        raise JwksConfigurationError(f"Недопустимый jwks_url: {exc}") from exc
    return candidate


class _HttpFetcher(Protocol):
    """Минимальный контракт HTTP-клиента: get(url) -> dict[str, Any]."""

    async def fetch(self, url: str) -> dict[str, Any]:
        """Метод fetch (см. signature)."""
        ...


class HttpJwksFetcher:
    """HTTP-fetcher для JWKS-документа через :class:`OutboundHttpClient`.

    Используется по умолчанию; в тестах подменяется fake-fetcher'ом.
    """

    def __init__(self, http: Any | None = None, *, timeout: float = 5.0) -> None:
        self._http = http
        self._timeout = timeout

    async def fetch(self, url: str) -> dict[str, Any]:
        """Метод fetch (см. signature)."""
        # Lazy-import — модуль ядра не должен зависеть от services/.
        if self._http is None:
            from src.backend.core.net.outbound_http import OutboundHttpClient

            self._http = OutboundHttpClient()
        response = await self._http.get(url, timeout=self._timeout)
        # Поддержка двух форм клиента: httpx.Response / dict-like.
        if hasattr(response, "json"):
            payload = response.json()
        else:
            payload = response
        if not isinstance(payload, dict):
            raise JwksFetchError(f"Некорректный JWKS payload: {type(payload).__name__}")
        return payload


class JwksCache:
    """Кеш JWKS-документа с TTL и ограниченным stale-fallback.

    Args:
        url: URL JWKS endpoint'а (например, ``https://auth.example/.well-known/jwks.json``).
            Только HTTPS (ADR-0419); иначе — :class:`JwksConfigurationError`.
        ttl: Время жизни записи в секундах. По умолчанию 300 (5 минут).
        fetcher: HTTP-fetcher; если ``None`` — создаётся :class:`HttpJwksFetcher`.
        timeout: Таймаут HTTP-запроса JWKS в секундах (ADR-0411: значение
            берётся из ``security.jwks_fetch_timeout``).
        max_stale_seconds: Предельное окно stale-fallback в секундах —
            сколько после истечения TTL старый JWKS ещё допустим
            (ADR-0419). ``0`` — fail-closed без stale-fallback.

    Attrs:
        url: URL JWKS endpoint'а.

    Raises:
        JwksConfigurationError: Если URL не-HTTPS или нарушает SSRF-политику.

    """

    def __init__(
        self,
        url: str,
        *,
        ttl: int = 300,
        fetcher: _HttpFetcher | None = None,
        timeout: float = 5.0,
        max_stale_seconds: int = DEFAULT_MAX_STALE_SECONDS,
    ) -> None:
        self.url = _validate_jwks_url(url)
        self._ttl = ttl
        self._max_stale = max(0, int(max_stale_seconds))
        self._fetcher = fetcher or HttpJwksFetcher(timeout=timeout)
        self._lock = asyncio.Lock()
        self._cache: dict[str, Any] | None = None
        self._expires_at: float = 0.0
        self._stale_until: float = 0.0

    def _is_fresh(self) -> bool:
        return self._cache is not None and time.monotonic() < self._expires_at

    async def _refresh(self) -> None:
        try:
            payload = await self._fetcher.fetch(self.url)
        except Exception as exc:
            if self._cache is not None and time.monotonic() < self._stale_until:
                _logger.warning(
                    "JWKS refresh failed (%s); используем stale cache (окно %s c)",
                    exc,
                    self._max_stale,
                )
                return
            if self._cache is not None:
                # ADR-0419: stale-окно истекло — fail-closed. Отозванный kid
                # не должен оставаться валидным бессрочно.
                raise JwksFetchError(
                    f"Не удалось обновить JWKS из {self.url} и истекло окно "
                    f"stale-fallback ({self._max_stale} c): {exc}"
                ) from exc
            raise JwksFetchError(
                f"Не удалось получить JWKS из {self.url}: {exc}"
            ) from exc
        now = time.monotonic()
        self._cache = payload
        self._expires_at = now + self._ttl
        self._stale_until = self._expires_at + self._max_stale

    async def get_keys(self) -> dict[str, Any]:
        """Возвращает свежий JWKS-документ (с автоматическим refresh)."""
        if self._is_fresh():
            assert self._cache is not None  # nosec
            return self._cache
        async with self._lock:
            if not self._is_fresh():
                await self._refresh()
            assert self._cache is not None  # nosec
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
