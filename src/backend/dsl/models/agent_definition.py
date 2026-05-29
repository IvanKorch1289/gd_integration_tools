"""Pydantic-декларация AI-агента (S25-S27 AI Platform, Task 3 GAP G5).

Модуль определяет декларативное YAML-описание AI-агента для unification
runtime'ов (LangGraph, PydanticAI, DSPy). Соответствует контракту ADR-NEW-19
"Agent DSL & Runtime Adapter".

Пример YAML::

    name: credit_risk_agent
    version: 1
    runtime: langgraph
    model:
      primary: openai/gpt-4o-mini
      fallback:
        - anthropic/claude-sonnet-4-6
        - local/llama-3-8b
    memory:
      episodic: { backend: postgres, ttl_hours: 168 }
      semantic: { backend: qdrant, ttl_hours: 720 }
    policy: credit_check_strict
    tools:
      - rag_query: { namespace: credit_docs, top_k: 5 }
      - sanitize_pii: {}
      - guardrails: { max_length: 10000 }
    rlm:
      enabled: true
      boost_factor: 0.1

Архитектура:
    * Каждая секция — отдельная Pydantic-модель (model_config extra="forbid").
    * :class:`AgentDefinition` — top-level aggregator.
    * Tools записываются YAML-friendly формой ``- <name>: { <config> }`` и
      нормализуются валидатором в :class:`ToolSpec` (имя + конфиг).
    * Ссылка на :class:`AIPolicySpec` хранится строкой (``policy: <name>``);
      resolve выполняется в runtime через :class:`PolicyResolver`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = (
    "AgentDefinition",
    "MemoryLayerSpec",
    "MemorySpec",
    "ModelRouterSpec",
    "RLMSpec",
    "StopConditionSpec",
    "SupervisorSpec",
    "ToolSpec",
)


AgentRuntime = Literal["langgraph", "pydanticai", "dspy"]


class ModelRouterSpec(BaseModel):
    """Описание LLM model-router с fallback chain.

    Использует LiteLLM-формат идентификаторов моделей
    (``openai/gpt-4o-mini``, ``anthropic/claude-sonnet-4-6``,
    ``local/llama-3-8b``). Совместим с :class:`LiteLLMGateway`.

    Attributes:
        primary: Канонический идентификатор primary-модели.
        fallback: Список fallback-моделей в порядке убывания приоритета.
            :class:`ModelRouter` пробует их при ошибке primary.
        timeout_s: Per-call таймаут в секундах.
        retry_attempts: Количество повторов primary до перехода на fallback.
    """

    model_config = ConfigDict(extra="forbid")

    primary: str = Field(
        min_length=1, description="Canonical LiteLLM model id primary."
    )
    fallback: list[str] = Field(
        default_factory=list, description="Fallback chain в порядке приоритета."
    )
    timeout_s: float = Field(
        default=30.0, gt=0.0, description="Per-call timeout в секундах."
    )
    retry_attempts: int = Field(
        default=2, ge=0, description="Повторы primary до fallback."
    )


class MemoryLayerSpec(BaseModel):
    """Описание одного memory layer'а (episodic / semantic / scratch).

    Совместимо с :class:`MemoryProtocol` (ADR-NEW-18, S24 W3) и
    :class:`MemorySpec` в :mod:`core.ai.policy.spec`.

    Attributes:
        backend: Тип backend'а (``"postgres"``, ``"qdrant"``, ``"redis"``,
            ``"mem0+pgvector"``, ``"langgraph+postgres"``, ...).
        ttl_hours: TTL записей в часах; ``None`` — без ограничения.
        namespace: Шаблон namespace с подстановками (``"agent:{tenant_id}"``).
        encryption: При ``True`` payload шифруется ключами Vault.
    """

    model_config = ConfigDict(extra="forbid")

    backend: str = Field(min_length=1, description="Тип backend'а memory.")
    ttl_hours: int | None = Field(
        default=None, ge=0, description="TTL в часах; None — без ограничения."
    )
    namespace: str | None = Field(
        default=None, description="Шаблон namespace; None — runtime-default."
    )
    encryption: bool = Field(
        default=True, description="Шифровать ли payload через Vault keys."
    )


class MemorySpec(BaseModel):
    """Конфигурация memory-layers агента.

    Соответствует трём временным горизонтам LangMem/Mem0:

    * ``scratch`` — короткая память (минуты-часы, обычно Redis).
    * ``episodic`` — эпизодическая (часы-дни, postgres/qdrant).
    * ``semantic`` — долговременная семантическая (недели-месяцы, qdrant).

    Все секции опциональны; runtime использует defaults из :class:`AIPolicySpec`
    при отсутствии соответствующих слоёв.

    Attributes:
        scratch: Краткосрочный scratchpad.
        episodic: Эпизодическая память (история взаимодействий).
        semantic: Долгосрочная семантическая память (RAG-like).
    """

    model_config = ConfigDict(extra="forbid")

    scratch: MemoryLayerSpec | None = Field(
        default=None, description="Краткосрочный scratchpad (Redis)."
    )
    episodic: MemoryLayerSpec | None = Field(
        default=None, description="Эпизодическая память (Postgres/Qdrant)."
    )
    semantic: MemoryLayerSpec | None = Field(
        default=None, description="Долгосрочная семантическая память (Qdrant)."
    )


class ToolSpec(BaseModel):
    """Описание одного tool'а агента.

    YAML-форма (single-key dict)::

        tools:
          - rag_query: { namespace: credit_docs, top_k: 5 }
          - sanitize_pii: {}

    Нормализуется в ``ToolSpec(name="rag_query", config={...})`` валидатором
    :meth:`AgentDefinition._normalize_tools`. Допустима также явная форма::

        tools:
          - name: rag_query
            config: { namespace: credit_docs, top_k: 5 }

    Attributes:
        name: Идентификатор tool'а в :class:`ToolRegistry`.
        config: Параметры tool'а (произвольный dict).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Идентификатор tool'а в registry.")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Конфигурация tool'а."
    )


