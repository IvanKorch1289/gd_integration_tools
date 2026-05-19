# Capability catalog (V11 / ADR-044)

Сгенерировано `tools/export_v11_artefacts.py capability-catalog`. Не редактировать вручную.

| Capability | scope_required | matcher | public | Описание |
|---|---|---|---|---|
| `ai.stream` | ✅ | `SegmentedGlobMatcher` | ➖ | Token-level streaming LLM (SSE/WS) через LLMStreamingService (scope = 'model:<prefix>', optional). |
| `cache.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение кэша через CacheFacade (namespace по ':'). |
| `cache.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись в кэш через CacheFacade (namespace по ':'). |
| `code.execute` | ✅ | `ExactAliasMatcher` | ➖ | Запуск пользовательского кода в sandbox (e2b/pyodide) через CodeSandbox; прямой subprocess запрещён (V15 R-V15-4). |
| `db.read` | ✅ | `ExactAliasMatcher` | ➖ | Чтение из БД через DatabaseFacade (read-only-сессия). |
| `db.write` | ✅ | `ExactAliasMatcher` | ➖ | Запись в БД через DatabaseFacade (rw-сессия). |
| `fs.create_new` | ✅ | `SegmentedGlobMatcher` | ➖ | Создание нового файла в AI workspace через AIFsFacade (non-overwriting; запись существующих файлов запрещена, V15 R-V15-4). |
| `fs.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение файлов через FSFacade (path-glob по '/'). |
| `fs.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись файлов через FSFacade (path-glob по '/'). |
| `langmem.admin` | ✅ | `ExactAliasMatcher` | ➖ | Администрирование LangMem: consolidate(), stats(), RLM reset (D.6). |
| `llm.invoke` | ✅ | `SegmentedGlobMatcher` | ➖ | Вызов LLM-провайдера через LLMFacade (provider/model по '/'). |
| `mcp.tool.call` | ✅ | `GlobScopeMatcher` | ➖ | Вызов MCP-инструмента (FastMCP HTTP transport); scope = action-name pattern. |
| `mq.consume` | ✅ | `GlobScopeMatcher` | ➖ | Подписка на сообщения через MQFacade (topic-glob). |
| `mq.publish` | ✅ | `GlobScopeMatcher` | ➖ | Публикация сообщений через MQFacade (topic-glob). |
| `net.inbound` | ✅ | `GlobScopeMatcher` | ➖ | Регистрация webhook/SSE-эндпоинтов через WebhookFacade. |
| `net.outbound` | ✅ | `GlobScopeMatcher` | ➖ | Исходящие HTTP/gRPC через {HTTP,GRPC}Facade. |
| `secrets.read` | ✅ | `URISchemeMatcher` | ➖ | Чтение секрета через SecretsFacade (vault:// / env:// / kms://). |
| `workflow.signal` | ✅ | `GlobScopeMatcher` | ➖ | Сигнал workflow через WorkflowFacade. |
| `workflow.start` | ✅ | `GlobScopeMatcher` | ➖ | Запуск workflow через WorkflowFacade (workflow_id-glob). |
