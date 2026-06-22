"""AIPolicySpec — Pydantic v2 декларативная политика AI per-workflow.

См. ADR-NEW-20 / docs/adr/0067-ai-policy-spec-dsl.md.

Scaffold S25 W2: создаёт типовую модель + базовую валидацию.
Полная резолюция (per-tenant override, JSON-Schema валидация, hot-reload) —
в :class:`PolicyResolver` (см. :mod:`core.ai.policy.resolver`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = (
    "AIPolicySpec",
    "AuditSpec",
    "BackendSpec",
    "BudgetSpec",
    "GuardRef",
    "MemorySpec",
    "ModelRouterSpec",
    "SanitizerRef",
    "ToolsSpec",  # S76 W1
)


class ModelRouterSpec(BaseModel):
    """Описание fallback chain моделей + RLM strategy.

    Attributes:
        primary: Канонический идентификатор модели (LiteLLM-формат:
            ``"openrouter/anthropic/claude-3.5-sonnet"``,
            ``"openai/gpt-4o-mini"``, ``"huggingface/local-llama-3"``).
        fallback: Список fallback-моделей в порядке убывания приоритета.
            ``ModelRouter`` пробует их при ошибке primary (timeout,
            rate-limit, недоступность).
        timeout_s: Per-call таймаут в секундах.
        retry_attempts: Количество повторных попыток primary до перехода
            на fallback chain.
        router_strategy: S169 W2 (RLM) — стратегия выбора модели.
            ``"failover"`` (default) — primary + fallback при ошибках
            (LiteLLMGateway.acompletion(fallbacks=...)).
            ``"complexity"`` — weak model (``cheap_model``) для простых
            запросов (короткий prompt, factual, single-step), primary
            для сложных (multi-step reasoning, long context).
            Implementation deferred to S170+ (per audit backlog P1-2).
        cheap_model: RLM weak model для ``router_strategy="complexity"``.
            Должен быть значительно дешевле primary (например
            ``"openai/gpt-4o-mini"`` vs ``"openai/gpt-4o"``,
            ``"anthropic/claude-3-haiku"`` vs ``"anthropic/claude-3.5-sonnet"``).
            Если None — strategy degrades to ``"failover"`` behaviour.
    """

    primary: str
    fallback: list[str] = Field(default_factory=list)
    timeout_s: float = 30.0
    retry_attempts: int = 2
    router_strategy: Literal["failover", "complexity"] = "failover"  # S169 W2
    cheap_model: str | None = None  # S169 W2 (RLM weak model)


class SanitizerRef(BaseModel):
    """Ссылка на input/output sanitizer.

    Attributes:
        name: Идентификатор sanitizer'а в формате ``"<engine>:<scope>"``.
            Примеры: ``"presidio:ru"``, ``"pii_tokenizer:reversible:ru_strict"``,
            ``"jsonschema:CreditDecision"``.
        config: Опциональные параметры engine'а (threshold, language, и т. п.).
        on_error: Поведение при ошибке sanitizer'а:
            ``"fail"`` — поднять исключение;
            ``"warn"`` — логировать и продолжить;
            ``"skip"`` — обойти sanitizer без логирования.
    """

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    on_error: Literal["fail", "warn", "skip"] = "fail"


class GuardRef(BaseModel):
    """Ссылка на input/output guard.

    Attributes:
        name: Идентификатор guard'а в формате ``"<engine>:<variant>"``.
            Примеры: ``"nemo:colang:topics"``, ``"llama_guard:safe_v3"``,
            ``"rebuff:default"``, ``"lakera:strict"``.
        config: Опциональные параметры engine'а
            (threshold, allowed_topics, и т. п.).
        on_block: Поведение при блокировке guard'ом:
            ``"fail"`` — поднять :exc:`GuardrailViolationError`;
            ``"warn"`` — логировать и продолжить;
            ``"dlq"`` — отправить запрос в Dead Letter Queue.
    """

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    on_block: Literal["fail", "warn", "dlq"] = "fail"


class BackendSpec(BaseModel):
    """Описание backend'а для memory layer.

    Attributes:
        backend: Тип backend'а (``"redis"``, ``"mem0+pgvector"``,
            ``"langgraph+postgres"``, ``"mongodb"``, ...).
        namespace: Шаблон namespace с подстановками
            (``"credit:short:{tenant_id}:{session_id}"``).
        ttl: TTL в секундах (если применимо).
    """

    backend: str
    namespace: str
    ttl: int | None = None


class MemorySpec(BaseModel):
    """Описание memory layer'а для AI-инвокации.

    Соответствует ``MemoryProtocol`` (ADR-NEW-18, S24 W3).

    Attributes:
        short_term: Краткосрочный scratchpad (Redis); живёт минуты-часы.
        long_term: Долгосрочный semantic memory (Mem0 + pgvector); дни-месяцы.
        episodic: Эпизодическая память (Qdrant); недели.
        checkpointer: LangGraph durable state (Postgres); до явного удаления.
        tenant_isolation: Если ``True`` — namespace всегда включает
            ``tenant_id``; cross-tenant утечки заблокированы.
        encryption: Если ``True`` — payload шифруется через
            ``infrastructure/secrets/`` ключами Vault.
    """

    short_term: BackendSpec | None = None
    long_term: BackendSpec | None = None
    episodic: BackendSpec | None = None
    checkpointer: BackendSpec | None = None
    tenant_isolation: bool = True
    encryption: bool = True


class BudgetSpec(BaseModel):
    """Бюджет AI-инвокации.

    Attributes:
        max_tokens_prompt: Максимум токенов prompt после template-render
            + sanitize (используется ``tiktoken`` trim).
        max_tokens_completion: Максимум токенов completion от LLM.
        max_cost_usd: Hard limit стоимости одной инвокации.
        ttl_s: TTL результата в cache (если включён semantic cache).
        context_strategy: Стратегия управления conversation history
            (``rolling_window`` | ``map_reduce`` | ``hierarchical``).
            gap-ai-8.
    """

    max_tokens_prompt: int = Field(default=8000, ge=1)
    max_tokens_completion: int = Field(default=2000, ge=1)
    max_cost_usd: float = Field(default=0.50, ge=0)
    ttl_s: int = Field(default=3600, ge=0)
    context_strategy: str = Field(default="rolling_window")


class AuditSpec(BaseModel):
    """Описание audit-секции AIPolicySpec.

    Attributes:
        extra_attrs: Дополнительные атрибуты для всех ``ai.invocation.*``
            событий (например, ``{"compliance": "152-FZ"}``).
            Добавляются в payload через ``AuditService`` (S17/K3).
        schema_version: Версия audit-схемы. Используется при breaking-changes.
    """

    extra_attrs: dict[str, str] = Field(default_factory=dict)
    schema_version: int = 1


class ToolsSpec(BaseModel):
    """S76 W1 (FINAL_REPORT_V2 P0-B) — tools whitelist/blacklist для
    AI agent'а.

    Защищает от over-permissive tool-инвокаций: agent может invoke
    только tools в whitelist (если whitelist непустой) и не может
    invoke tools в blacklist.

    Use case (FINAL_REPORT_V2 P0-B): agent имеет доступ к 30+ tools
    (MCP gateway, built-in tools, plugin tools). Tenant admin хочет
    restrict agent только к ``["db.read.orders", "ai.invoke.credit_check"]``
    (whitelist) И запретить ``["fs.write", "shell.execute"]`` (blacklist).

    Attributes:
        whitelist: Список разрешённых tool names (пустой = no
            restriction, default). Используется :class:`AIGateway`
            для filter agent's tool set при invoke.
        blacklist: Список запрещённых tool names (пустой = no
            blacklist, default). Always applied (даже если whitelist
            непустой — explicit denylist).
        on_violation: Поведение при попытке invoke tool вне whitelist
            или в blacklist:
            ``"fail"`` — поднять :exc:`ToolPolicyViolationError` (default);
            ``"warn"`` — логировать warning и allow invocation;
            ``"block"`` — silently drop (no exception, no log).

    Examples:
        Только whitelist:
        ```yaml
        tools:
          whitelist: ["db.read.orders", "ai.invoke.credit_check"]
          on_violation: "fail"
        ```

        Только blacklist:
        ```yaml
        tools:
          blacklist: ["fs.write", "shell.execute", "network.open_socket"]
          on_violation: "fail"
        ```
    """

    whitelist: list[str] = Field(default_factory=list)
    blacklist: list[str] = Field(default_factory=list)
    on_violation: Literal["fail", "warn", "block"] = "fail"


class AIPolicySpec(BaseModel):
    """Декларативная политика AI per-workflow (ADR-NEW-20).

    YAML-описание в ``ai_policies/*.policy.yaml`` (global) и
    ``extensions/<plugin>/ai_policies/*.policy.yaml`` (per-tenant override).

    Полное описание полей и use-case см. в docs/adr/0067-ai-policy-spec-dsl.md.

    Attributes:
        name: Уникальное имя политики (``"credit_check_strict"``).
        version: Версия (для breaking changes).
        workflow_pattern: Glob-шаблон ``workflow_id`` (``"credit_check*"``
            или ``"credit_check"``); используется :class:`PolicyResolver`.
        tenant_pattern: Glob-шаблон ``tenant_id`` (``"*"`` или ``"premium*"``);
            per-tenant override.
        model_router: :class:`ModelRouterSpec` — primary + fallback.
        input_sanitizers: Список input sanitizers (PII, format-normalize).
        input_guards: Список input guards (jailbreak detection, topic filter).
        output_guards: Список output guards (Llama Guard).
        output_sanitizers: Список output sanitizers (PII redaction,
            JSON-Schema validation через Outlines).
        memory: :class:`MemorySpec` — memory layers (опционально).
        budget: :class:`BudgetSpec` — токены / стоимость / TTL.
        audit: :class:`AuditSpec` — audit-event extra attrs.
        tools: :class:`ToolsSpec` — S76 W1 (FINAL_REPORT_V2 P0-B)
            whitelist/blacklist для agent tool invocations. Default
            empty = no restriction (backward-compat с pre-S76).
        required: Если ``True`` — :class:`AIGateway` падает с
            :exc:`PolicyNotResolvedError` если resolver не нашёл подходящую
            политику. ``False`` — fallback default-pass-through.
    """

    name: str
    version: int = 1
    workflow_pattern: str
    tenant_pattern: str = "*"
    model_router: ModelRouterSpec
    input_sanitizers: list[SanitizerRef] = Field(default_factory=list)
    input_guards: list[GuardRef] = Field(default_factory=list)
    output_guards: list[GuardRef] = Field(default_factory=list)
    output_sanitizers: list[SanitizerRef] = Field(default_factory=list)
    memory: MemorySpec | None = None
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    audit: AuditSpec = Field(default_factory=AuditSpec)
    tools: ToolsSpec = Field(default_factory=ToolsSpec)  # S76 W1
    required: bool = True

    @property
    def model(self) -> str:
        """Returns the resolved model name (primary from model_router).

        This provides a convenient way to check which model will be used
        before calling AIGateway.
        """
        return self.model_router.primary
