"""WAF фасад для исходящего HTTP-трафика (V15 R-V15-5, S1 DoD).

Перед каждым исходящим вызовом :class:`OutboundHttpClient` спрашивает
:class:`WafPolicy.evaluate(...)` — должен ли запрос пройти. Policy
агрегирует:

* allow-host / deny-host списки;
* per-host rate-limit (опционально);
* payload-scan (опциональный hook на тело запроса).

Решение представлено :class:`WafDecision` — pure-data объект, который
:class:`OutboundHttpClient` интерпретирует. На ``decision.allowed=False``
поднимается :class:`WafBypassError` с человекочитаемой причиной для
audit-event'а.

Все ``:external`` capabilities обязаны проходить через эту pipeline
(см. ADR R-V15-5). Нарушение ловит ``tools/check_waf_coverage.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

__all__ = (
    "AsyncPayloadScanner",
    "PayloadScanner",
    "WafBypassError",
    "WafDecision",
    "WafPolicy",
    "build_default_policy",
)


@dataclass(frozen=True, slots=True)
class WafDecision:
    """Результат проверки запроса WAF-фасадом.

    Attributes:
        allowed: ``True`` — запрос разрешён, ``False`` — заблокирован.
        reason: Человекочитаемое объяснение (для audit-log/DLQ).
        host: Хост запроса (для метки Prometheus).
    """

    allowed: bool
    reason: str
    host: str


class WafBypassError(RuntimeError):
    """Исходящий вызов заблокирован WAF-policy.

    Attributes:
        decision: Полное решение (``WafDecision``) для audit-event'а.
    """

    def __init__(self, decision: WafDecision) -> None:
        self.decision = decision
        super().__init__(
            f"WAF blocked outbound request to {decision.host!r}: {decision.reason}"
        )


PayloadScanner = Callable[[bytes | None], str | None]
"""Сигнатура опц. **синхронного** payload-scanner'а.

Возвращает ``None`` если payload чист, либо строку-причину блокировки.
Используется ``WafPolicy.evaluate(...)`` (sync). Для I/O-bound сканеров
(ClamAV/HTTP-AV) предпочтительнее :data:`AsyncPayloadScanner` +
``WafPolicy.evaluate_async(...)``.
"""

AsyncPayloadScanner = Callable[[bytes | None], Awaitable[str | None]]
"""Async-сигнатура payload-scanner'а (Sprint 16 Wave 6, B-3 finale).

