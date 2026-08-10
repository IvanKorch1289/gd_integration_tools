"""S65 W2 — TemplateRenderProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class TemplateRenderProcessor(BaseProcessor):
    """Рендеринг Jinja2 шаблонов.

    Body: dict (переменные). template: str (Jinja2 template).
    Результат: str (rendered text).
    """

    required_capability: ClassVar[str | None] = "rpa.template.render"
    audit_event: str | None = "rpa.template.render"

    def __init__(self, template: str, *, name: str | None = None) -> None:
        super().__init__(name=name or "render_template")
        self._template = template

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        if not await self.auth_check(exchange, action="read"):
            return
        try:
            from jinja2.sandbox import (
                SandboxedEnvironment,  # noqa: F401 — availability probe
            )
        except ImportError:
            exchange.fail("jinja2 not installed: pip install Jinja2")
            return
        body = exchange.in_message.body
        variables = body if isinstance(body, dict) else {"body": body}
        try:
            # ponytail: use SandboxedEnvironment to prevent SSTI
            env = SandboxedEnvironment()
            result = env.from_string(self._template).render(**variables)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
            # W34: observability trace — все RPA processors должны оставлять
            # хотя бы один set_property call (test contract).
            exchange.set_property("template_rendered", True)
        except Exception as exc:
            exchange.fail(f"Template render failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        return {"render_template": {"template": self._template}}
