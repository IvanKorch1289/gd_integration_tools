"""DSL-процессор ``ics_calendar`` — iCalendar parse/render через icalendar.

Wave ``[wave:s5/k3-w3-processor-pack-3]``.

Использует библиотеку ``icalendar`` (RFC 5545). Поддерживает 2 операции:
``parse`` (ICS bytes/str → list[dict events]) и ``render`` (list[dict] → ICS bytes).

Контракт DSL::

    .ics_calendar(mode="parse", source="body.ics_text", to="body.events")
    .ics_calendar(mode="render", source="body.events", to="body.ics_text")

Feature flag: ``feature_flags.proc_ics_calendar`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("IcsCalendarProcessor",)


_ALLOWED_MODES = frozenset({"parse", "render"})

# Минимальное множество свойств для round-trip.
_EVENT_PROPS = (
    "uid",
    "summary",
    "description",
    "location",
    "dtstart",
    "dtend",
    "dtstamp",
    "organizer",
)


@processor(
    "ics_calendar",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "source": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["mode"],
    },
    meta={"tier": 1, "category": "documents"},
    tags=("ics", "calendar", "documents"),
)
class IcsCalendarProcessor(BaseProcessor):
    """Parse / render iCalendar через ``icalendar``.

    Args:
        mode: ``parse`` (ICS text/bytes → list[dict events]) или
            ``render`` (list[dict] → ICS bytes).
        source: Где взять исходные данные.
        to: Куда положить результат.
    """

    def __init__(
        self,
        mode: str,
        *,
        source: str = "body",
        to: str = "body.ics_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ics_calendar:{mode}")
        if mode not in _ALLOWED_MODES:
            raise ValueError(
                f"ics_calendar: mode must be 'parse'|'render', got {mode!r}"
            )
        self._mode = mode
        self._source = source
        self._target = to

    def _resolve_source(self, exchange: "Exchange[Any]") -> Any:
        body = exchange.in_message.body
        if self._source == "body":
            return body
        if self._source.startswith("body."):
            return body.get(self._source[len("body.") :]) if isinstance(body, dict) else None
        if self._source.startswith("properties."):
            return exchange.properties.get(self._source[len("properties.") :])
        return None

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  # type: ignore[assignment]
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    def _parse(self, raw: Any) -> list[dict[str, Any]]:
        from icalendar import Calendar  # type: ignore[import-not-found]

        if isinstance(raw, str):
            cal = Calendar.from_ical(raw)
        elif isinstance(raw, (bytes, bytearray)):
            cal = Calendar.from_ical(bytes(raw))
        else:
            raise ValueError("ics_calendar parse: source must be str or bytes")
        events: list[dict[str, Any]] = []
        for component in cal.walk():
            if component.name == "VEVENT":
                events.append(
                    {
                        prop: str(component.get(prop.upper()))
                        for prop in _EVENT_PROPS
                        if component.get(prop.upper())
                    }
                )
        return events

    def _render(self, events: list[dict[str, Any]]) -> bytes:
        from icalendar import Calendar, Event  # type: ignore[import-not-found]

        cal = Calendar()
        cal.add("prodid", "-//gd-integration-tools//DSL//RU")
        cal.add("version", "2.0")
        for ev in events:
            event = Event()
            for prop, value in ev.items():
                event.add(prop, value)
            cal.add_component(event)
        return cal.to_ical()

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_ics_calendar:
                exchange.set_property("ics_calendar_status", "skipped")
                return
        except Exception:  # noqa: BLE001
            pass

        src_value = self._resolve_source(exchange)
        try:
            if self._mode == "parse":
                result: Any = self._parse(src_value)
            else:  # render
                if not isinstance(src_value, list):
                    exchange.fail("ics_calendar render: source must be list[dict]")
                    return
                result = self._render(src_value)
        except ImportError as exc:
            exchange.fail(f"ics_calendar: icalendar not available: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"ics_calendar error: {exc}")
            return

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"mode": self._mode}
        if self._source != "body":
            spec["source"] = self._source
        if self._target != "body.ics_result":
            spec["to"] = self._target
        return {"ics_calendar": spec}
