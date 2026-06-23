"""MemoryProfileSpec — спецификация memory profiles (S29 W1).

План Agent DSL + Memory Orchestration Layer, Phase 5.

Memory profile — декларативное описание одного storage backend для
agent memory. Позволяет declaratively настроить retention, namespace,
access pattern для каждого memory resource.

Декларация в plugin.toml::

    [[memory_profile]]
    id            = "episodic_long_term"
    kind          = "episodic"
    store         = "memory_postgres"
    namespace_template = "tenant:${tenant_id}:memory:episodic"
    retention_days = 90
    access        = "scoped"
    consolidation = "reflect_dedup"

Usage::

    profile = MemoryProfileSpec(
        id="episodic_long_term",
        kind=MemoryKind.EPISODIC,
        store="memory_postgres",
        namespace_template="tenant:${tenant_id}:memory:episodic",
        retention_days=90,
    )

См. также
---------
* :class:`AgentMemoryGateway` — :mod:`core.interfaces.agent_memory`.
* :class:`AgentRegistry` — :mod:`core.ai.agent_registry`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


__all__ = ("MemoryKind", "MemoryProfileSpec")


class MemoryKind(StrEnum):
    """Вид memory resource (по аналогии с Tier-типами).

    Attributes:
        WORKING: Short-term in-memory (scratchpad, conversation messages).
            TTL ~minutes. Хранится в Redis/Mongo.
        EPISODIC: Journal прошлых executions. Medium-term, queryable.
            Хранится в PostgreSQL.
        SEMANTIC: Domain facts, rules, entities через embeddings.
            Long-term. Хранится в Qdrant/Weaviate.
        PROCEDURAL: Instructions, policies, playbooks.
            Read-heavy, rarely written. Хранится в PostgreSQL/Vectordb.
    """

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryProfileSpec(BaseModel):
    """Декларативное описание memory profile (S29 W1).

    Определяет storage backend, namespace scheme, retention и access pattern
    для одного memory resource.

    Декларируется в ``plugin.toml`` секцией ``[[memory_profile]]``.

    YAML::

        memory_profiles:
          - id: "episodic_long_term"
            kind: "episodic"
            store: "memory_postgres"
            namespace_template: "tenant:${tenant_id}:memory:episodic"
            retention_days: 90
            access: "scoped"
            consolidation: "reflect_dedup"

    Attributes:
        id: Уникальный идентификатор (``"episodic_long_term"``).
        kind: :class:`MemoryKind` — тип памяти (working/episodic/semantic/procedural).
        store: Имя storage backend (``"memory_main"``, ``"memory_postgres"``,
            ``"memory_qdrant"``). Должно быть зарегистрировано в
            :class:`AgentMemoryGateway`.
        namespace_template: Шаблон namespace. Подставляет ``${tenant_id}``,
            ``${workflow_name}``, ``${session_id}``.
        retention_days: Срок хранения в днях. ``None`` = бессрочно.
        access: Стратегия доступа:

            * ``"scoped"`` — изолированный namespace per workflow/session;
            * ``"shared-read"`` — все агенты читают, только owner пишет;
            * ``"shared-write"`` — все агенты читают и пишут.
        consolidation: Policy name для consolidation
            (``"summarize"``, ``"dedup"``, ``"reflect"``, ``"none"``).
        schema_ref: Опц. ссылка на JSON-Schema для валидации записей.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Уникальный идентификатор.")
    kind: MemoryKind = Field(description="Тип памяти.")
    store: str = Field(
        min_length=1, description="Имя storage backend в AgentMemoryGateway."
    )
    namespace_template: str = Field(
        description=(
            "Шаблон namespace. Подставляет ${tenant_id}, "
            "${workflow_name}, ${session_id}."
        )
    )
    retention_days: int | None = Field(
        default=None, ge=1, description="Срок хранения в днях. None = бессрочно."
    )
    access: Literal["scoped", "shared-read", "shared-write"] = "scoped"
    consolidation: Literal["summarize", "dedup", "reflect", "none"] = "none"
    schema_ref: str | None = Field(
        default=None, description="JSON-Schema path для валидации записей."
    )
