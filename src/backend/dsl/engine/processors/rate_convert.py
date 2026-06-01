"""DSL-процессор ``rate_convert`` — конвертация валют через external HTTP.

Wave ``[wave:s5/k3-w4-processor-pack-4]``.

Обращается к внешнему provider курсов валют (по умолчанию — open.er-api.com)
через :class:`OutboundHttpClient` (R-V15-5: WAF-обязателен для всех external).

Контракт DSL::

    .rate_convert(
        amount=100,
        from_currency="USD",
        to_currency="EUR",
        provider="er-api",
        to="body.eur",
    )

YAML::

    - rate_convert:
        amount: 100
        from_currency: USD
        to_currency: EUR
        to: body.eur

Feature flag: ``feature_flags.proc_rate_convert`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("RateConvertProcessor",)


_PROVIDERS = {
    "er-api": "https://open.er-api.com/v6/latest/{base}",
    "exchangerate-host": "https://api.exchangerate.host/latest?base={base}",
}


@processor(
    "rate_convert",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "amount": {"type": ["number", "null"]},
            "amount_source": {"type": ["string", "null"]},
            "from_currency": {"type": "string"},
            "to_currency": {"type": "string"},
            "provider": {"type": "string", "enum": sorted(_PROVIDERS)},
            "to": {"type": "string"},
        },
        "required": ["from_currency", "to_currency"],
    },
    capabilities=("net.outbound.open.er-api.com:external",),
    meta={"tier": 1, "category": "finance"},
    tags=("rates", "currency", "fx"),
)
class RateConvertProcessor(BaseProcessor):
    """Конвертация суммы между валютами через провайдер курсов.

    Args:
        from_currency: ISO-код исходной валюты (``USD``, ``EUR``, ``RUB``).
        to_currency: ISO-код валюты назначения.
        amount: Сумма (если задана напрямую).
        amount_source: ``body.<field>`` / ``properties.<name>`` — откуда
            взять сумму (если ``amount=None``).
        provider: ``er-api`` (default) / ``exchangerate-host``.
        to: Куда положить результат (``body.<field>`` / ``properties.<name>``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        from_currency: str,
        to_currency: str,
        *,
        amount: float | None = None,
        amount_source: str | None = None,
        provider: str = "er-api",
        to: str = "body.converted_amount",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"rate_convert:{from_currency}→{to_currency}")
        if not from_currency:
            raise ValueError("rate_convert: from_currency must be non-empty")
        if not to_currency:
            raise ValueError("rate_convert: to_currency must be non-empty")
        if provider not in _PROVIDERS:
            raise ValueError(
                f"rate_convert: provider must be one of {sorted(_PROVIDERS)}, "
                f"got {provider!r}"
            )
        self._from = from_currency.upper()
        self._to = to_currency.upper()
        self._amount = amount
        self._amount_source = amount_source
        self._provider = provider
        self._target = to

    def _resolve_amount(self, exchange: "Exchange[Any]") -> float | None:
        if self._amount is not None:
            return float(self._amount)
        if not self._amount_source:
            body = exchange.in_message.body
            if isinstance(body, (int, float)):
                return float(body)
            return None
        body = exchange.in_message.body
        if self._amount_source.startswith("body."):
            field = self._amount_source[len("body.") :]
            value = body.get(field) if isinstance(body, dict) else None
        elif self._amount_source.startswith("properties."):
            field = self._amount_source[len("properties.") :]
            value = exchange.properties.get(field)
        else:
            value = None
        return float(value) if value is not None else None

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

    async def _fetch_rate(self) -> float | None:
        from src.backend.core.net.outbound_http import OutboundHttpClient

        url = _PROVIDERS[self._provider].format(base=self._from)
        async with OutboundHttpClient(plugin="core.rate_convert") as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        # er-api: data["rates"][to]; exchangerate-host: data["rates"][to]
        rates = data.get("rates") or data.get("conversion_rates") or {}
        rate_value = rates.get(self._to)
        return float(rate_value) if rate_value is not None else None

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_rate_convert:
                exchange.set_property("rate_convert_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        amount = self._resolve_amount(exchange)
        if amount is None:
            exchange.fail("rate_convert: amount not provided / not numeric")
            return

        try:
            rate = await self._fetch_rate()
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"rate_convert provider error: {exc}")
            return

        if rate is None:
            exchange.fail(f"rate_convert: no rate {self._from}→{self._to}")
            return

        converted = amount * rate
        self._apply_target(
            exchange,
            {"amount": converted, "from": self._from, "to": self._to, "rate": rate},
        )

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"from_currency": self._from, "to_currency": self._to}
        if self._amount is not None:
            spec["amount"] = self._amount
        if self._amount_source:
            spec["amount_source"] = self._amount_source
        if self._provider != "er-api":
            spec["provider"] = self._provider
        if self._target != "body.converted_amount":
            spec["to"] = self._target
        return {"rate_convert": spec}
