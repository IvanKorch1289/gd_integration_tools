"""Sprint 3 (V16.1 P1) — :class:`EmailTriggerProcessor`.

Адаптер процессор для маршрутов, у которых ``from`` — IMAP-источник
(``EmailSource`` или ``ImapMonitor``-совместимый payload).

Принимает на вход распарсенное письмо (``dict``) в ``in_message.body``
и применяет дополнительные фильтры до прохождения дальше по pipeline.
Если письмо не проходит фильтр — exchange останавливается без ошибки
(``exchange.stop(propagate=False)``), не запуская последующие шаги.

Полезен в трёх сценариях:

1. ``EmailSource`` зарегистрирован глобально и имеет широкие фильтры
   (или их нет), а конкретный route хочет более узкое условие.
2. Полученные письма направляются в нескольких маршрутах с разными
   условиями (subject contains "INVOICE" → один route, "ALERT" — другой).
3. ``ImapMonitor`` (legacy) уже обрабатывает входящие; для постепенной
   миграции на ``EmailSource`` хочется иметь один и тот же фильтр-API.
"""

from __future__ import annotations

import re
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("EmailTriggerProcessor",)


def _compile_subject_pattern(pattern: str | None) -> re.Pattern[str] | None:
    """Превращает ``subject_pattern`` в regex-объект.

    Префикс ``re:`` → regex; иначе — literal substring (escape).
    """
    if not pattern:
        return None
    if pattern.startswith("re:"):
        return re.compile(pattern[3:], flags=re.IGNORECASE)
    return re.compile(re.escape(pattern), flags=re.IGNORECASE)


class EmailTriggerProcessor(BaseProcessor):
    """``.email_trigger(...)`` — фильтрует входящее письмо по теме / отправителю.

    Шаг pipeline-а, применимый к route-ам, у которых ``from`` — Email-source.
    Если фильтр не проходит — выполнение останавливается без ошибки.

    Args:
        subject_pattern: Substring или ``re:<regex>``. ``None`` — без фильтра.
        from_filter: Substring для From-заголовка. ``None`` — без фильтра.
        propagate_metadata: Если ``True`` — копирует ``subject``/``from``/
            ``message_id`` из payload в headers (``x-email-subject`` и т. д.)
            для удобства последующих шагов.
        name: Опциональное имя процессора для логов / observability.
    """

    def __init__(
        self,
        *,
        subject_pattern: str | None = None,
        from_filter: str | None = None,
        propagate_metadata: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "email_trigger")
        self._subject_re = _compile_subject_pattern(subject_pattern)
        self._from_filter = from_filter
        self._propagate_metadata = propagate_metadata
        self._subject_pattern_raw = subject_pattern

    def matches(self, payload: Any) -> bool:
        """Проверяет, удовлетворяет ли ``payload`` фильтрам."""
        if not isinstance(payload, dict):
            return False
        subject = str(payload.get("subject", ""))
        sender = str(payload.get("from", ""))
        if self._subject_re is not None and not self._subject_re.search(subject):
            return False
        if (
            self._from_filter is not None
            and self._from_filter.lower() not in sender.lower()
        ):
            return False
        return True

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Применяет фильтры; останавливает exchange при non-match."""
        body = exchange.in_message.body
        if not self.matches(body):
            exchange.stop()
            return
        if self._propagate_metadata and isinstance(body, dict):
            for src_key, hdr_key in (
                ("subject", "x-email-subject"),
                ("from", "x-email-from"),
                ("message_id", "x-email-message-id"),
            ):
                value = body.get(src_key)
                if value:
                    exchange.in_message.set_header(hdr_key, value)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"propagate_metadata": self._propagate_metadata}
        if self._subject_pattern_raw is not None:
            spec["subject_pattern"] = self._subject_pattern_raw
        if self._from_filter is not None:
            spec["from_filter"] = self._from_filter
        return {"email_trigger": spec}
