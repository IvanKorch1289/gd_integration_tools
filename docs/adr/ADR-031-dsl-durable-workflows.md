# ADR-031 — Durable Workflows через DSL (замена Prefect)

* **Статус:** Superseded by [ADR-045](ADR-045-temporal-migration-spec.md)
* **Дата:** 2026-04-22 (accepted) / 2026-05-04 (superseded после Wave D)
* **Фаза:** IL-WF1 (Workflow engine — замена Prefect) → R1 Wave D (Temporal migration)
* **Связанные ADR:** ADR-001 (DSL central abstraction), ADR-011 (Outbox pattern), ADR-022 (ConnectorRegistry), ADR-045 (Temporal как default backend).
* **Автор:** claude

> **2026-05-04 supersedure note:** Wave D ввёл `WorkflowBackend`
> Protocol (ADR-045) с двумя impl'ами: Temporal как default + pg-runner
> как fallback. Решения этого ADR-031 (event-sourcing в PG, LISTEN/NOTIFY,
> APScheduler) **остаются валидными** в `PgRunnerWorkflowBackend` —
> используется в dev_light и как graceful degradation. Новые domains
> ДОЛЖНЫ выбирать Temporal через `WorkflowFacade`; existing OrderWorkflow
> работает на pg-runner до отдельной миграции (R3).

## Контекст

Проект использует Prefect 3.2 для long-running async workflows
(order processing, SKB polling, notifications). Prefect даёт базовый
retry + `managed_pause` через `suspend_flow_run`, но несёт:

1. **Heavy dep** — ~80MB + транзитивные (pendulum, apprise, async-timeout).
2. **Хаки для async** — `managed_pause` при hard-cancel оставляет state в
   непредсказуемом виде, полагается на Prefect Server.
3. **Отдельный UI/Server** — дублирует возможности нашего Streamlit /
   Prometheus / Grafana.
4. **Ограниченный control flow** — есть retry/tasks, но нет declarative
   branching / loops / sub-workflows в идиоматичном виде.
5. **Нет native durability без Prefect Server** — flows хранят state в
   Prefect orchestration layer, не в наших Postgres таблицах.

После Camel-подобного DSL (ADR-001) и 158 процессоров всё, что делает
Prefect, может быть выражено как declarative workflow в нашем DSL.

### Новые требования пользователя (2026-04-22)

1. **Воркфлоу — отдельные сущности**, вызываемые через любой transport:
   REST / SOAP / gRPC / RabbitMQ / Kafka. Унифицированный triggering.
2. **Доступны как tools для AI-агентов** (MCP auto-export). CrewAI /
   LangChain / LangGraph могут вызывать workflow как обычный tool.
3. **Ветвления / циклы / дочерние воркфлоу / работа в фоне / отдельные
   воркеры**.
4. **Hybrid workers**: API пишет в БД, workers слушают `LISTEN/NOTIFY`
   (`pg_notify('workflow_pending', id)`), backup polling каждые 30s.
5. **Event sourcing** (append-only `workflow_events`): state — fold
   событий; snapshot compaction каждые N событий.
6. **Hot-reload spec + hard cancel**: running instance читает свежий
   spec из RouteRegistry; cancel через `asyncio.Task.cancel()` + compensate.

## Решение

### 1. Data model (event-sourced)

```
workflow_instances   (thin header, mutable)
    id, workflow_name, route_id, status,
    current_version, last_event_seq,
    snapshot_state JSONB, next_attempt_at,
    locked_by, locked_until,
    tenant_id, input_payload,
    created_at, updated_at, finished_at

workflow_events      (append-only, immutable source of truth)
    seq BIGSERIAL PK (глобально уникальная),
    workflow_id FK → workflow_instances.id,
    event_type ENUM(created, step_started, step_finished, step_failed,
                    branch_taken, loop_iter, sub_spawned, sub_completed,
                    paused, resumed, cancelled, compensated, snapshotted),
    payload JSONB,
    step_name VARCHAR NULL,
    occurred_at TIMESTAMPTZ
```

State reconstruction: `SELECT * FROM workflow_events WHERE workflow_id=?
ORDER BY seq` → fold → `WorkflowState`. Snapshot каждые 50 событий →
`workflow_instances.snapshot_state` для ускоренного replay.

### 2. Hybrid workers (LISTEN/NOTIFY + polling)

