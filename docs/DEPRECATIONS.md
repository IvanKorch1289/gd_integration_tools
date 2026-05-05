# Deprecation Log

Регистр deprecation-shim и планируемых к удалению публичных путей/модулей.

Формат строки таблицы:

| Путь/Имя | Заменён на | Введён (фаза/дата) | Плановое удаление | Тип |
|---|---|---|---|---|

## Активные shim

| Путь/Имя | Заменён на | Введён (фаза/дата) | Плановое удаление | Тип |
|---|---|---|---|---|
| `src.infrastructure.workflow.runner.DurableWorkflowRunner` (pg-runner direct use) | `src.core.workflow.WorkflowBackend` (Protocol через DI) + `src.services.workflows.WorkflowFacade` (capability gate) | Wave D / 2026-05-04 | R3 (после полной миграции existing OrderWorkflow на Temporal) | API surface |
| `src.workflows.orders_dsl` (pg-runner-specific) | Будет переписан под Temporal-determinism (см. `tools/migrate_workflow_v11.py`) | Wave D / 2026-05-04 | R3 / OrderWorkflow domain-плагин | module |
| `app.core.service_registry` (module) | `app.core.svcs_registry` | A3 / 2026-04-21 | 2026-07-01 (H3 Cleanup) | module |
| `app.core.service_registry.ServiceRegistry` | `app.core.svcs_registry.register_factory/get_service/list_services` | A3 / 2026-04-21 | 2026-07-01 | class |
| `app.core.service_registry.service_registry` (singleton) | `app.core.svcs_registry.register_factory/get_service` | A3 / 2026-04-21 | 2026-07-01 | singleton |
| `app.infrastructure.clients.transport.http.HttpClient` (aiohttp) | `app.infrastructure.clients.transport.http_httpx.HttpxClient` | A4 / 2026-04-21 | 2026-07-01 (H3) | class/module |
| `app.dsl.engine.processors.control_flow.RetryProcessor` (custom loop) | wraps `tenacity.AsyncRetrying` | A4 / 2026-04-21 | поведение совместимо — удаление не планируется | class |
| `app.infrastructure.clients.transport.soap` (zeep) | `soap_async.AsyncSoapClient` | C11 / 2026-04-21 | 2026-07-01 (H3) | module |

## Удалённые (для истории)

| Путь/Имя | Заменён на | Введён (фаза/дата) | Удалено (фаза/дата) | Тип |
|---|---|---|---|---|
| `app.workflows.utils.managed_pause` (Prefect `suspend_flow_run`) | `WorkflowBuilder.wait(duration_s=N)` + DurableWorkflowRunner | IL-WF3 / 2026-04-22 | Wave F.1 / 2026-05-01 | function |
| `app.workflows.tasks` (Prefect `@task`) | `app.workflows.orders_dsl._call_*` processors | IL-WF3 / 2026-04-22 | Wave F.1 / 2026-05-01 | module |
| `app.workflows.order_flows` (Prefect `@flow`) | `app.workflows.orders_dsl.build_all_order_workflows()` | IL-WF3 / 2026-04-22 | Wave F.1 / 2026-05-01 | module |
| `app.workflows.task_factory.create_service_task` (Prefect auto-gen) | MCP auto-export via `app.entrypoints.mcp.workflow_tools.register_workflow_tools` | IL-WF3 / 2026-04-22 | Wave F.1 / 2026-05-01 | function |
| `prefect` (pyproject.toml dependency) | `app.infrastructure.workflow.*` + `app.workflows.orders_dsl` (DSL durable engine, ADR-031) | IL-WF3 / 2026-04-22 | Wave F.1 / 2026-05-01 | dependency |

---

**Правила:**

1. Любой shim должен содержать `warnings.warn(DeprecationWarning, ...)` с указанием фазы удаления.
2. Удаление — не позже 1 релиза (или в фазе H3 Cleanup, что раньше).
3. Строка из «Активные shim» переносится в «Удалённые» одновременно с коммитом, удаляющим shim.
4. Пропущенная дата удаления — основание для нового тикета cleanup и фейла `creosote`/`vulture` в CI.
