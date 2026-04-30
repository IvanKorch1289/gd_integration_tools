# DSL Write-Back (W25.2)

Bidirectional Python ↔ YAML для DSL-маршрутов: сериализация Pipeline'а
из ``RouteRegistry`` обратно в YAML-файлы. Используется для миграции
legacy кода в YAML и UI-редактора.

## Компоненты

| Слой | Файл | Назначение |
|---|---|---|
| Core | `src/dsl/engine/pipeline.py` (`to_dict`/`to_yaml`) | сериализация Pipeline |
| Core | `src/dsl/engine/processors/base.py::BaseProcessor.to_spec()` | базовый контракт processor → dict |
| Core | `src/dsl/yaml_store.py::YAMLStore` | save/load/diff на диск |
| Service | `src/services/dsl/builder_service.py::DSLBuilderService` | фасад с env-guard |
| CLI | `manage.py dsl write-yaml` | dev-CLI для write-back |
| UI | `src/entrypoints/streamlit_app/pages/32_DSL_Builder.py` | Streamlit-страница |

## Использование

### CLI (dev-only)

```bash
# preview без записи
uv run python manage.py dsl write-yaml my.route_id --diff --dry-run

# фактическая запись (только в development)
uv run python manage.py dsl write-yaml my.route_id --output dsl_routes/
```

CLI выходит с кодом 2, если `APP_ENVIRONMENT != "development"` и не
указан `--dry-run`.

### Streamlit page

`/32_DSL_Builder` — выбор route_id → preview YAML/diff → кнопка Save
(видна только в development).

### Программно (services-слой)

```python
from src.services.dsl.builder_service import get_dsl_builder_service

svc = get_dsl_builder_service()
result = svc.save_route("orders.create", dry_run=True)
print(result.diff)  # unified-diff с YAMLStore
print(result.written, result.reason)
```

## Контракт `to_spec()`

Каждый процессор может реализовать ``to_spec() -> dict | None``:

```python
class LogProcessor(BaseProcessor):
    def to_spec(self) -> dict[str, Any] | None:
        return {"log": {"level": self._level}}
```

- ключ внешнего dict'а — **имя метода RouteBuilder**;
- значение — kwargs этого метода (примитивы, dict, list);
- ``None`` — процессор не сериализуется (callable/тип в args, sub-pipelines, etc.).

Pipeline.to_dict пропускает процессоры, у которых ``to_spec()`` возвращает ``None``.

## Текущее покрытие (W25.2 baseline)

Реализовано в этой волне (примитивно-параметризованные процессоры):

| Builder method | Processor | Файл |
|---|---|---|
| `set_header` | SetHeaderProcessor | `processors/core.py` |
| `set_property` | SetPropertyProcessor | `processors/core.py` |
| `log` | LogProcessor | `processors/core.py` |
| `transform` | TransformProcessor | `processors/core.py` |
| `dispatch_action` | DispatchActionProcessor (без payload_factory) | `processors/core.py` |
| `enrich` | EnrichProcessor (без payload_factory) | `processors/core.py` |
| `throttle` | ThrottlerProcessor | `processors/eip/flow_control.py` |
| `delay` | DelayProcessor (без scheduled_time_fn) | `processors/eip/flow_control.py` |

Уже было реализовано до W25 (~28 процессоров): Audit / Notify / Invoke /
Entity CRUD / Telegram / Express / WindowedDedup / MulticastRoutes /
Redirect и пр.

## Ограничения

1. **Callable-аргументы**: процессоры с ``payload_factory``,
   ``predicate``, ``correlation_key`` и т.п. сериализуются как
   ``None`` (молча). Их нужно описывать YAML'ом изначально или
   рефакторить под expression-форму (JMESPath / template).

2. **Type-аргументы**: ``ValidateProcessor(model=OrderSchemaIn)`` пока
   не сериализуется — model нужно резолвить через registry. Будет в
   следующих волнах через ``schema: OrderSchemaIn`` (символьный ref).

3. **Sub-processors**: реализованы в W26.1 для пяти control-flow
   процессоров — Retry / TryCatch / Parallel / Saga / Choice. Choice
   поддерживает только JMESPath-форму (``expr``); legacy callable
   predicate возвращает ``None`` и пропускается при write-back.
   Splitter / Aggregator / Loop / OnCompletion остаются open и
   запланированы в более поздних волнах.

   Пример nested-YAML для control-flow:

   ```yaml
   processors:
     - retry:
         max_attempts: 3
         delay_seconds: 1.0
         backoff: exponential
         processors:
           - log: {level: info}
           - dispatch_action: {action: orders.create}
     - do_try:
         try_processors:
           - transform: {expression: body}
         catch_processors:
           - log: {level: error}
         finally_processors:
           - set_header: {key: x-finalized, value: "1"}
     - parallel:
         strategy: all
         branches:
           left:
             - log: {level: info}
           right:
             - dispatch_action: {action: notify.user}
     - saga:
         steps:
           - forward: {dispatch_action: {action: orders.reserve}}
             compensate: {dispatch_action: {action: orders.cancel}}
     - choice:
         when:
           - expr: "status == 'ok'"
             processors:
               - dispatch_action: {action: orders.complete}
         otherwise:
           - log: {level: warning}
   ```

4. **Write-back только в development**: env-guard в
   ``DSLBuilderService.is_write_enabled``. Production использует
   read-only YAMLStore + ImportGateway / API endpoints.

## Полный аудит to_spec coverage

См. `docs/reference/dsl/to_spec_audit.md` (генерируется
``tools/audit_to_spec.py``).
