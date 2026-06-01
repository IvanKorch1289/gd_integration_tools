"""DSL-процессор ``unit_conversion`` — конвертация единиц через pint.

Wave ``[wave:s5/k3-w3-processor-pack-3]``.

Использует библиотеку ``pint`` (lazy). Конвертирует физические/инженерные
величины между единицами (метры → футы, килограммы → фунты, бар → паскали).

Контракт DSL::

    .unit_conversion(value=100, from_unit="meter", to_unit="foot", to="body.feet")

YAML::

    - unit_conversion:
        from: body.distance_m
        from_unit: meter
        to_unit: foot
        to: body.distance_ft

Feature flag: ``feature_flags.proc_unit_conversion`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("UnitConversionProcessor",)


@processor(
    "unit_conversion",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "value": {"type": ["number", "string", "null"]},
            "from_value_source": {"type": ["string", "null"]},
            "from_unit": {"type": "string"},
            "to_unit": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["from_unit", "to_unit"],
    },
    meta={"tier": 1, "category": "transform"},
    tags=("units", "pint", "convert"),
)
class UnitConversionProcessor(BaseProcessor):
    """Конвертация единиц через pint.

    Args:
        from_unit: Единица источника (``meter``, ``kg``, ``celsius``, ``bar``).
        to_unit: Единица назначения.
        value: Числовое значение (если задано напрямую, не из exchange).
        from_value_source: ``body.<field>`` / ``properties.<name>`` —
            откуда взять значение (если ``value=None``).
        to: Куда положить результат.
    """

    def __init__(
        self,
        from_unit: str,
        to_unit: str,
        *,
        value: float | str | None = None,
        from_value_source: str | None = None,
        to: str = "body.converted",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"unit_conversion:{from_unit}→{to_unit}")
        if not from_unit:
            raise ValueError("unit_conversion: from_unit must be non-empty")
        if not to_unit:
            raise ValueError("unit_conversion: to_unit must be non-empty")
        self._from_unit = from_unit
        self._to_unit = to_unit
        self._value = value
        self._from_value_source = from_value_source
        self._target = to

    def _resolve_value(self, exchange: "Exchange[Any]") -> Any:
        if self._value is not None:
            return self._value
        if not self._from_value_source:
            return exchange.in_message.body
        body = exchange.in_message.body
        if self._from_value_source.startswith("body."):
            return (
                body.get(self._from_value_source[len("body.") :])
                if isinstance(body, dict)
                else None
            )
        if self._from_value_source.startswith("properties."):
            return exchange.properties.get(
                self._from_value_source[len("properties.") :]
            )
        return None

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_unit_conversion:
                exchange.set_property("unit_conversion_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        try:
            import pint
        except ImportError as exc:
            exchange.fail(f"unit_conversion: pint not available: {exc}")
            return

        raw = self._resolve_value(exchange)
        try:
            ureg = pint.UnitRegistry()
            quantity = ureg.Quantity(float(raw), self._from_unit)
            converted = quantity.to(self._to_unit)
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"unit_conversion error: {exc}")
            return

        # Результат — magnitude (число), units можно положить рядом.
        self._apply_target(exchange, float(converted.magnitude))

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"from_unit": self._from_unit, "to_unit": self._to_unit}
        if self._value is not None:
            spec["value"] = self._value
        if self._from_value_source:
            spec["from_value_source"] = self._from_value_source
        if self._target != "body.converted":
            spec["to"] = self._target
        return {"unit_conversion": spec}