```
  API / Consumer / MCP tool
     │
     ▼  create instance → INSERT workflow_events(event_type="created")
  TRIGGER fn_workflow_notify
     │   pg_notify('workflow_pending', workflow_id::text)
     ▼
  ┌────────────────────────────────┐      ┌────────────────────────┐
  │ Worker pod (asyncpg listener)  │ ───► │ pg_try_advisory_lock   │
  │ event-driven execution         │      │ (hash(workflow_id))    │
  └────────────────────────────────┘      └────────────────────────┘
                    ▲
                    │  backup polling каждые 30s (safety net)
                    ▼
                SELECT pending instances ...
```

Advisory lock (per workflow_id) предотвращает double-execution при
одновременном notify + polling.

### 3. Unified trigger через любой transport

Workflow регистрируется в `WorkflowRegistry` **И** в `ActionHandlerRegistry`
(как action с type=`workflow`):

```python
# src/workflows/orders_skb.py
@workflow(
    name="orders.skb_flow",
    input_schema=OrderIn,
    output_schema=OrderResult,
    max_attempts=10,
    backoff="exponential",
)
def build() -> Pipeline:
    return (
        WorkflowBuilder.from_(...)
        .branch(when="$.amount > 100000",
                then=[_.sub_workflow("kyc.enhanced")],
                else_=[_.sub_workflow("kyc.basic")])
        .loop(while_="$.skb_result is null",
              body=[_.http_call("...", url="..."),
                    _.wait(timedelta(minutes=5))],
              max_iter=288)
        .for_each(collection="$.items", body=[...], parallel=True)
        .compensate_with([...])
        .build()
    )
```

Registry auto-binds к `ActionHandlerRegistry` + MCP server:
- `dispatch_action(action="orders.skb_flow", source="rest")` → creates instance.
- Return value для `wait=False`: `WorkflowInstanceRef(id, status="pending")`.
- Return value для `wait=True` (sync triggering): blocks on Postgres
  `LISTEN workflow_done_{id}` до completion (max-wait настраиваемый).

**Transports:**

| Transport | Pattern |
|---|---|
| REST | `POST /api/v1/workflows/{name}/trigger` body=input, returns instance_id |
| gRPC | `TriggerWorkflow(name, input, wait)` — proto in `workflows.proto` |
| SOAP | operation `triggerWorkflow` в `/soap/workflows.wsdl` |
| RabbitMQ | consumer на queue `workflows.trigger.{name}` |
| Kafka | consumer на topic `workflows.trigger` (routing key = name) |
| MCP | auto-registered как tool `workflow_{name}` — JSON Schema из input_schema |
| AI-agent | `agent.with_tools([workflow_orders_skb_flow, ...])` через MCP |

### 4. Control flow primitives (DSL)

Все — extensions `RouteBuilder` через mixin `WorkflowBuilderMixin`:

| Метод | Semantics |
|---|---|
| `.durable(steps, max_attempts, backoff, compensate)` | wrap в DurableWorkflowProcessor |
| `.branch(when, then, else_)` | condition: JMESPath / typed predicate; state branch persist-ится как event `branch_taken` |
| `.loop(while_, body, max_iter)` | while-loop с hard-cap `max_iter`; каждая итерация — event `loop_iter` |
| `.for_each(collection, body, parallel, max_concurrent)` | map over collection; parallel=True использует asyncio.gather с semaphore |
| `.sub_workflow(name, input_map, output_map, wait=True)` | sync child: pauses parent до child complete; events `sub_spawned`, `sub_completed` |
| `.trigger_workflow(name, wait=False, correlation_id=...)` | fire-and-forget, parent получает ref, не блокируется |
| `.wait(duration \| until_callable)` | durable pause; `next_attempt_at = now() + duration`, worker отпускает lock, возобновляется когда NOTIFY придёт |
| `.compensate_with(steps)` | saga compensation: выполняется при failure/cancel |
| `.human_approval(group, timeout)` | HITL: pause до внешнего approve/reject event |

### 5. Hot-reload spec + hard cancel

**Hot-reload**: worker на каждом step читает spec из `RouteRegistry.get(route_id)`
свежим. Если admin обновил YAML (через dev-panel или git deploy + reload),
running instance подхватывает новую версию на следующем step. Старые
события в `workflow_events` неизменны — возможно несоответствие
с current spec, но это `upgrade_compatible` ситуация (пользователь
отвечает за backward-compat новых spec).

