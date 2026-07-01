"""DSL ICS Calendar процессоры — парсинг и сборка iCalendar (RFC 5545).

Pure-Python dep: ``icalendar>=5.0``. Lazy-import.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("IcsCalendarProcessor",)


class IcsCalendarProcessor(BaseProcessor):
    """Парсит/строит iCalendar (RFC 5545) через библиотеку ``icalendar``.

    Режимы:
    - ``mode="parse"`` (default): body=str|bytes (ICS) → list[dict] событий
      с полями ``uid, summary, description, location, start, end, organizer,
      attendees, status, rrule, categories``;
    - ``mode="build"``: body=list[dict] (или один dict) → bytes (ICS).

    Usage::
        .parse_ics()                       # body=ics_text → list событий
        .parse_ics(mode="parse", only_first=True)
        .parse_ics(mode="build", prodid="-//gd_integration_tools//RU")
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True

    _DT_FIELDS = ("start", "end", "dtstart", "dtend", "created", "last_modified")

    def __init__(
        self,
        *,
        mode: str = "parse",
        only_first: bool = False,
        prodid: str = "-//gd_integration_tools//RU",
        name: str | None = None,
    ) -> None:
        if mode not in {"parse", "build"}:
            raise ValueError(f"Unsupported ics mode: {mode}")
        super().__init__(name=name or f"parse_ics:{mode}")
        self._mode = mode
        self._only_first = only_first
        self._prodid = prodid

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Парсит ICS-календарь в список событий или строит ICS из dict'ов.

        Mode ``parse``: десериализует ICS (str/bytes) через ``icalendar``,
        извлекает VEVENT-компоненты как dict. При ``only_first`` возвращает
        только первый.

        Mode ``build``: строит ICS-календарь из dict/list[dict], возвращает
        ``bytes``.

        Args:
            exchange: Текущий exchange; body — ICS-строка (parse) или
                dict/list[dict] (build). Результат — в ``out_message``.
            context: Контекст выполнения маршрута.
        """
        try:
            from icalendar import Calendar, Event
        except ImportError:
            exchange.fail("icalendar not installed: pip install 'icalendar>=5.0'")
            return

        body = exchange.in_message.body

        try:
            if self._mode == "parse":
                if isinstance(body, str):
                    raw = body.encode("utf-8")
                elif isinstance(body, bytes):
                    raw = body
                else:
                    exchange.fail("parse_ics: body must be str or bytes")
                    return

                cal = Calendar.from_ical(raw)
                events: list[dict[str, Any]] = []
                for component in cal.walk("VEVENT"):
                    events.append(self._event_to_dict(component))
                    if self._only_first:
                        break
                result: Any = events[0] if (self._only_first and events) else events
                exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

            else:  # build
                items = body if isinstance(body, list) else [body]
                if not isinstance(items, list) or not all(
                    isinstance(it, dict) for it in items
                ):
                    exchange.fail("build_ics: body must be dict or list[dict]")
                    return

                cal = Calendar()
                cal.add("prodid", self._prodid)
                cal.add("version", "2.0")
                for item in items:
                    event = Event()
                    for key, value in item.items():
                        if value is None:
                            continue
                        event.add(key.lower(), value)
                    cal.add_component(event)
                exchange.set_out(
                    body=bytes(cal.to_ical()), headers=dict(exchange.in_message.headers)
                )
        except Exception as exc:
            exchange.fail(f"parse_ics: {exc}")

    @staticmethod
    def _event_to_dict(event: Any) -> dict[str, Any]:
        def _val(name: str) -> Any:
            raw = event.get(name)
            if raw is None:
                return None
            if hasattr(raw, "dt"):
                dt = raw.dt
                if isinstance(dt, (datetime, date)):
                    return dt.isoformat()
                return str(dt)
            return str(raw)

        attendees_raw = event.get("attendee", [])
        if not isinstance(attendees_raw, list):
            attendees_raw = [attendees_raw]
        attendees = [str(a) for a in attendees_raw]

        return {
            "uid": _val("uid"),
            "summary": _val("summary"),
            "description": _val("description"),
            "location": _val("location"),
            "start": _val("dtstart"),
            "end": _val("dtend"),
            "organizer": _val("organizer"),
            "attendees": attendees,
            "status": _val("status"),
            "rrule": _val("rrule"),
            "categories": _val("categories"),
            "created": _val("created"),
            "last_modified": _val("last-modified"),
        }

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._mode != "parse":
            spec["mode"] = self._mode
        if self._only_first:
            spec["only_first"] = True
        if self._prodid != "-//gd_integration_tools//RU":
            spec["prodid"] = self._prodid
        return {"parse_ics": spec}