class SupervisorSpec(BaseModel):
    """Supervisor-узел LangGraph (multi-agent orchestration).

    Используется в LangGraph runtime для координации sub-agents. См.
    ADR-NEW-19 §3.2 "Supervisor pattern".

    Attributes:
        type: Тип supervisor'а (``"hierarchical"`` — иерархия, ``"flat"`` —
            один уровень, ``"router"`` — pure-router без планирования).
        max_iterations: Максимум итераций цикла supervisor → agent → supervisor.
        agents: Список имён sub-agents, доступных supervisor'у.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["hierarchical", "flat", "router"] = Field(
        default="flat", description="Тип supervisor-паттерна."
    )
    max_iterations: int = Field(
        default=10, ge=1, description="Максимум итераций координации."
    )
    agents: list[str] = Field(
        default_factory=list, description="Имена sub-agents под supervisor'ом."
    )


class StopConditionSpec(BaseModel):
    """Условия остановки агента (anti-loop, budget-cap).

    Любое из условий, достигшее предела, останавливает цикл агента.
    Используется во всех runtime'ах (LangGraph/PydanticAI/DSPy) как
    унифицированная защита от бесконечного цикла.

    Attributes:
        max_steps: Максимум шагов graph'а (узлов LangGraph / iterations DSPy).
        max_tool_calls: Максимум вызовов tools за одну инвокацию.
        max_tokens: Hard-cap на total tokens (prompt + completion).
        max_cost_usd: Hard-cap на стоимость инвокации (USD).
        max_wall_time_s: Hard-cap на wall-clock время (секунды).
    """

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=25, ge=1, description="Максимум шагов graph'а.")
    max_tool_calls: int = Field(default=50, ge=1, description="Максимум вызовов tools.")
    max_tokens: int | None = Field(
        default=None, ge=1, description="Hard-cap total tokens."
    )
    max_cost_usd: float | None = Field(
        default=None, gt=0.0, description="Hard-cap стоимости USD."
    )
    max_wall_time_s: float | None = Field(
        default=None, gt=0.0, description="Hard-cap wall-time секунды."
    )


class RLMSpec(BaseModel):
    """Reinforcement Learning Memory (RLM) контур обучения.

    См. Task 4 GAP G4 + :mod:`services.ai.memory.langmem.rlm`. RLM-цикл:
    feedback → score-adjustment → re-embed → upsert в vector store.

    Attributes:
        enabled: Включён ли RLM-цикл для этого агента.
        boost_factor: Сила положительной/отрицательной коррекции score'а
            при позитивном/негативном feedback (``adjust_score`` formula).
        threshold: Порог penalty, при котором запись попадает в consolidation.
        consolidation_batch_size: Размер batch'а для periodic consolidation.
        reindex_interval_hours: Интервал автоматического re-index'а памяти.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, description="Включён ли RLM-цикл.")
    boost_factor: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Сила коррекции score'а на одну обратную связь.",
    )
    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Порог penalty для попадания в consolidation.",
    )
    consolidation_batch_size: int = Field(
        default=100, ge=1, description="Размер batch'а consolidation."
    )
    reindex_interval_hours: int | None = Field(
        default=24, ge=1, description="Интервал re-index'а; None — отключено."
    )


