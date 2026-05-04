# Capability catalog (V11 / ADR-044)

Сгенерировано `tools/export_v11_artefacts.py capability-catalog`. Не редактировать вручную.

| Capability | scope_required | matcher | public | Описание |
|---|---|---|---|---|
| `cache.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение кэша через CacheFacade (namespace по ':'). |
| `cache.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись в кэш через CacheFacade (namespace по ':'). |
| `db.read` | ✅ | `ExactAliasMatcher` | ➖ | Чтение из БД через DatabaseFacade (read-only-сессия). |
| `db.write` | ✅ | `ExactAliasMatcher` | ➖ | Запись в БД через DatabaseFacade (rw-сессия). |
| `fs.read` | ✅ | `SegmentedGlobMatcher` | ➖ | Чтение файлов через FSFacade (path-glob по '/'). |
| `fs.write` | ✅ | `SegmentedGlobMatcher` | ➖ | Запись файлов через FSFacade (path-glob по '/'). |
| `llm.invoke` | ✅ | `SegmentedGlobMatcher` | ➖ | Вызов LLM-провайдера через LLMFacade (provider/model по '/'). |
| `mq.consume` | ✅ | `GlobScopeMatcher` | ➖ | Подписка на сообщения через MQFacade (topic-glob). |
| `mq.publish` | ✅ | `GlobScopeMatcher` | ➖ | Публикация сообщений через MQFacade (topic-glob). |
| `net.inbound` | ✅ | `GlobScopeMatcher` | ➖ | Регистрация webhook/SSE-эндпоинтов через WebhookFacade. |
| `net.outbound` | ✅ | `GlobScopeMatcher` | ➖ | Исходящие HTTP/gRPC через {HTTP,GRPC}Facade. |
| `secrets.read` | ✅ | `URISchemeMatcher` | ➖ | Чтение секрета через SecretsFacade (vault:// / env:// / kms://). |
| `workflow.signal` | ✅ | `GlobScopeMatcher` | ➖ | Сигнал workflow через WorkflowFacade. |
| `workflow.start` | ✅ | `GlobScopeMatcher` | ➖ | Запуск workflow через WorkflowFacade (workflow_id-glob). |
