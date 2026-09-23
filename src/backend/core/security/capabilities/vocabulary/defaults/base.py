"""Base capabilities registration (S50 M2-#5 split).

Извлечено из defaults.py (S62 W2 single-file → Sprint 50 sub-package split).
"""

from __future__ import annotations

from src.backend.core.security.capabilities.matchers import (
    ExactAliasMatcher,
    GlobScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)
from src.backend.core.security.capabilities.vocabulary.models import CapabilityDef
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,
)


def register(vocab: CapabilityVocabulary) -> None:
    """Register base capabilities (db, net, fs, mq, cache, workflow, llm)."""
    exact = ExactAliasMatcher()
    dot_glob = GlobScopeMatcher()
    path_glob = SegmentedGlobMatcher(sep="/")
    cache_glob = SegmentedGlobMatcher(sep=":")
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
    # P3 S172 W2: message-level claim-check capability (EIP ClaimCheckProcessor).
    vocab.register(
        CapabilityDef(
            name="message.claim_check.store",
            matcher=exact,
            description=(
                "Сохранение claim token в Redis/S3 через EIP ClaimCheckProcessor "
                "store-режим (message-level payload offload)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="message.claim_check.retrieve",
            matcher=exact,
            description=(
                "Восстановление payload по claim token через EIP "
                "ClaimCheckProcessor retrieve-режим."
            ),
        )
    )
    # P3 S172 W2: Temporal workflow best-practices capabilities.
    vocab.register(
        CapabilityDef(
            name="workflow.claim_check.store",
            matcher=exact,
            description=(
                "Сохранение Temporal workflow payload через WorkflowClaimCheckProcessor "
                "(Temporal best practice для больших event-history)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="workflow.continue_as_new.request",
            matcher=exact,
            description=(
                "Запрос Continue-As-New в Temporal workflow "
                "(Temporal best practice для долгоживущих executions)."
            ),
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
