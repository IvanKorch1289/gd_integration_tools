# V2 Итерация 8: Cross-cutting — фактические находки

## Context propagation — точные точки разрыва

| Компонент | Файл | Строки | Факт |
|-----------|------|--------|------|
| InvokeWorkflowProcessor | `dsl/engine/processors/invoke_workflow.py` | 159-179 | Передаёт только `workflow_name`, `workflow_id`, `input=payload`. **Нет** `tenant_id`, `correlation_id`, `traceparent` |
| Emitter | `dsl/workflow/compiler/emitter.py` | 91-99 | `ctx` содержит `_input`, `_outputs`, `_signals`. **Нет** `tenant_id`, `correlation_id`, `trace_id` |
| SkillRegistry.invoke | `core/ai/skill_registry.py` | 203-291 | Сигнатура `invoke(self, skill_id, **kwargs)`. **Нет** context/tenant_id/correlation_id |
| SkillInvokeProcessor | `dsl/engine/processors/agent_dsl/skill_invoke.py` | 76-87 | `del context` (!) — ExecutionContext **полностью игнорируется** |

## Feature flags
- **240** total (все поля `AnnAssign` в `core/config/features/`)
- **13** default=True (все в `features/ai_rag.py`)
- **224** default=False
- **3** non-bool

## SLO enforcement
- `SLOTracker` — только запись метрик + Prometheus export
- **Нет** middleware/gate для отклонения запросов при превышении SLO
- `execution_engine.py:159-168` — только `record()` после выполнения

## OTel + Temporal
- `temporal_client.py:119`, `temporal_backend.py:123` — `Client.connect` **без** `interceptors=`
- Поиск `interceptor` в `infrastructure/workflow/` — **0 совпадений**
- `StepAuditMiddleware` — ручная установка span-атрибутов, **не** Temporal interceptor

## Graceful shutdown
- `lifecycle.py:601-1142` — shutdown workflow, outbox, AI safety, loaders, plugins, log sinks
- **Нет** HTTP drain (закрытия активных HTTP-соединений)
- `main.py:44-71` — `uvicorn.run()` без `timeout_graceful_shutdown`
- `base.py:76-157` — нет поля `graceful_shutdown_timeout`
