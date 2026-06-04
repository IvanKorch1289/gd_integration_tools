"""Sprint 8A K1 W1 — миграционный helper для WAF Phase-2.

Цель: дать callsite'ам единый API для исходящих HTTP-запросов без полного
переписывания. Под feature-flag ``waf_outbound_via_facade``:

* **OFF (default-OFF)**: возвращает обычный ``httpx.AsyncClient(timeout=...)``
  — legacy-поведение, нулевой риск регрессий.
* **ON**: возвращает :class:`OutboundHttpClient` с WAF-pre-hook + capability
  check + audit-event.

API сохраняет совместимость с ``async with`` блоком и стандартными
``.post()`` / ``.get()`` / ``.put()`` / ``.delete()`` вызовами; разница только
во внешней логике (audit + WAF).

Использование::

    from src.backend.core.net.migration_helper import make_http_client

    async with make_http_client(timeout=30) as client:
        resp = await client.post(url, json=payload)

V15 R-V15-5 — strict WAF policy для всех ``:external``.
S1 W1.1 DoD: ``rg "httpx\\.AsyncClient\\(\\)" src/ | grep -v core/net/`` = 0.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.backend.core.net.outbound_http import OutboundHttpClient

__all__ = ("make_http_client",)


def _flag_enabled() -> bool:
    """True, если ``feature_flags.waf_outbound_via_facade`` включён.

    Безопасно к импорту в unit-тестах без settings.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(getattr(feature_flags, "waf_outbound_via_facade", False))
    except Exception as _:
        return False


def make_http_client(
    *, timeout: float | httpx.Timeout | None = None, plugin: str = "core", **kwargs: Any
) -> OutboundHttpClient | httpx.AsyncClient:
    """Возвращает HTTP-клиент с WAF-обвязкой (при flag ON) или legacy httpx.

    Args:
        timeout: Стандартный таймаут (число или :class:`httpx.Timeout`).
        plugin: Имя caller'а для audit-event (только при flag ON).
        **kwargs: Дополнительные параметры, прокидываются в
            :class:`httpx.AsyncClient` (verify, cert, base_url, ...).
            Игнорируются при flag ON, кроме явно поддерживаемых
            (verify/cert/base_url/http2).

    Returns:
        Async-context-manager совместимый клиент с ``post/get/put/delete``.

    Пример::

        async with make_http_client(timeout=30) as client:
            resp = await client.post(url, json=payload)
    """
    if _flag_enabled():
        # OutboundHttpClient импортирует tomы зависимостей (WAF + capability);
        # legacy путь — нулевая стоимость.
        passthrough = {
            k: v
            for k, v in kwargs.items()
            if k in {"verify", "cert", "base_url", "http2"}
        }
        if isinstance(timeout, (int, float)):
            timeout = httpx.Timeout(timeout)
        if timeout is not None:
            passthrough["timeout"] = timeout
        return OutboundHttpClient(plugin=plugin, **passthrough)

    # Legacy путь: чистый httpx.AsyncClient с теми же kwargs.
    client_kwargs: dict[str, Any] = dict(kwargs)
    if timeout is not None:
        client_kwargs["timeout"] = timeout
    return httpx.AsyncClient(**client_kwargs)
