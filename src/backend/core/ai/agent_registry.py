"""AgentRegistry V11.2 — TOML-manifest реестр AI-агентов (S28 W1).

Загружает ``[[agent]]`` секции из ``extensions/<plugin>/plugin.toml``
и предоставляет singleton lookup для :class:`AgentSpec`.

Архитектура аналогична :class:`SkillRegistry <core.ai.skill_registry.SkillRegistry>`:
тот же паттерн TOML- manifest + Python decorator bridge + hot-reload.

Agent Definition
----------------
Каждый агент в plugin.toml::

    [[agent]]
    id            = "credit_advisor"
    version       = "1.0.0"
    model         = "minimax:m2"
    prompt_ref    = "prompts/credit_advisor.j2"
    skills        = ["credit.score.calculate"]
    tools         = ["actions.credit.fetch"]
    memory_mode   = "scoped"
    memory_write  = ["episodic"]
    handoff_max   = 5
    handoff_allow_revisit = false
    policy_ref    = "credit_strict"
    max_turns     = 15
    timeout_s     = 90.0
    tenant_aware  = true
    feature_flag  = "CREDIT_ADVISOR_V2_ENABLED"

Lookup
------
1. :meth:`from_toml_manifest` — V11.2 TOML loader.
2. :meth:`register` — direct Python registration (для тестов/dynamic agents).
3. :meth:`get_agent` — lookup по ``agent_id``.

DI Registration
--------------
``AgentRegistry`` регистрируется как singleton в DI-контейнере
(через ``svcs`` или аналогичный механизм).

Hot-reload: при изменении ``plugin.toml`` через watchfiles.awatch (Wave B) —
diff + unregister/register changes (target ≤ 2s reload).

Scaffold S28 W1: model + methods; full implementation loader — S28 W2.

См. также
---------
* :class:`AgentSpec` — :mod:`core.ai.agent_spec`.
* :class:`SkillRegistry` — :mod:`core.ai.skill_registry` (skill definitions).
* docs/adr/ADR-NEW-22-agent-registry.md.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from src.backend.core.ai.agent_spec import AgentSpec

__all__ = ("AgentRegistry",)

logger = get_logger(__name__)


class AgentRegistry:
    """Реестр AI-агентов (TOML manifest + Python registration sov).

    Lookup flow:

    1. :meth:`from_toml_manifest` — V11.2 TOML loader (новый путь).
    2. :meth:`register` — direct Python registration (tests / dynamic agents).
    3. :meth:`get_agent` — lookup по ``agent_id``.

    Notes:
        Scaffold-методы поднимают ``NotImplementedError`` до полной
        реализации в S28 W2 (TOML loader) и S28 W4 (hot-reload).
    """

    def __init__(self) -> None:
        """Инициализация пустого реестра."""
        self._agents: dict[str, AgentSpec] = {}

    # ── Loaders ────────────────────────────────────────────────────

    def from_toml_manifest(self, plugin_toml: Path) -> list[AgentSpec]:
        """Загрузить ``[[agent]]`` секции из ``plugin.toml`` V11.2.

        Args:
            plugin_toml: Абсолютный путь к ``plugin.toml`` плагина.

        Returns:
            Список :class:`AgentSpec` (по одному на секцию ``[[agent]]``).
            Каждый агент регистрируется в ``self._agents``.

        Raises:
            ValueError: TOML syntax error или missing required fields.
            NotImplementedError: S28 W2 — полная реализация.
        """
        import tomllib

        with plugin_toml.open("rb") as fh:
            data = tomllib.load(fh)

        agents_section: list[dict[str, Any]] | None = data.get("agent", [])
        if agents_section is None:
            return []

        from src.backend.core.ai.agent_spec import AgentSpec
        from src.backend.dsl.workflow.spec import RetryPolicy

        results: list[AgentSpec] = []
        for idx, raw in enumerate(agents_section):
            try:
                # Parse memory scope
                memory_mode = str(raw.get("memory_mode", "scoped"))
                memory_write = list(raw.get("memory_write", []))

                # Parse handoff policy
                handoff_max = int(raw.get("handoff_max", 5))
                handoff_allow_revisit = bool(raw.get("handoff_allow_revisit", False))
                handoff_escalation = raw.get("handoff_escalation_on_max")

                from src.backend.core.ai.agent_spec import HandoffPolicy, MemoryScope

                memory_scope = MemoryScope(
                    read=tuple(raw.get("memory_read", [])),
                    write=tuple(memory_write),
                    mode=memory_mode,
                    write_strategy=str(raw.get("memory_write_strategy", "background")),
                )
                handoff_policy = HandoffPolicy(
                    max_handoffs=handoff_max,
                    allow_revisit=handoff_allow_revisit,
                    escalation_on_max_handoffs=handoff_escalation,
                )

                # Parse retry policy if present
                retry_policy: RetryPolicy | None = None
                if "retry_max_attempts" in raw:
                    retry_policy = RetryPolicy(
                        max_attempts=int(raw.get("retry_max_attempts", 3)),
                        initial_interval_s=float(
                            raw.get("retry_initial_interval_s", 1.0)
                        ),
                        backoff_coefficient=float(
                            raw.get("retry_backoff_coefficient", 2.0)
                        ),
                    )

                spec = AgentSpec(
                    id=str(raw["id"]),
                    version=str(raw["version"]),
                    model=str(raw["model"]),
                    prompt_ref=raw.get("prompt_ref"),
                    prompt_inline=raw.get("prompt_inline"),
                    skills=tuple(raw.get("skills", [])),
                    tools=tuple(raw.get("tools", [])),
                    memory=memory_scope,
                    handoff=handoff_policy,
                    policy_ref=raw.get("policy_ref"),
                    retry_policy=retry_policy,
                    max_turns=int(raw.get("max_turns", 10)),
                    timeout_s=float(raw.get("timeout_s", 60.0)),
                    tenant_aware=bool(raw.get("tenant_aware", True)),
                    feature_flag=raw.get("feature_flag"),
                )
            except KeyError as exc:
                raise ValueError(
                    f"from_toml_manifest: agent[{idx}] missing required field: {exc}"
                ) from exc

            self._agents[spec.id] = spec
            results.append(spec)

        return results

    # ── Registration ───────────────────────────────────────────────

    def register(self, spec: AgentSpec) -> None:
        """Зарегистрировать агента напрямую (для тестов/dynamic agents).

        Args:
            spec: Полностью инициализированный :class:`AgentSpec`.
        """
        self._agents[spec.id] = spec
        logger.debug("AgentRegistry: registered agent %s v%s", spec.id, spec.version)

    # ── Lookup ─────────────────────────────────────────────────────

    def get_agent(self, agent_id: str) -> AgentSpec:
        """Получить агента по ``agent_id``.

        Args:
            agent_id: Идентификатор агента.

        Returns:
            :class:`AgentSpec`.

        Raises:
            KeyError: Агент не найден.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"AgentRegistry.get_agent: agent_id={agent_id!r} not found")
        return agent

    def list_agents(self) -> list[AgentSpec]:
        """Список всех зарегистрированных агентов.

        Returns:
            Snapshot всех :class:`AgentSpec` (deterministic order по id).
        """
        return sorted(self._agents.values(), key=lambda a: a.id)

    # ── Hot-reload ─────────────────────────────────────────────────

    async def hot_reload(self, plugin_toml: Path) -> None:
        """Перечитать ``plugin.toml`` манифесты через watchfiles.

        Используется как callback из ``watchfiles.awatch`` (Wave B) при
        изменении ``extensions/*/plugin.toml``.

        Args:
            plugin_toml: Путь к изменённому ``plugin.toml``.

        Raises:
            NotImplementedError: S28 W4 — hot-reload implementation.
        """
        raise NotImplementedError("S28 W4: hot-reload через watchfiles")
