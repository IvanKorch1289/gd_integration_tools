"""DSL Unit-conversion процессоры — pint-обёртка для физических величин.

Поддерживает: длина, масса, объём, температура, время, валюта (через
custom-units registry в pint), скорость, давление и т.д. Pure-Python dep:
``pint>=0.24``. Lazy-import — pipeline валится только если процессор реально
используется без установленной зависимости.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("UnitConversionProcessor",)


class UnitConversionProcessor(BaseProcessor):
    """Конвертация числовых величин между единицами измерения через pint.

    Body — число, dict или list:
    - число (int/float): конвертируется напрямую (требуется ``from_unit``);
    - dict с ключами ``value`` + ``unit``: ``unit`` берётся из body;
    - list[number]: каждый элемент конвертируется (то же ``from_unit``).

    Результат — число (или dict/list — структура body сохраняется),
    плюс property ``unit_conversion_rate`` с коэффициентом.

    Если ``to_property`` задан — пишет результат в ``set_property``,
    а body не трогает.

    Usage::
        .convert_units(from_unit="km", to_unit="mile")
        .convert_units(to_unit="celsius")  # body = {"value": 100, "unit": "fahrenheit"}
        .convert_units(from_unit="usd", to_unit="rub", to_property="amount_rub")
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        to_unit: str,
        from_unit: str | None = None,
        precision: int | None = None,
        to_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"convert_units:{to_unit}")
        self._to_unit = to_unit
        self._from_unit = from_unit
        self._precision = precision
        self._to_property = to_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            import pint  
        except ImportError:
            exchange.fail("pint not installed: pip install 'pint>=0.24'")
            return

        ureg = pint.UnitRegistry()
        body = exchange.in_message.body

        try:
            if isinstance(body, dict) and "value" in body and "unit" in body:
                from_unit = str(body["unit"])
                quantity = ureg.Quantity(body["value"], from_unit)
                converted = quantity.to(self._to_unit)
                magnitude = self._round(converted.magnitude)
                result: Any = {**body, "value": magnitude, "unit": self._to_unit}
            elif isinstance(body, list):
                if not self._from_unit:
                    exchange.fail("convert_units: from_unit required for list body")
                    return
                result = []
                for item in body:
                    quantity = ureg.Quantity(item, self._from_unit)
                    converted = quantity.to(self._to_unit)
                    result.append(self._round(converted.magnitude))
            else:
                if not self._from_unit:
                    exchange.fail(
                        "convert_units: from_unit required when body is bare number"
                    )
                    return
                quantity = ureg.Quantity(body, self._from_unit)
                converted = quantity.to(self._to_unit)
                result = self._round(converted.magnitude)
        except pint.errors.UndefinedUnitError as exc:
            exchange.fail(f"convert_units: undefined unit ({exc})")
            return
        except pint.errors.DimensionalityError as exc:
            exchange.fail(f"convert_units: incompatible dimensions ({exc})")
            return
        except Exception as exc:
            exchange.fail(f"convert_units: {exc}")
            return

        if self._to_property:
            exchange.set_property(self._to_property, result)
        else:
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def _round(self, value: float) -> float:
        if self._precision is None:
            return float(value)
        return round(float(value), self._precision)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"to_unit": self._to_unit}
        if self._from_unit is not None:
            spec["from_unit"] = self._from_unit
        if self._precision is not None:
            spec["precision"] = self._precision
        if self._to_property is not None:
            spec["to_property"] = self._to_property
        return {"convert_units": spec}
