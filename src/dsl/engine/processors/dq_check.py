"""Data Quality процессор для DSL pipeline."""

from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("DQCheckProcessor",)


class DQCheckProcessor(BaseProcessor):
    """Проверяет данные по правилам Data Quality.

    Usage в DSL::

        .dq_check(rules=[
            DQRule(name="amount_not_null", field="amount", check="not_null"),
            DQRule(name="amount_range", field="amount", check="range", params={"min": 0}),
        ])
    """

    def __init__(
        self,
        rules: list[Any] | None = None,
        dataset: str = "default",
        fail_on_violation: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dq_check")
        self._rules = rules or []
        self._dataset = dataset
        self._fail_on_violation = fail_on_violation

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.services.ops.data_quality import get_dq_monitor

        monitor = get_dq_monitor()
        for rule in self._rules:
            monitor.add_rule(rule)

        body = exchange.in_message.body
        result = await monitor.check(body, dataset=self._dataset)
        exchange.set_property("dq_result", result)

        if self._fail_on_violation and not result.get("is_clean", True):
            violations = result.get("violations", [])
            exchange.fail(f"DQ violations: {len(violations)}")
