"""BindSkillProcessor — привязка skill pack к агенту/workflow step (S29 W2).

План Agent DSL + Memory Orchestration Layer, Phase 6.

BindSkillProcessor декоративно привязывает skill pack (набор skill references)
к агенту или workflow step. Используется когда нужно динамически расширить
набор available skills без изменения AgentSpec.

YAML::

    steps:
      - bind_skill:
          pack_id: "credit_skills"
          target_agent: "credit_advisor"
          output_key: "bound_skills"

Python::

    builder.bind_skill(pack_id="credit_skills", target_agent="credit_advisor")

См. также
---------
* :class:`SkillRegistry` — :mod:`core.ai.skill_registry`.
* :class:`SkillPackSpec` — :mod:`core.ai.skill_pack`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("BindSkillProcessor",)

_logger = get_logger("workflow.processors.bind_skill")


class BindSkillProcessor(BaseAIProcessor):
    """Привязка skill pack к агенту/workflow step (S29 W2).

    Позволяет динамически добавить набор skills к агенту без изменения
    AgentSpec в registry.

    Args:
        pack_id: Идентификатор skill pack (``"credit_skills"``).
        target_agent: Опц. agent_id, к которому привязать pack.
            Если ``None`` — pack привязывается к текущему step.
        output_key: Опц. ключ для сохранения bound skills в exchange.
        name: Имя процессора.
    """

    feature_flag_name: ClassVar[str | None] = "ai_bind_skill_enabled"
    required_capability: ClassVar[str | None] = "skill.invoke"
    audit_event: ClassVar[str | None] = "ai.bind_skill"

    def __init__(
        self,
        *,
        pack_id: str,
        target_agent: str | None = None,
        output_key: str | None = None,
        name: str | None = None,
    ) -> None:
        """Инициализация BindSkillProcessor.

        Args:
            pack_id: Идентификатор skill pack.
            target_agent: Опц. agent_id для привязки.
            output_key: Опц. ключ результата.
            name: Имя процессора.
        """
        super().__init__(name=name)
        self._pack_id = pack_id
        self._target_agent = target_agent
        self._output_key = output_key

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполнить привязку skill pack.

        Lookup skill pack через SkillRegistry, затем привязывает
        skills к target_agent или текущему workflow step context.
        """
        # Get SkillRegistry from context state (best-effort)
        skill_registry = context.get("skill_registry", None)
        if skill_registry is None:
            _logger.warning(
                "BindSkillProcessor[%s]: skill_registry not in context — no-op",
                self.name,
            )
            return

        # Get skill pack
        pack = await self._resolve_pack(skill_registry)
        if pack is None:
            _logger.warning(
                "BindSkillProcessor[%s]: pack_id=%r not found — no-op",
                self.name,
                self._pack_id,
            )
            return

        # Bind to target
        if self._target_agent:
            # Bind to agent in context state
            bound_agents = context.get("bound_agents", {})
            bound_agents[self._target_agent] = pack
            context.set("bound_agents", bound_agents)
            _logger.debug(
                "BindSkillProcessor: pack %s bound to agent %s",
                self._pack_id,
                self._target_agent,
            )
        else:
            # Bind to current step output
            if self._output_key:
                exchange.set_property(self._output_key, pack)
            _logger.debug(
                "BindSkillProcessor: pack %s bound to step output key %s",
                self._pack_id,
                self._output_key,
            )

    async def _resolve_pack(self, registry: Any) -> dict[str, Any] | None:
        """Resolve skill pack из registry.

        Args:
            registry: SkillRegistry или compatible.

        Returns:
            Pack dict или None если не найден.
        """
        # Try get_skill_pack method
        get_pack = getattr(registry, "get_skill_pack", None)
        if get_pack is not None:
            return await get_pack(self._pack_id)

        # Fallback: get individual skills from pack
        list_packs = getattr(registry, "list_skill_packs", None)
        if list_packs is not None:
            packs = await list_packs()
            for pack in packs:
                if pack.get("id") == self._pack_id:
                    return pack
        return None