**Hard cancel**: `POST /admin/workflows/{id}/cancel` →
`status='cancelling'` → next NOTIFY → worker проверяет → отменяет
текущий step (`asyncio.Task.cancel()`) → compensate_with → event
`cancelled`. Партиальные side-effects идемпотентно покрыты
compensate-цепочкой.

### 6. Agent tools integration (MCP)

MCP server (`src/entrypoints/mcp/mcp_server.py`) **автоматически**
экспортирует зарегистрированные workflows как tools:

```python
# generated MCP tool:
@mcp_server.tool(name="workflow_orders_skb_flow")
async def trigger_orders_skb_flow(
    input: OrderInSchema,
    wait: bool = False,
    timeout_s: int = 300,
) -> OrderResultSchema | WorkflowInstanceRef:
    return await workflow_registry.trigger(
        name="orders.skb_flow",
        input=input.model_dump(),
        wait=wait,
        timeout_s=timeout_s,
        source="mcp",
    )
```

AI-агенты (CrewAI / LangChain / LangGraph) видят workflow как обычный
tool с JSON schema input/output, могут вызывать с `wait=True` (sync) или
`wait=False` (async с polling instance_id).

## Последствия

### Положительные

- **`-80MB` deps** (prefect + транзитивные).
- **Единый uniform transport**: REST/SOAP/gRPC/Rabbit/Kafka/MCP
  диспатчат workflow через один и тот же `dispatch_action()`.
- **Agent-native**: workflows автоматически tools для LLM-агентов без
  wrapping layer.
- **Durability on OUR Postgres** — нет зависимости от Prefect Server;
  backup / replication / DR — стандартные PG процедуры.
- **Event sourcing = бесплатный audit log** + replay для debugging.
- **RED metrics + OTEL tracing unified** с остальным infrastructure.
- **DSL-first**: visualization / linting / import / codegen (BPMN / OpenAPI)
  применяются к workflows.

### Отрицательные

- **~3500 LOC новый код**. 8 чанков (IL-WF1.0 — IL-WF1.4 + IL-WF2.* + IL-WF3 + IL-WF4).
- **Event sourcing complexity**: snapshot compaction + replay-consistency
  при concurrent modifications — нетривиально.
- **Advisory locks** — `pg_try_advisory_lock(hash(uuid))` — теоретический
  hash collision (практически 1 к 2⁶³), мitigируется проверкой `workflow_id`
  в `locked_by`.
- **Нет Prefect Cloud UI** — заменяется Streamlit `/admin/workflows` + Grafana.
- **Нет готовых 3rd-party tasks** (AWS/GCP/Slack Prefect libraries) —
  они и так не используются, все внешние вызовы через `http_call` / connectors.

## DoD ADR-031

- [ ] IL-WF1.0: ADR-031 в `docs/adr/ADR-031-dsl-durable-workflows.md` (этот файл).
- [ ] IL-WF1.1: `workflow_instances` + `workflow_events` + trigger + stores.
- [ ] IL-WF1.2: `WorkflowEventStore`, `WorkflowInstanceStore`, `WorkflowState.replay()`.
- [ ] IL-WF1.3: `DurableWorkflowRunner` + asyncpg LISTEN + advisory lock + backup polling.
- [ ] IL-WF1.4: `DurableWorkflowProcessor` + `RouteBuilder.durable()` + control-flow (branch/loop/for_each/sub_workflow/trigger_workflow/wait/compensate).
- [ ] IL-WF1.5: `workflow-worker` CLI entrypoint + graceful shutdown + K8s probes.
- [ ] IL-WF1.6: MCP auto-export (workflows as tools) + REST/gRPC/SOAP/Rabbit/Kafka triggers.
- [ ] IL-WF2.*: миграция существующих Prefect flows.
- [ ] IL-WF3: удаление `prefect` из `pyproject.toml`.
- [ ] IL-WF4: Admin API + Streamlit runtime visualization (timeline, event log, current step highlight).

## Ссылки

- План: `/root/.claude/plans/tidy-jingling-map.md` (IL-WF1 секция).
- Prefect usage inventory: см. agent report от 2026-04-22.
- Референсы: Temporal.io (event sourcing + workers), Camunda Zeebe
  (BPMN + event sourcing), AWS Step Functions (declarative spec).
