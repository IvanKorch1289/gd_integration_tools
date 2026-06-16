# Capability catalog (V11 / ADR-044)

Сгенерировано `tools/export_v11_artefacts.py capability-catalog`. Не редактировать вручную.

| Capability | scope_required | matcher | public | Описание |
|---|---|---|---|---|
| `ai.feedback.train` | ✅ | `ExactAliasMatcher` | ➖ | Запуск DSPy training-loop по labeled feedback + публикация prompt-version (S11 K4 W5). |
| `ai.guardrail.evaluate` | ✅ | `GlobScopeMatcher` | ➖ | Вызов defense-in-depth guardrails pipeline (NeMo Colang input rails + Llama Guard 3 output classifier); scope = tenant-id или '*' (S24 W2, ADR-NEW-17). |
| `ai.guardrail.policy_read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение per-tenant guardrail policy (NeMo/LlamaGuard/Rebuff/Lakera enable map) из tenant_config.py; scope = tenant-id или '*' (S24 W2, ADR-NEW-17). |
| `ai.guardrails.lakera` | ✅ | `GlobScopeMatcher` | ➖ | Вызов Lakera Guard prompt-injection / PII detector. scope = '*' или конкретный provider-id (S11 K1 W2). |
| `ai.guardrails.rebuff` | ✅ | `GlobScopeMatcher` | ➖ | Вызов Rebuff prompt-injection detector. scope = '*' или provider-id (S11 K1 W2). |
| `ai.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов LLM через единую точку входа AIGateway (ADR-NEW-19). Проверяется на каждый AIGateway.invoke(request.workflow_id); scope = workflow_id pattern или '*' (S25 W1). |
| `ai.memory.delete` | ✅ | `GlobScopeMatcher` | ➖ | Удаление user-memory из MemoryProtocol (GDPR / 152-ФЗ user-erasure); scope = tenant-id или '*' (S24 W3, ADR-NEW-18). |
| `ai.memory.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение из MemoryProtocol (LangGraph Checkpointer / Mem0 / AgentMemory); namespace = '<tenant_id>:<scope>'; scope = tenant-id или '*' (S24 W3, ADR-NEW-18). |
| `ai.memory.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись в MemoryProtocol; namespace = '<tenant_id>:<scope>'; scope = tenant-id или '*' (S24 W3, ADR-NEW-18). |
| `ai.model_registry.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение из AI Model Registry (MLflow + HF Hub composite); scope = backend-id или '*' (S11 K4 W6). |
| `ai.model_registry.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись/promote в AI Model Registry. scope = backend-id или '*' (S11 K4 W6). |
| `ai.policy.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение AIPolicySpec из ai_policies/*.policy.yaml через PolicyResolver (ADR-NEW-20); scope = policy-name pattern или '*' (S25 W2). |
| `ai.rag.pii_redaction` | ✅ | `ExactAliasMatcher` | ➖ | Применение PII-маскера к augment_result.documents[*].content в RAG retrieval pipeline (S11 K1 W1). |
| `ai.route.optimize` | ✅ | `GlobScopeMatcher` | ➖ | AI-анализ route-метрик + генерация PR markdown (S11 K4 W7); scope = route-name или '*'. |
| `ai.stream` | ✅ | `SegmentedGlobMatcher` | ➖ | Token-level streaming LLM (SSE/WS) через LLMStreamingService (scope = 'model:<prefix>', optional). |
| `cache.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение кэша через CacheFacade (namespace по ':'). |
| `cache.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись в кэш через CacheFacade (namespace по ':'). |
| `code.execute` | ✅ | `ExactAliasMatcher` | ➖ | Запуск пользовательского кода в sandbox (e2b/pyodide) через CodeSandbox; прямой subprocess запрещён (V15 R-V15-4). |
| `db.execute_procedure` | ✅ | `GlobScopeMatcher` | ➖ | Вызов stored procedure во внешней БД через ExternalDatabaseFacade. |
| `db.read` | ✅ | `ExactAliasMatcher` | ➖ | Чтение из БД через DatabaseFacade (read-only-сессия). |
| `db.write` | ✅ | `ExactAliasMatcher` | ➖ | Запись в БД через DatabaseFacade (rw-сессия). |
| `fs.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение файлов через FSFacade (path-glob по '/'). |
| `fs.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Унифицированная запись файлов. fs.create_new — deprecated alias (post-S20 removal). Scope: fs.write.workspace.<session_id> для AI-workspaces; fs.write.tenant.<tenant_id> / fs.write.repo.<area> для системных. |
| `langmem.admin` | ✅ | `ExactAliasMatcher` | ➖ | Администрирование LangMem: consolidate(), stats(), RLM reset (D.6). |
| `llm.invoke` | ✅ | `SegmentedGlobMatcher` | ➖ | Вызов LLM-провайдера через LLMFacade (provider/model по '/'). |
| `mcp.gateway.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool через MCPGateway namespace (credit/analytics/system) с auth + WAF (ADR-NEW-23); scope = namespace-name или '*' (S27 W4). |
| `mcp.gateway.invoke.analytics` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool в namespace 'analytics' через MCPGateway (ADR-0070, S27 W4); scope = tool-name или '*'. |
| `mcp.gateway.invoke.credit` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool в namespace 'credit' через MCPGateway (ADR-0070, S27 W4); scope = tool-name или '*'. |
| `mcp.gateway.invoke.system` | ✅ | `GlobScopeMatcher` | ➖ | Вызов tool в namespace 'system' через MCPGateway (ADR-0070, S27 W4); scope = tool-name или '*'. |
| `mcp.tool.call` | ✅ | `GlobScopeMatcher` | ➖ | Вызов MCP-инструмента (FastMCP HTTP transport); scope = action-name pattern. |
| `mq.consume` | ✅ | `GlobScopeMatcher` | ➖ | Подписка на сообщения через MQFacade (topic-glob). |
| `mq.publish` | ✅ | `GlobScopeMatcher` | ➖ | Публикация сообщений через MQFacade (topic-glob). |
| `net.inbound` | ✅ | `GlobScopeMatcher` | ➖ | Регистрация webhook/SSE-эндпоинтов через WebhookFacade. |
| `net.outbound` | ✅ | `GlobScopeMatcher` | ➖ | Исходящие HTTP/gRPC через {HTTP,GRPC}Facade. |
| `pii.audit` | ✅ | `GlobScopeMatcher` | ➖ | Запись audit-event pii.{detected,anonymized,blocked} с tenant_id + entity_type + redacted_hash в immutable Postgres audit-sink; scope = tenant-id или '*' (S24 W1, ADR-NEW-16). |
| `pii.read` | ✅ | `GlobScopeMatcher` | ➖ | Чтение текста через PII-detector pipeline (Presidio + ru NER) перед маскированием/anonymize; scope = tenant-id или '*' (S24 W1, ADR-NEW-16). |
| `pii.tokenize.reversible` | ✅ | `GlobScopeMatcher` | ➖ | Reversible PII-токенизация через PIITokenizer (Presidio + AES-GCM TokenRegistry); обязательна для unmask round-trip (ADR-NEW-21). scope = domain-id (banking, hr, medical) или '*' (S25 W4). |
| `pii.write` | ✅ | `GlobScopeMatcher` | ➖ | Запись маскированных payload-ов в outbound LLM / RAG / DLQ / Langfuse traces; scope = tenant-id или '*' (S24 W1, ADR-NEW-16). |
| `secrets.read` | ✅ | `URISchemeMatcher` | ➖ | Чтение секрета через SecretsFacade (vault:// / env:// / kms://). |
| `skill.invoke` | ✅ | `GlobScopeMatcher` | ➖ | Вызов AI skill через SkillRegistry (ADR-NEW-22, S26 W5); scope = skill-id pattern (``credit.score.calculate``, ``credit.*``) или '*' (S27 W3 DSL .skill_invoke()). |
| `storage.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение из объектного хранилища через StorageFacade (key/prefix). |
| `storage.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись/удаление в объектном хранилище через StorageFacade (key). |
| `workflow.signal` | ✅ | `GlobScopeMatcher` | ➖ | Сигнал workflow через WorkflowFacade. |
| `workflow.start` | ✅ | `GlobScopeMatcher` | ➖ | Запуск workflow через WorkflowFacade (workflow_id-glob). |
