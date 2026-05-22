"""ADR-044 — :class:`CapabilityVocabulary` — открытый registry.

Связывает имена capability с их :class:`ScopeMatcher` и метаданными
(scope_required, описание). v0-каталог регистрируется через
:func:`register_default_vocabulary`. Плагины могут добавлять
новые категории через ``vocabulary.register(...)`` (требует
meta-capability ``core.capability_vocabulary.extend`` — выдаётся
вручную ядром-админом, см. ADR-044).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.backend.core.security.capabilities.errors import CapabilityNotFoundError
from src.backend.core.security.capabilities.matchers import (
    ExactAliasMatcher,
    GlobScopeMatcher,
    ScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)
from src.backend.core.security.capabilities.models import CapabilityRef

__all__ = ("CapabilityDef", "CapabilityVocabulary", "build_default_vocabulary")


@dataclass(frozen=True, slots=True)
class CapabilityDef:
    """Метаданные одной зарегистрированной capability.

    Attributes:
        name: Полное имя ``<resource>.<verb>``.
        matcher: Strategy для резолвинга scope.
        scope_required: Если ``True`` — capability с ``scope=None``
            считается ошибкой манифеста.
        description: Человекочитаемая аннотация (для admin-UI и
            DSL-Linter).
        public: Если ``True`` — capability доступна route'у даже
            без явной декларации в плагине (например, общий
            ``net.outbound`` к публичным API).
    """

    name: str
    matcher: ScopeMatcher
    scope_required: bool = True
    description: str = ""
    public: bool = False
    """Часть «публичного капабилити-набора ядра» (см. ADR-044)."""

    aliases: tuple[str, ...] = field(default_factory=tuple)
    """Опц. альтернативные имена (legacy)."""


class CapabilityVocabulary:
    """Открытый registry capability-определений."""

    def __init__(self) -> None:
        self._defs: dict[str, CapabilityDef] = {}

    def register(self, definition: CapabilityDef) -> None:
        """Зарегистрировать capability.

        Raises:
            ValueError: Если capability с таким именем уже есть.
        """
        if definition.name in self._defs:
            raise ValueError(f"Capability already registered: {definition.name!r}")
        self._defs[definition.name] = definition
        for alias in definition.aliases:
            if alias in self._defs:
                raise ValueError(f"Alias {alias!r} conflicts with existing capability")
            self._defs[alias] = definition

    def get(self, name: str) -> CapabilityDef:
        """Найти определение по имени.

        Raises:
            CapabilityNotFoundError: Если имени нет в registry.
        """
        try:
            return self._defs[name]
        except KeyError as exc:
            raise CapabilityNotFoundError(name=name) from exc

    def has(self, name: str) -> bool:
        """Зарегистрирована ли capability."""
        return name in self._defs

    def all(self) -> tuple[CapabilityDef, ...]:
        """Все определения в порядке регистрации (без дубликатов)."""
        seen: set[str] = set()
        result: list[CapabilityDef] = []
        for definition in self._defs.values():
            if id(definition) in seen:
                continue
            seen.add(id(definition))
            result.append(definition)
        return tuple(result)

    def public_capabilities(self) -> tuple[CapabilityDef, ...]:
        """Подмножество ``public=True`` определений."""
        return tuple(d for d in self.all() if d.public)

    def validate_ref(self, ref: CapabilityRef) -> None:
        """Проверить, что ссылка осмысленна.

        - имя зарегистрировано;
        - если ``scope_required`` — scope не None.

        Raises:
            CapabilityNotFoundError: Имя отсутствует в registry.
            ValueError: ``scope_required`` нарушено.
        """
        definition = self.get(ref.name)
        if definition.scope_required and ref.scope is None:
            raise ValueError(
                f"Capability {ref.name!r} requires explicit scope (scope_required=True)"
            )


def build_default_vocabulary() -> CapabilityVocabulary:
    """Собирает CapabilityVocabulary с v0-каталогом из ADR-044.

    Matcher'ы выбираются по семантике sep'а ресурса:

    * ``.`` — host/topic/workflow_id (DNS-стиль);
    * ``/`` — path / provider-route;
    * ``:`` — cache-namespace.
    """
    vocab = CapabilityVocabulary()
    dot_glob = GlobScopeMatcher()  # sep="."
    path_glob = SegmentedGlobMatcher(sep="/")
    cache_glob = SegmentedGlobMatcher(sep=":")
    exact = ExactAliasMatcher()
    uri = URISchemeMatcher()

    vocab.register(
        CapabilityDef(
            name="db.read",
            matcher=exact,
            description="Чтение из БД через DatabaseFacade (read-only-сессия).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="db.write",
            matcher=exact,
            description="Запись в БД через DatabaseFacade (rw-сессия).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="secrets.read",
            matcher=uri,
            description="Чтение секрета через SecretsFacade (vault:// / env:// / kms://).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="net.outbound",
            matcher=dot_glob,
            description="Исходящие HTTP/gRPC через {HTTP,GRPC}Facade.",
        )
    )
    vocab.register(
        CapabilityDef(
            name="net.inbound",
            matcher=dot_glob,
            description="Регистрация webhook/SSE-эндпоинтов через WebhookFacade.",
        )
    )
    vocab.register(
        CapabilityDef(
            name="fs.read",
            matcher=path_glob,
            description="Чтение файлов через FSFacade (path-glob по '/').",
        )
    )
    vocab.register(
        CapabilityDef(
            name="fs.write",
            matcher=path_glob,
            description="Запись файлов через FSFacade (path-glob по '/').",
        )
    )
    vocab.register(
        CapabilityDef(
            name="fs.create_new",
            matcher=path_glob,
            description=(
                "Создание нового файла в AI workspace через AIFsFacade "
                "(non-overwriting; запись существующих файлов запрещена, V15 R-V15-4)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="code.execute",
            matcher=exact,
            description=(
                "Запуск пользовательского кода в sandbox (e2b/pyodide) через "
                "CodeSandbox; прямой subprocess запрещён (V15 R-V15-4)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="mq.publish",
            matcher=dot_glob,
            description="Публикация сообщений через MQFacade (topic-glob).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="mq.consume",
            matcher=dot_glob,
            description="Подписка на сообщения через MQFacade (topic-glob).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="cache.read",
            matcher=cache_glob,
            description="Чтение кэша через CacheFacade (namespace по ':').",
        )
    )
    vocab.register(
        CapabilityDef(
            name="cache.write",
            matcher=cache_glob,
            description="Запись в кэш через CacheFacade (namespace по ':').",
        )
    )
    vocab.register(
        CapabilityDef(
            name="workflow.start",
            matcher=dot_glob,
            description="Запуск workflow через WorkflowFacade (workflow_id-glob).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="workflow.signal",
            matcher=dot_glob,
            description="Сигнал workflow через WorkflowFacade.",
        )
    )
    vocab.register(
        CapabilityDef(
            name="llm.invoke",
            matcher=path_glob,
            description="Вызов LLM-провайдера через LLMFacade (provider/model по '/').",
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.stream",
            matcher=path_glob,
            description=(
                "Token-level streaming LLM (SSE/WS) через LLMStreamingService "
                "(scope = 'model:<prefix>', optional)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="mcp.tool.call",
            matcher=dot_glob,
            description=(
                "Вызов MCP-инструмента (FastMCP HTTP transport); "
                "scope = action-name pattern."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="langmem.admin",
            matcher=exact,
            description=(
                "Администрирование LangMem: consolidate(), stats(), RLM reset (D.6)."
            ),
        )
    )
    # ─── Sprint 11 — AI/RAG Completion capabilities ──────────────────────
    vocab.register(
        CapabilityDef(
            name="ai.rag.pii_redaction",
            matcher=exact,
            description=(
                "Применение PII-маскера к augment_result.documents[*].content "
                "в RAG retrieval pipeline (S11 K1 W1)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrails.lakera",
            matcher=dot_glob,
            description=(
                "Вызов Lakera Guard prompt-injection / PII detector. "
                "scope = '*' или конкретный provider-id (S11 K1 W2)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrails.rebuff",
            matcher=dot_glob,
            description=(
                "Вызов Rebuff prompt-injection detector. "
                "scope = '*' или provider-id (S11 K1 W2)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.model_registry.read",
            matcher=dot_glob,
            description=(
                "Чтение из AI Model Registry (MLflow + HF Hub composite); "
                "scope = backend-id или '*' (S11 K4 W6)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.model_registry.write",
            matcher=dot_glob,
            description=(
                "Запись/promote в AI Model Registry. "
                "scope = backend-id или '*' (S11 K4 W6)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.feedback.train",
            matcher=exact,
            description=(
                "Запуск DSPy training-loop по labeled feedback "
                "+ публикация prompt-version (S11 K4 W5)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.route.optimize",
            matcher=dot_glob,
            description=(
                "AI-анализ route-метрик + генерация PR markdown "
                "(S11 K4 W7); scope = route-name или '*'."
            ),
        )
    )
    # ─── Sprint 24 — AI Safety Hardening capabilities (ADR-NEW-16/17/18) ─
    vocab.register(
        CapabilityDef(
            name="pii.read",
            matcher=dot_glob,
            description=(
                "Чтение текста через PII-detector pipeline (Presidio + ru NER) "
                "перед маскированием/anonymize; scope = tenant-id или '*' "
                "(S24 W1, ADR-NEW-16)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="pii.write",
            matcher=dot_glob,
            description=(
                "Запись маскированных payload-ов в outbound LLM / RAG / DLQ / "
                "Langfuse traces; scope = tenant-id или '*' (S24 W1, ADR-NEW-16)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="pii.audit",
            matcher=dot_glob,
            description=(
                "Запись audit-event pii.{detected,anonymized,blocked} с tenant_id "
                "+ entity_type + redacted_hash в immutable Postgres audit-sink; "
                "scope = tenant-id или '*' (S24 W1, ADR-NEW-16)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrail.evaluate",
            matcher=dot_glob,
            description=(
                "Вызов defense-in-depth guardrails pipeline "
                "(NeMo Colang input rails + Llama Guard 3 output classifier); "
                "scope = tenant-id или '*' (S24 W2, ADR-NEW-17)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrail.policy_read",
            matcher=dot_glob,
            description=(
                "Чтение per-tenant guardrail policy "
                "(NeMo/LlamaGuard/Rebuff/Lakera enable map) из tenant_config.py; "
                "scope = tenant-id или '*' (S24 W2, ADR-NEW-17)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.memory.read",
            matcher=dot_glob,
            description=(
                "Чтение из MemoryProtocol (LangGraph Checkpointer / Mem0 / AgentMemory); "
                "namespace = '<tenant_id>:<scope>'; scope = tenant-id или '*' "
                "(S24 W3, ADR-NEW-18)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.memory.write",
            matcher=dot_glob,
            description=(
                "Запись в MemoryProtocol; namespace = '<tenant_id>:<scope>'; "
                "scope = tenant-id или '*' (S24 W3, ADR-NEW-18)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.memory.delete",
            matcher=dot_glob,
            description=(
                "Удаление user-memory из MemoryProtocol (GDPR / 152-ФЗ "
                "user-erasure); scope = tenant-id или '*' (S24 W3, ADR-NEW-18)."
            ),
        )
    )
    return vocab
