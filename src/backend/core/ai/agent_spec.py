"""AgentSpec, MemoryScope, HandoffPolicy (S28 W1, план Agent DSL + Memory Orchestration).

Модуль определяет data-классы для декларативного описания AI-агентов,
используемых в Workflow DSL (``:class:`AgentInvokeDeclaration``) и
:mod:`core.ai.agent_registry`.

Data-классы (frozen=True, slots=True) выбраны вместо Pydantic- моделей
специально для:
- immutability (agent definitions не должны мутировать в runtime);
- memory efficiency (slots);
- comparability через equality.

Memory Scope
------------
Каждый агент имеет ``memory: MemoryScope`` — декларирует какие memory
resources читает/пишет. Проверяется через capability-gate
(``memory.read.<resource>``, ``memory.write.<resource>``).

Handoff Policy
--------------
``handoff: HandoffPolicy`` — правила передачи управления другому агенту
(multi-agent supervisor pattern). Лимитирует количество handoffs и
разрешает/запрещает re-visiting агентов.

Agent Registry
--------------
Загрузка из plugin.toml ``[[agent]]`` секций — через
:class:`AgentRegistry <core.ai.agent_registry.AgentRegistry>`.

См. также
----------
* :class:`SkillSpec` — :mod:`core.ai.skill_registry` (skill definitions).
* :class:`AgentInvokeDeclaration` — :mod:`dsl.workflow.spec`.
* :class:`AgentRegistry` — :mod:`core.ai.agent_registry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = (
    "MemoryScope",
    "HandoffPolicy",
    "AgentSpec",
)


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Memory scoping policy для агента.

    Определяет какие memory resources агент может читать и писать,
    а также стратегию записи.

    Attributes:
        read: Кортеж имён memory resources для чтения
            (``("memory_main", "episodic")``). Пустой = без доступа.
        write: Кортеж имён memory resources для записи.
        mode: Стратегия изоляции:

            * ``"none"`` — доступ закрыт (no memory access);
            * ``"scoped"`` — isolated namespace per workflow/session;
            * ``"inherited"`` — наследует memory scope вызывающего;
            * ``"shared"`` — shared между всеми агентами workflow.
        write_strategy: Стратегия записи в long-term memory:

            * ``"hot_path"`` — писать сразу после каждого turn;
            * ``"background"`` — batch consolidation в фоне;
            * ``"manual"`` — только явный ``reflect`` step.
    """

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    mode: Literal["none", "scoped", "inherited", "shared"] = "scoped"
    write_strategy: Literal["hot_path", "background", "manual"] = "background"


@dataclass(frozen=True, slots=True)
class HandoffPolicy:
    """Правила передачи управления другому агенту (multi-agent supervisor).

    Используется в ``invoke_agent`` шаге workflow, когда LLM-driven
    supervisor решает передать управление другому агенту.

    Attributes:
        max_handoffs: Максимальное количество handoffs в одном
            workflow execution (default 5). При достижении лимита
            применяется ``escalation_on_max_handoffs``.
        allow_revisit: Разрешает ли агенту повторно вызвать агента,
            которому он уже передавал управление.
        escalation_on_max_handoffs: ``agent_id`` агента для escalation
            при достижении ``max_handoffs``. Если ``None`` — workflow
            завершается с ошибкой.
    """

    max_handoffs: int = 5
    allow_revisit: bool = False
    escalation_on_max_handoffs: str | None = None


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Декларативное описание AI-агента (data-класс, не Pydantic-модель).

    Маппится 1:1 на TOML-секцию ``[[agent]]`` из ``plugin.toml`` V11.2::

        [[agent]]
        id            = "credit_advisor"
        version       = "1.0.0"
        model         = "minimax:m2"
        prompt_ref    = "prompts/credit_advisor.j2"
        skills        = ["credit.score.calculate", "credit.check.rules"]
        tools         = ["actions.credit.fetch", "actions.credit.approve"]
        memory_mode   = "scoped"
        memory_write  = ["episodic"]
        handoff_max   = 5
        handoff_allow_revisit = false
        policy_ref    = "credit_strict"
        max_turns     = 15
        timeout_s     = 90.0
        tenant_aware  = true
        feature_flag  = "CREDIT_ADVISOR_V2_ENABLED"

    Атрибуты
    ---------
    id: Уникальный идентификатор (``"credit_advisor"``).
        Конвенция: ``<domain>_<role>``.
    version: SemVer-версия (``"1.0.0"``).
    model: Провайдер и модель (``"provider:model"``, например
        ``"minimax:m2"``, ``"openai:gpt-4o"``). Используется
        :class:`ModelRouter <core.ai.gateway.ModelRouter>` для
        routing между провайдерами.
    prompt_ref: Путь к Jinja2-шаблону (``"prompts/credit.j2"``).
        Если задан — ``prompt_inline`` игнорируется.
    prompt_inline: Инлайн-prompt (fallback если ``prompt_ref`` не задан).
    skills: Кортеж skill_id references из :class:`SkillRegistry`.
    tools: Кортеж action names доступных как tools для агента
        (из :class:`ActionHandlerRegistry`).
    memory: Memory scope policy для агента.
    handoff: Handoff policy для multi-agent supervisor.
    policy_ref: Ссылка на :class:`AIPolicySpec.name`
        (``"credit_strict"``); агент выполняется через :class:`AIGateway`
        с этой политикой.
    retry_policy: Retry policy для LLM-вызова.
    max_turns: Максимум turns в agent conversation (default 10).
    timeout_s: Per-invocation timeout (default 60.0).
    tenant_aware: Если ``True`` — агент получает ``tenant_id`` из
        :class:`TenantContext` (через DI).
    feature_flag: Опционально — имя feature-flag из
        :mod:`core.config.features`; агент доступен только при
        ``FeatureFlags.<name> = True``.

    Notes
    -----
    Все поля immutable (frozen=True). Для runtime mutation
    используется registry pattern с перерегистрацией.
    """

    id: str
    version: str
    model: str
    prompt_ref: str | None = None
    prompt_inline: str | None = None
    skills: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    memory: MemoryScope = field(default_factory=MemoryScope)
    handoff: HandoffPolicy = field(default_factory=HandoffPolicy)
    policy_ref: str | None = None
    retry_policy: "RetryPolicy | None" = None
    max_turns: int = 10
    timeout_s: float = 60.0
    tenant_aware: bool = True
    feature_flag: str | None = None


from src.backend.dsl.workflow.spec import RetryPolicy  # noqa: F401, E402