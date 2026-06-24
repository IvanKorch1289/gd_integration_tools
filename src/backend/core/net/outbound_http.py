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

__all__ = ("CORRELATION_ID_HEADER", "AuditCallback", "OutboundHttpClient")

# Sprint 17 K3 W3 (D12) — стандартный header для cross-service correlation.
# Значение берётся из ``correlation_id_var`` ContextVar; явный header
# в kwargs caller'а имеет приоритет.
CORRELATION_ID_HEADER = "X-Correlation-ID"

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

        # S17 K3 W3 (D12): inject X-Correlation-ID из ContextVar в outgoing
        # headers. Caller-override (явный header) имеет приоритет.
        effective_headers = self._inject_correlation_id(headers)

        request_kwargs: dict[str, Any] = {"method": method, "url": url}
        if content is not None:
            request_kwargs["content"] = content
        if effective_headers is not None:
            request_kwargs["headers"] = effective_headers
        if json is not None:
            request_kwargs["json"] = json
        if params is not None:
            request_kwargs["params"] = params
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        return await self._client.request(**request_kwargs)

    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        """Streaming HTTP-запрос с обязательной WAF-проверкой (S36-W7).

        Используется для SSE / chunked download / long-poll сценариев,
        где response_body заранее неизвестен. WAF проверяет только URL
        (payload пустой) + headers, до открытия stream.

        Usage::

            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes():
                    ...

        Args:
            method: HTTP method (``"GET"``, ``"POST"``).
            url: Полный URL.
            headers: Опц. outgoing headers.
            params: Опц. query params.
            timeout: Per-request timeout.

        Returns:
            :class:`httpx.Response` — async context manager (НЕ awaitable).
            Caller обязан использовать ``async with``.

        Raises:
            WafBypassError: WAF заблокировал запрос.
            CapabilityDeniedError: Caller не имеет capability
                ``net.outbound:<host>`` (если ``capability_check`` задан).
        """
        # WAF-evaluate до открытия stream (без payload).
        decision = self._policy.evaluate(url, payload=None)
        self._emit_audit(decision, method, url)
        if not decision.allowed:
            raise WafBypassError(decision)

        if self._capability_check is not None:
            self._capability_check(self._plugin, "net.outbound", decision.host)

        effective_headers = self._inject_correlation_id(headers)

        request_kwargs: dict[str, Any] = {"method": method, "url": url}
        if effective_headers is not None:
            request_kwargs["headers"] = effective_headers
        if params is not None:
            request_kwargs["params"] = params
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        return self._client.stream(**request_kwargs)

    @staticmethod
    def _inject_correlation_id(
        headers: Mapping[str, str] | None,
    ) -> Mapping[str, str] | None:
        """Дополнить headers ``X-Correlation-ID`` из текущего ContextVar.

        S17 K3 W3 (D12). Если caller передал явный ``X-Correlation-ID``
        (или одну из его case-вариаций), значение не перетирается. Если
        ContextVar пуст — header не добавляется (избегаем пустых строк).

        S27: Использует CorrelationIdProvider protocol из core/interfaces/observability
        (реализация — ``get_correlation_id`` из ``infrastructure.observability.correlation``).
        При недоступности — silent pass.
        """
        try:
            from src.backend.core.interfaces.observability import CorrelationIdProvider

            def _get_cid() -> str | None:
                from src.backend.core.di.providers.infrastructure_facade import (
                    get_correlation_module as _get_corr_mod_fn,
                )
                _correlation = _get_corr_mod_fn()

                return _correlation.get_correlation_id()

            provider: CorrelationIdProvider = _get_cid
            cid = provider()
        except Exception:
            return headers
        if not cid:
            return headers
        existing = dict(headers or {})
        for key in existing:
            if key.lower() == CORRELATION_ID_HEADER.lower():
                return existing
        existing[CORRELATION_ID_HEADER] = cid
        return existing

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
        """Вызвать audit-callback, если задан.

        S109 W1: dual-emit — callback для backward compat +
        :func:`emit_waf_evaluation` из ``core.audit.facade`` (canonical
        Path A helper) для unified audit service. Callback-only путь
        сохранён для callers, которым нужен sync ``dict`` payload
        (legacy testkit).
        """
        if self._audit is not None:
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
        # S109 W1: dual-emit через unified audit service.
        # Lazy import для избежания circular dep (facade → services/audit).
        # ``emit_waf_evaluation`` возвращает coroutine — fire-and-forget через
        # ``asyncio.create_task`` если event loop активен, иначе sync close.
        import asyncio

        from src.backend.core.audit.facade import emit_waf_evaluation

        try:
            coro = emit_waf_evaluation(
                decision=decision, plugin=self._plugin, method=method, url=url
            )
            if asyncio.iscoroutine(coro):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(coro)
                except RuntimeError:
                    pass  # no running loop → drop coroutine (sync context)
        except Exception as _:
            pass  # never raise from audit emission


SyncOutboundFactory = Callable[..., Awaitable[OutboundHttpClient]]
