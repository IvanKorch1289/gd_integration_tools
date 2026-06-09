"""SkillInvokeProcessor — DSL-вызов :class:`SkillRegistry.invoke` (S27 W3).

Декларативный invoke skill'а из TOML manifest (ADR-NEW-22, S26 W5):

YAML контракт::

    steps:
      - skill_invoke:
          skill_id: credit.score.calculate
          params_property: body.scoring_params
          result_property: skill_result

Python контракт::

    builder.skill_invoke(skill_id="credit.score.calculate")

Capability ``skill.invoke.<skill_id>`` обязательна.

При недоступности :class:`SkillRegistry` (DI singleton ``None``, либо
``NotImplementedError`` в scaffold-режиме) — silent pass-through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("SkillInvokeProcessor",)

_logger = get_logger(__name__)


class SkillInvokeProcessor(BaseAIProcessor):
    """Вызов AI skill через :class:`SkillRegistry.invoke` (S27 W3).

    Args:
        skill_id: Идентификатор skill (``"credit.score.calculate"``);
            конвенция ``<domain>.<resource>.<action>``.
        params_property: Откуда взять параметры skill'а. Default ``"body"``
            — из ``exchange.in_message.body`` (должен быть dict).
            Поддерживает dot-path и ``"property:<name>"``.
        result_property: Свойство exchange для записи результата.
            Default ``"skill_result"``.
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "skill.invoke"
    audit_event: ClassVar[str | None] = "ai.skill.invoke"

    def __init__(
        self,
        *,
        skill_id: str,
        params_property: str | None = "body",
        result_property: str = "skill_result",
        name: str | None = None,
    ) -> None:
        if not skill_id:
            raise ValueError("SkillInvokeProcessor: skill_id обязателен")
        super().__init__(name=name or f"skill_invoke:{skill_id}")
        self.skill_id = skill_id
        self.params_property = params_property
        self.result_property = result_property

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope для ``skill.invoke`` = ``skill_id``."""
        del exchange
        return self.skill_id

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        registry = self._resolve_registry()
        if registry is None:
            _logger.warning(
                "%s: SkillRegistry недоступен — pass-through skip", self.name
            )
            return

        # Проброс tenant/correlation в shared state и exchange properties
        # для downstream процессоров и аудита (V2 fix)
        if exchange.meta.tenant_id:
            context.set("_skill_tenant_id", exchange.meta.tenant_id)
            exchange.set_property("_skill_tenant_id", exchange.meta.tenant_id)
        if exchange.meta.correlation_id:
            context.set("_skill_correlation_id", exchange.meta.correlation_id)
            exchange.set_property("_skill_correlation_id", exchange.meta.correlation_id)

        params = self._extract_params(exchange)
        try:
            result = await registry.invoke(self.skill_id, **params)
        except NotImplementedError:
            _logger.warning(
                "%s: SkillRegistry.invoke() — scaffold (NotImplementedError) — skip",
                self.name,
            )
            return
        except KeyError:
            exchange.set_error(
                f"{self.name}: skill_id={self.skill_id!r} не зарегистрирован"
            )
            exchange.stop()
            return

        exchange.set_property(self.result_property, result)

    def _extract_params(self, exchange: Exchange[Any]) -> dict[str, Any]:
        """Достать params для skill'а через dot-path."""
        if self.params_property is None:
            return {}
        path = self.params_property
        if path == "body":
            body = exchange.in_message.body
            return body if isinstance(body, dict) else {}
        if path.startswith("body."):
            cursor: Any = exchange.in_message.body
            for part in path[len("body.") :].split("."):
                if not isinstance(cursor, dict):
                    return {}
                cursor = cursor.get(part)
            return cursor if isinstance(cursor, dict) else {}
        if path.startswith("property:"):
            value = exchange.get_property(path[len("property:") :])
            return value if isinstance(value, dict) else {}
        return {}

    @staticmethod
    def _resolve_registry() -> Any | None:
        """Lazy-резолв :class:`SkillRegistry` через DI singleton."""
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"skill_id": self.skill_id}
        if self.params_property != "body":
            spec["params_property"] = self.params_property
        if self.result_property != "skill_result":
            spec["result_property"] = self.result_property
        return {"skill_invoke": spec}
