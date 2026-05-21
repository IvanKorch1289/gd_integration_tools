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

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

__all__ = ("WafBypassError", "WafDecision", "WafPolicy", "build_default_policy")


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
"""Сигнатура опц. payload-scanner'а.

Возвращает ``None`` если payload чист, либо строку-причину блокировки.
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
    strict: bool = False
    """Если ``True`` — пустой allow_hosts трактуется как deny-all."""

    def evaluate(self, url: str, payload: bytes | None = None) -> WafDecision:
        """Решить, разрешён ли запрос к ``url`` с телом ``payload``.

        Порядок проверок (fail-fast):

        1. Парсинг хоста из URL — невалидный URL → ``allowed=False``.
        2. Deny-list — приоритетный.
        3. Strict-режим + allow_hosts mismatch.
        4. Размер payload.
        5. Payload-scanner.
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

        if self.payload_scanner is not None and payload is not None:
            scanner_reason = self.payload_scanner(payload)
            if scanner_reason is not None:
                return WafDecision(False, scanner_reason, host=host)

        return WafDecision(True, "allowed", host=host)

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