Используется ``WafPolicy.evaluate_async(...)`` — не блокирует event-loop
при общении с ClamAV/HTTP-AV. Возвращает ``None`` если payload чист, либо
строку-причину блокировки (например, имя сигнатуры).
"""


@dataclass(slots=True)
class WafPolicy:
    """Декларативная WAF-policy.

    Attributes:
        allow_hosts: Whitelist хостов (точный match по host из URL).
            Пустой — allow-all (modulo deny_hosts/scanner).
        deny_hosts: Blacklist хостов; имеет приоритет над allow.
        max_payload_bytes: Лимит размера тела запроса (None — без лимита).
        payload_scanner: Опц. функция, проверяющая тело (антивирус,
            sql-injection-detector и т.д.).

    Default-deny при пустом ``allow_hosts`` НЕ применяется — это
    осознанное решение (мы не хотим заблокировать всё ядро при пустом
    конфиге). Default-deny включается через :func:`build_default_policy`
    с явным ``strict=True``.
    """

    allow_hosts: frozenset[str] = field(default_factory=frozenset)
    deny_hosts: frozenset[str] = field(default_factory=frozenset)
    max_payload_bytes: int | None = None
    payload_scanner: PayloadScanner | None = None
    async_payload_scanner: AsyncPayloadScanner | None = None
    """Sprint 16 Wave 6 (B-3): async payload-scanner для I/O-bound
    проверок (ClamAV INSTREAM/HTTP-AV). Используется только в
    :meth:`evaluate_async`; не вызывается из sync :meth:`evaluate`."""

    strict: bool = False
    """Если ``True`` — пустой allow_hosts трактуется как deny-all."""

    def evaluate(self, url: str, payload: bytes | None = None) -> WafDecision:
        """Решить, разрешён ли запрос к ``url`` с телом ``payload``.

        Порядок проверок (fail-fast):

        1. Парсинг хоста из URL — невалидный URL → ``allowed=False``.
        2. Deny-list — приоритетный.
        3. Strict-режим + allow_hosts mismatch.
        4. Размер payload.
        5. Sync payload-scanner.

        Async payload-scanner НЕ вызывается из sync-пути — используйте
        :meth:`evaluate_async` для I/O-bound сканеров (ClamAV/HTTP-AV).
        """
        pre = self._evaluate_pre_payload(url, payload)
        if pre is not None and not pre.allowed:
            return pre
        # pre is None в edge-case'е (нет хоста); обработали выше
        assert pre is not None
        host = pre.host

        if self.payload_scanner is not None and payload is not None:
            scanner_reason = self.payload_scanner(payload)
            if scanner_reason is not None:
                return WafDecision(False, scanner_reason, host=host)

        return WafDecision(True, "allowed", host=host)

    async def evaluate_async(
        self, url: str, payload: bytes | None = None
    ) -> WafDecision:
        """Async-версия :meth:`evaluate` с поддержкой async payload-scanner.

        Порядок проверок идентичен sync-пути, но дополнительно после
        sync-scanner'а вызывается ``async_payload_scanner(payload)``
        через ``await``. Это критично для I/O-bound сканеров (ClamAV
        INSTREAM/HTTP-AV): event-loop не блокируется на время
        сканирования. Sprint 16 Wave 6 (B-3 finale).
        """
        pre = self._evaluate_pre_payload(url, payload)
        if pre is not None and not pre.allowed:
            return pre
        assert pre is not None
        host = pre.host

        if self.payload_scanner is not None and payload is not None:
            scanner_reason = self.payload_scanner(payload)
            if scanner_reason is not None:
                return WafDecision(False, scanner_reason, host=host)

        if self.async_payload_scanner is not None and payload is not None:
            async_reason = await self.async_payload_scanner(payload)
            if async_reason is not None:
                return WafDecision(False, async_reason, host=host)

        return WafDecision(True, "allowed", host=host)

    def _evaluate_pre_payload(
        self, url: str, payload: bytes | None
    ) -> WafDecision | None:
        """Общая часть sync/async-проверок до payload-scanner'а.

        Возвращает финальный :class:`WafDecision` если запрос отвергнут
        (host invalid / deny-list / strict-mismatch / size-limit), либо
        :class:`WafDecision` с ``allowed=True`` для передачи host'а
        в payload-scanner step. None никогда не возвращается.
        """
        host = self._extract_host(url)
        if host is None:
            return WafDecision(False, "invalid URL or missing host", host="")

        if host in self.deny_hosts:
            return WafDecision(False, "host in deny_hosts", host=host)

        if self.strict and self.allow_hosts and host not in self.allow_hosts:
            return WafDecision(False, "host not in allow_hosts (strict)", host=host)

        if (
            self.max_payload_bytes is not None
            and payload is not None
            and len(payload) > self.max_payload_bytes
        ):
            return WafDecision(
                False,
                f"payload {len(payload)}B exceeds limit {self.max_payload_bytes}B",
                host=host,
            )

        return WafDecision(True, "ok", host=host)

    @staticmethod
    def _extract_host(url: str) -> str | None:
        """Возвращает host или ``None`` при невалидном URL."""
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        if not parsed.hostname:
            return None
        return parsed.hostname.lower()


def build_default_policy(
    *,
    allow_hosts: frozenset[str] | None = None,
    deny_hosts: frozenset[str] | None = None,
    strict: bool = False,
    max_payload_bytes: int | None = 10 * 1024 * 1024,
) -> WafPolicy:
    """Возвращает дефолтную policy с разумными лимитами.

    По умолчанию: payload limit 10 MiB, strict=False (allow-list не
    обязателен на dev-профиле). В prod рекомендуется ``strict=True``
    с явным ``allow_hosts`` через ADR.
    """
    return WafPolicy(
        allow_hosts=allow_hosts or frozenset(),
        deny_hosts=deny_hosts or frozenset(),
        max_payload_bytes=max_payload_bytes,
        strict=strict,
    )
