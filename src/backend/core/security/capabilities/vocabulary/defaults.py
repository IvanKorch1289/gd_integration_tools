from __future__ import annotations

from src.backend.core.security.capabilities.matchers import (
    ExactAliasMatcher,
    GlobScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)
from src.backend.core.security.capabilities.vocabulary.models import (
    CapabilityDef,  # S62 W2: cross-import
)
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,  # S62 W2: cross-import
)

"""S62 W2 — defaults.py part of vocabulary decomp.

build_default_vocabulary (388 LOC, BIG function).
"""


def _build_base_capabilities(
    vocab: CapabilityVocabulary,
    exact: ExactAliasMatcher,
    dot_glob: GlobScopeMatcher,
    path_glob: SegmentedGlobMatcher,
    cache_glob: SegmentedGlobMatcher,
    uri: URISchemeMatcher,
) -> None:
    """Register base capabilities (db, net, fs, mq, cache, workflow, llm, etc.)."""
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
            name="db.execute_procedure",
            matcher=dot_glob,
            description="Вызов stored procedure во внешней БД через ExternalDatabaseFacade.",
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
            aliases=("fs.create_new",),
            description=(
                "Унифицированная запись файлов. "
                "fs.create_new — deprecated alias (post-S20 removal). "
                "Scope: fs.write.workspace.<session_id> для AI-workspaces; "
                "fs.write.tenant.<tenant_id> / fs.write.repo.<area> для системных."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="storage.read",
            matcher=path_glob,
            description="Чтение из объектного хранилища через StorageFacade (key/prefix).",
        )
    )
    vocab.register(
        CapabilityDef(
            name="storage.write",
            matcher=path_glob,
            description="Запись/удаление в объектном хранилище через StorageFacade (key).",
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


def _build_ai_rag_capabilities(
    vocab: CapabilityVocabulary, exact: ExactAliasMatcher, dot_glob: GlobScopeMatcher
) -> None:
    """Register Sprint 11 AI/RAG Completion capabilities."""
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


def _build_ai_safety_capabilities(
    vocab: CapabilityVocabulary, dot_glob: GlobScopeMatcher
) -> None:
    """Register Sprint 24 AI Safety Hardening capabilities."""
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


def _build_ai_platform_capabilities(
    vocab: CapabilityVocabulary,
    dot_glob: GlobScopeMatcher,
    path_glob: SegmentedGlobMatcher,
) -> None:
    """Register Sprint 25-27 AI Platform Layer capabilities."""
    vocab.register(
        CapabilityDef(
            name="ai.invoke",
            matcher=dot_glob,
            description=(
                "Вызов LLM через единую точку входа AIGateway (ADR-NEW-19). "
                "Проверяется на каждый AIGateway.invoke(request.workflow_id); "
                "scope = workflow_id pattern или '*' (S25 W1)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.policy.read",
            matcher=dot_glob,
            description=(
                "Чтение AIPolicySpec из ai_policies/*.policy.yaml через "
                "PolicyResolver (ADR-NEW-20); scope = policy-name pattern "
                "или '*' (S25 W2)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="pii.tokenize.reversible",
            matcher=dot_glob,
            description=(
                "Reversible PII-токенизация через PIITokenizer (Presidio + "
                "AES-GCM TokenRegistry); обязательна для unmask round-trip "
                "(ADR-NEW-21). scope = domain-id (banking, hr, medical) или '*' "
                "(S25 W4)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="mcp.gateway.invoke",
            matcher=dot_glob,
            description=(
                "Вызов tool через MCPGateway namespace (credit/analytics/"
                "system) с auth + WAF (ADR-NEW-23); scope = namespace-name "
                "или '*' (S27 W4)."
            ),
        )
    )
    # Per-namespace capabilities (ADR-0070 §1, S27 W4)
    for _ns_name in ("credit", "analytics", "system"):
        vocab.register(
            CapabilityDef(
                name=f"mcp.gateway.invoke.{_ns_name}",
                matcher=dot_glob,
                description=(
                    f"Вызов tool в namespace '{_ns_name}' через MCPGateway "
                    f"(ADR-0070, S27 W4); scope = tool-name или '*'."
                ),
            )
        )
    vocab.register(
        CapabilityDef(
            name="skill.invoke",
            matcher=dot_glob,
            description=(
                "Вызов AI skill через SkillRegistry (ADR-NEW-22, S26 W5); "
                "scope = skill-id pattern (``credit.score.calculate``, "
                "``credit.*``) или '*' (S27 W3 DSL .skill_invoke())."
            ),
        )
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

    _build_base_capabilities(vocab, exact, dot_glob, path_glob, cache_glob, uri)
    _build_ai_rag_capabilities(vocab, exact, dot_glob)
    _build_ai_safety_capabilities(vocab, dot_glob)
    _build_ai_platform_capabilities(vocab, dot_glob, path_glob)

    return vocab