class AgentDefinition(BaseModel):
    """Top-level декларация AI-агента (ADR-NEW-19, GAP G5).

    Загружается из ``agents/<name>.agent.yaml`` через
    :func:`src.backend.dsl.loaders.agent_loader.load_agent_yaml`.

    Attributes:
        name: Уникальное имя агента (``"credit_risk_agent"``).
        version: Версия декларации (для breaking changes).
        runtime: Целевой runtime — ``"langgraph"`` | ``"pydanticai"`` | ``"dspy"``.
        model: :class:`ModelRouterSpec` — primary + fallback chain.
        memory: :class:`MemorySpec` — память агента (опционально).
        policy: Имя :class:`AIPolicySpec` для AI-gateway enforcement
            (input/output sanitizers + guards + budget). Резолвится
            через :class:`PolicyResolver` в runtime.
        tools: Список :class:`ToolSpec`. Поддерживается YAML-форма
            ``- <name>: {config}`` (single-key dict).
        supervisor: :class:`SupervisorSpec` — multi-agent orchestration
            (LangGraph runtime).
        stop_condition: :class:`StopConditionSpec` — anti-loop / budget-cap.
        rlm: :class:`RLMSpec` — RL-memory loop (опционально).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Уникальное имя агента.")
    version: int = Field(default=1, ge=1, description="Версия декларации.")
    runtime: AgentRuntime = Field(description="Целевой runtime агента.")
    model: ModelRouterSpec = Field(description="LLM model-router + fallback chain.")
    memory: MemorySpec | None = Field(
        default=None, description="Memory-layers; None — defaults из AIPolicySpec."
    )
    policy: str | None = Field(
        default=None,
        min_length=1,
        description="Имя AIPolicySpec для gateway-enforcement.",
    )
    tools: list[ToolSpec] = Field(
        default_factory=list, description="Tools агента (RAG / sanitizers / guards)."
    )
    supervisor: SupervisorSpec | None = Field(
        default=None, description="Supervisor multi-agent (LangGraph)."
    )
    stop_condition: StopConditionSpec | None = Field(
        default=None, description="Anti-loop / budget-cap условия."
    )
    rlm: RLMSpec | None = Field(default=None, description="RL-memory loop.")

    @field_validator("tools", mode="before")
    @classmethod
    def _normalize_tools(cls, raw: Any) -> Any:
        """Нормализация YAML-формы tools в список :class:`ToolSpec`.

        Поддерживаются три формы записи tools в YAML:

        1. **Single-key dict** (рекомендуется, как в примере задачи)::

               tools:
                 - rag_query: { namespace: credit_docs, top_k: 5 }
                 - sanitize_pii: {}

        2. **Explicit form** (name + config)::

               tools:
                 - name: rag_query
                   config: { namespace: credit_docs, top_k: 5 }

        3. **Plain string** (если конфигурация не нужна)::

               tools:
                 - sanitize_pii

        Все три формы конвертируются в ``[ToolSpec(name=..., config=...)]``.

        Args:
            raw: Сырое значение поля ``tools`` из YAML или
                инициализатора.

        Returns:
            Нормализованный список dict-ов, готовых к Pydantic-валидации.
        """
        if raw is None:
            return []
        if not isinstance(raw, list):
            return raw
        normalized: list[Any] = []
        for item in raw:
            if isinstance(item, str):
                normalized.append({"name": item, "config": {}})
            elif isinstance(item, dict):
                if "name" in item:
                    normalized.append(item)
                elif len(item) == 1:
                    [(key, value)] = item.items()
                    config = value if isinstance(value, dict) else {}
                    normalized.append({"name": key, "config": config})
                else:
                    normalized.append(item)
            else:
                normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def _validate_supervisor_runtime(self) -> AgentDefinition:
        """Supervisor допустим только для langgraph runtime.

        PydanticAI и DSPy не поддерживают multi-agent supervisor pattern из
        коробки; объявление supervisor в их декларации, вероятно, опечатка
        или ошибочное копирование, поэтому валидация падает на раннем этапе.

        Returns:
            self, если конфигурация корректна.

        Raises:
            ValueError: При supervisor + non-langgraph runtime.
        """
        if self.supervisor is not None and self.runtime != "langgraph":
            raise ValueError(
                f"supervisor поддерживается только для runtime='langgraph', "
                f"задано runtime={self.runtime!r}"
            )
        return self
