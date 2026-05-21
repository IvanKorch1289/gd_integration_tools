"""Единый исходящий HTTP-клиент с WAF-pre-hook (V15 R-V15-5, S1 DoD).

Все ``:external`` capabilities обязаны идти через :class:`OutboundHttpClient`.
Альтернативные пути (прямой ``httpx.AsyncClient``) ловит CI-gate
``tools/check_waf_coverage.py``.

Ключевые возможности:

* ``WafPolicy.evaluate(...)`` ДО отправки запроса; на блокировку —
  :class:`WafBypassError` (caller получает в виде exception, audit-event
  пишет policy в свой канал, опционально через optional ``audit_callback``);
* ``CapabilityGate.check(plugin, "net.outbound", host)`` — runtime-gate
  привязывает каждый запрос к декларации плагина;
* explicit pool-limits через :class:`httpx.Limits` (R-V15-14);
* per-host cancel/timeout настраивается на уровне вызова.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from src.backend.core.net.waf import WafBypassError, WafDecision, WafPolicy

__all__ = ("AuditCallback", "OutboundHttpClient")

AuditCallback = Callable[[dict[str, Any]], None]
"""Сигнатура audit-callback'а: принимает event dict, ничего не возвращает."""

CapabilityChecker = Callable[[str, str, str | None], None]
"""Сигнатура capability-gate.check: ``(plugin, capability, scope) -> None``,

raise при denied. Ставится :class:`CapabilityGate` или fake в тестах.
"""


_DEFAULT_LIMITS: httpx.Limits = httpx.Limits(
    max_connections=100, max_keepalive_connections=20, keepalive_expiry=15.0
)
_DEFAULT_TIMEOUT: httpx.Timeout = httpx.Timeout(
    connect=5.0, read=30.0, write=10.0, pool=5.0
)


class OutboundHttpClient:
    """Async HTTP-клиент с обязательной WAF-фильтрацией исходящих запросов.

    Args:
        policy: WAF-policy; если ``None`` — пустая permissive (deny-list
            пустой, payload-limit не задан).
        capability_check: Функция, валидирующая capability запроса
            (обычно ``CapabilityGate.check``). Если ``None`` — capability
            не проверяется (для unit-тестов и core-internal вызовов).
        audit: Опц. callback на каждое решение WAF (granted/denied).
        limits: HTTPX-лимиты пула (см. R-V15-14).
        timeout: HTTPX-timeout по умолчанию.
        verify: TLS-verify режим (``True`` / путь к CA bundle).
        cert: Опц. tuple ``(cert_path, key_path)`` для mTLS на стороне
            клиента (используется К1 mTLS-test).
        plugin: Имя caller'а (плагин/route) для audit-event'а.
            На уровне ядра — строка ``"core"``.
    """

    def __init__(
        self,
        *,
        policy: WafPolicy | None = None,
        capability_check: CapabilityChecker | None = None,
        audit: AuditCallback | None = None,
        limits: httpx.Limits = _DEFAULT_LIMITS,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        verify: bool | str = True,
        cert: tuple[str, str] | None = None,
        plugin: str = "core",
        http2: bool = False,
        base_url: str = "",
    ) -> None:
        self._policy = policy or WafPolicy()
        self._capability_check = capability_check
        self._audit = audit
        self._plugin = plugin
        # S3 К2 W1: ``http2``/``base_url`` для миграции легаси-клиентов
        # (vault_cipher, opa, clickhouse, webhook handler) без потери
        # текущего поведения. Совместимо с httpx[http2] из pyproject.
        client_kwargs: dict[str, Any] = {
            "limits": limits,
            "timeout": timeout,
            "verify": verify,
            "cert": cert,
            "http2": http2,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = httpx.AsyncClient(**client_kwargs)

    async def __aenter__(self) -> OutboundHttpClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Закрыть нижележащий ``httpx.AsyncClient``."""
        await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any | None = None,
        params: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        """Выполнить HTTP-запрос с обязательной WAF-проверкой.

        Raises:
            WafBypassError: WAF заблокировал запрос.
            CapabilityDeniedError: Caller не имеет capability
                ``net.outbound:<host>`` (если ``capability_check`` задан).
        """
        # Sprint 16 Wave 6 (B-3 finale): если в policy задан
        # async_payload_scanner — используем evaluate_async для не-блокирующей
        # ClamAV/HTTP-AV проверки. Без async scanner поведение идентично
        # legacy sync-пути.
        if self._policy.async_payload_scanner is not None:
            decision = await self._policy.evaluate_async(url, payload=content)
        else:
            decision = self._policy.evaluate(url, payload=content)
        self._emit_audit(decision, method, url)
        if not decision.allowed:
            raise WafBypassError(decision)

        if self._capability_check is not None:
            self._capability_check(self._plugin, "net.outbound", decision.host)

        request_kwargs: dict[str, Any] = {"method": method, "url": url}
        if content is not None:
            request_kwargs["content"] = content
        if headers is not None:
            request_kwargs["headers"] = headers
        if json is not None:
            request_kwargs["json"] = json
        if params is not None:
            request_kwargs["params"] = params
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        return await self._client.request(**request_kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Удобная обёртка над ``request("GET", ...)``."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Удобная обёртка над ``request("POST", ...)``."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Удобная обёртка над ``request("PUT", ...)``."""
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Удобная обёртка над ``request("DELETE", ...)``."""
        return await self.request("DELETE", url, **kwargs)

    def _emit_audit(self, decision: WafDecision, method: str, url: str) -> None:
        """Вызвать audit-callback, если задан."""
        if self._audit is None:
            return
        self._audit(
            {
                "event": "waf.evaluate",
                "plugin": self._plugin,
                "method": method,
                "url": url,
                "host": decision.host,
                "allowed": decision.allowed,
                "reason": decision.reason,
            }
        )


SyncOutboundFactory = Callable[..., Awaitable[OutboundHttpClient]]
