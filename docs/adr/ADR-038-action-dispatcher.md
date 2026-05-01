# ADR-038: ActionDispatcher Gateway — единая точка диспетчеризации action

- **Статус:** accepted
- **Дата:** 2026-05-01
- **Фаза:** Wave-14.1 (Action Gateway sprint 2)
- **Автор:** Claude (по согласованию с заказчиком)

## Контекст

В W14.1 (sprint 1) был зафиксирован минимальный
`ActionDispatcher` Protocol — транспорт-агностичный вызов
бизнес-команды по `ActionCommandSchema`. На практике этого оказалось
недостаточно: HTTP, WebSocket, Scheduler и MQ-консьюмеры
независимо вызывали `service.method(**payload)` в обход реестра, что
делало невозможным:

* единый аудит (correlation_id, tenant_id, user_id);
* идемпотентность по `idempotency-key` поверх любого транспорта;
* rate-limit на уровне action (не транспорта);
* унифицированный envelope ошибок (`ActionResult`);
* динамический каталог зарегистрированных действий
  (нужен Streamlit Action Console + MCP auto-export + developer portal).

Реестр `ActionHandlerRegistry` в DSL хранил только
`(action → handler-spec)`, без расширенных метаданных
(`input_model`, `output_model`, `transports`, `side_effect`,
`permissions`, `rate_limit`, `timeout_ms`, …) и без поддержки
middleware-цепочки.

## Рассмотренные варианты

- **Вариант А — middleware на уровне FastAPI / Starlette.**

  *Плюсы:* стандартный механизм, не требует новых абстракций.
  *Минусы:* привязка к одному транспорту; WebSocket / Scheduler /
  MQ остаются вне цепочки; невозможно унифицировать envelope ошибок
  до того, как FastAPI сериализует ответ; rate-limit/idempotency на
  уровне action не выражается через middleware HTTP-роутера.

- **Вариант Б — отдельный gateway-сервис (sidecar).**

  Например, Envoy filter-chain или собственный микросервис.

  *Плюсы:* enterprise-grade, переносим между языками.
  *Минусы:* дополнительный hop, рассинхрон со схемами Pydantic,
  тяжёлая инфраструктура для проекта с одним runtime и DSL внутри
  процесса.

- **Вариант В — статически сгенерированный Gateway (codegen).**

  Парсить `ActionSpec` и генерировать типизированный диспетчер.

  *Плюсы:* zero runtime overhead, типизация end-to-end.
  *Минусы:* несовместимо с динамической регистрацией DSL-маршрутов
  через YAMLStore / `register_action_handlers` / hot-reload;
  ломает Wave-26.5 модель «runtime-источник правды — реестр».

- **Вариант Г — расширение Protocol + middleware-цепочка в
  существующем `ActionHandlerRegistry`/`DefaultActionDispatcher`
  (выбран).**

  Двойной контракт: легаси `ActionDispatcher.dispatch(command)`
  сохраняется без изменений, поверх — новый
  `ActionGatewayDispatcher.dispatch(action, payload, context)` с
  envelope и middleware-цепочкой. Транспорты (HTTP, WS, Scheduler,
  MQ) опционально делегируют в gateway через feature flag — это
  даёт безопасную постепенную миграцию.

  *Плюсы:* нулевые новые зависимости, обратная совместимость по
  каждому call site, единая точка для трассировки/аудита/rate-limit/
  идемпотентности; реестр остаётся single source of truth.
  *Минусы:* `Protocol` шире → больше сюрпризов при подмене в тестах;
  middleware-цепочка строится на каждый dispatch (приемлемо для не-hot
  путей, где она нужна).

## Решение

Принят **Вариант Г** — четырёх-фазная имплементация:

### Phase A — контракты (`9911182`)

`src/core/interfaces/action_dispatcher.py` расширен следующими
DTO/Protocol:

* `ActionMetadata` — расширенные метаданные action
  (`input_model`, `output_model`, `transports`, `side_effect`,
  `idempotent`, `permissions`, `rate_limit`, `timeout_ms`,
  `deprecated`, `since_version`, `error_types`, `tags`);
* `DispatchContext` — контекст вызова (`correlation_id`,
  `tenant_id`, `user_id`, `idempotency_key`, `source`,
  `trace_parent`, `attributes`);
* `ActionResult` / `ActionError` — унифицированный envelope;
* `ActionMiddleware` Protocol + `MiddlewareNextHandler` тип;
* `ActionGatewayDispatcher` Protocol с
  `dispatch(action, payload, context) → ActionResult`,
  `get_metadata`, `list_actions(transport)`,
  `list_metadata(transport)`, `register_middleware`.

Легаси `ActionDispatcher` Protocol сохранён без изменений.

### Phase B — реестр (`eb45b09`)

`ActionHandlerRegistry` получил parallel storage метаданных и
middleware-цепочку:

* `_metadata: dict[str, ActionMetadata]` рядом с `_handlers`;
* `register_with_metadata(action, handler, metadata)`;
* `get_metadata` / `list_metadata(transport)`;
* `register_middleware` / `list_middleware`.

`register` / `register_many` остались обратно совместимыми — при
вызове создаётся минимальная `ActionMetadata` (только `action` +
`input_model` из `payload_model`). Дополнительно введён адаптер
`src/core/actions/spec_to_metadata.py` (`ActionSpec` →
`ActionMetadata`), который вызывается из
`ActionRouterBuilder.add_action`.

### Phase C — реализация диспетчера (`2aefff7`)

`src/services/execution/action_dispatcher.py`:

* `DefaultActionDispatcher` реализует одновременно `ActionDispatcher`
  (legacy) и `ActionGatewayDispatcher`. Полиморфный `dispatch`
  принимает либо `ActionCommandSchema` (legacy), либо `str` имя
  action (gateway-режим) — это позволяет существующим call sites
  (Invoker, DSL processors) работать без правок.
* Терминальный обработчик строит `ActionCommandSchema`, вызывает
  реестр и маппит исключения в `ActionResult` / `ActionError`
  (`action_not_found` → не recoverable; прочие → `dispatch_failed`).
* Middleware-цепочка строится из списка `registry.list_middleware()`
  справа налево, чтобы порядок регистрации = порядок вызова.

В composition root зарегистрированы 3 базовые middleware
(`src/plugins/composition/service_setup.py`):

1. `AuditMiddleware` — структурированный лог `action.start /
   action.end / action.error` с `correlation_id` / `tenant_id`;
2. `IdempotencyMiddleware` — кэш по `(action, idempotency_key)`
   на TTL (Redis-backed in prod, in-memory fallback);
3. `RateLimitMiddleware` — token-bucket на `(action, tenant_id)`
   из `ActionMetadata.rate_limit`.

### Phase D — делегирование транспортов (`cd3dc03`)

* HTTP — `ActionRouterBuilder._build_action_endpoint` вызывает
  `_dispatch_via_gateway`, если включён feature flag
  `USE_ACTION_DISPATCHER_FOR_HTTP=1`. Иначе — старый прямой путь
  `service.method(**direct_kwargs)`. По умолчанию **OFF**.
* WebSocket / Scheduler / MQ — аналогичные feature flag'и с
  fallback на прямой вызов.
* `_action_result_to_response` маппит `ActionResult` в
  FastAPI-friendly ответ: `success=True` → `data` напрямую (FastAPI
  сериализует через `response_model`), `success=False` →
  `JSONResponse` со статусом 400/404/500 в зависимости от
  `error.recoverable` + `error.code`.

### Phase E — Inventory API + ADR + docs (этот документ)

* `GET /api/v1/actions/inventory[?transport=http|ws|...]` — JSON-каталог
  всех зарегистрированных action с расширенными метаданными.
  Используется Streamlit Action Console (drop-down + auto-complete),
  MCP auto-export (внешние LLM-агенты), developer portal,
  контрактные тесты.
* Обновлены `.claude/KNOWN_ISSUES.md` и `.claude/CONTEXT.md`.

## Последствия

### Положительные

- Единая точка для аудита, трассировки, идемпотентности,
  rate-limit и envelope ошибок поверх HTTP / WS / Scheduler / MQ —
  без перепроектирования entrypoints.
- Backward compatible на каждом уровне: легаси `ActionDispatcher`
  Protocol сохранён, прямой путь через `service.method(**)` работает,
  feature flag включается per-transport.
- `ActionMetadata.transports / side_effect / permissions / rate_limit`
  становятся *единственным источником правды* о action — отсюда же
  питается developer portal и MCP-каталог.
- Тестируемость: `DefaultActionDispatcher` принимает реестр в
  конструкторе → тесты используют изолированный экземпляр без global
  state.

### Отрицательные

- 3 средних middleware (`audit`, `idempotency`, `rate_limit`)
  выполняются на каждый gateway-dispatch — оверхед ~50-100µs на
  вызов. Для high-throughput action (например, batch metric ingest)
  потребуется bypass через прямой path или per-action skip-list (W14.2).
- Двойственность `dispatch(...)` (полиморфизм по типу первого
  аргумента) усложняет typing — для нового кода обязательно использовать
  именованный `dispatch_action(action, payload, context)`.
- 119 существующих action всё ещё проходят через прямой путь
  (`USE_ACTION_DISPATCHER_FOR_HTTP=false`). Полная миграция требует
  per-action декларации `transports / side_effect / permissions` —
  технический долг W14.2.

### Нейтральные

- DSL apiVersion v3 не нужен: изменения в реестре читают
  `ActionSpec.body_model / response_model` через duck-typing.
- В composition root middleware регистрируются один раз — новых
  hooks в lifespan не добавлено.

## Open questions / технический долг

1. ~~**Миграция всех 119 actions**~~ → **частично закрыто
   2026-05-01 post-sprint-2** (см. ниже «Дополнение: per-spec миграция»).
   Закрыты пункты 3 (per-action декларация Gateway-полей) и
   стартовая инфраструктура для пункта 1 (per-spec включение
   `use_dispatcher`). Открытым остаётся вопрос — расширение пилота
   с 4 healthcheck-action на остальные 84 ActionSpec через
   декларацию `action_id` + `use_dispatcher=True`.
2. **Integration-тесты middleware** по транспортам (HTTP / WS /
   Scheduler) с реальным Redis-cache для `IdempotencyMiddleware` и
   `testcontainers[redis]`. Эффорт: M.
3. ~~**Per-action декларация Gateway-полей**~~ → **закрыто
   2026-05-01** (см. «Дополнение»): `ActionSpec` расширен полями
   `side_effect / idempotent / permissions / rate_limit / timeout_ms /
   deprecated / since_version / transports`; адаптер
   `action_spec_to_metadata` выводит `side_effect`/`idempotent` из
   HTTP-метода по REST-конвенции. Контракт-тест
   `tests/unit/dsl/test_action_metadata_contract.py` фиксирует
   инварианты.
4. **MCP auto-export** — отдельный endpoint / CLI, который
   читает `GET /api/v1/actions/inventory` и публикует tool-каталог во
   внешний MCP server. Часть W14.3.
5. **Bypass-список для hot-path** — действия с очень коротким SLA
   (например, кэш-warmup), которые не должны проходить через цепочку
   middleware. Возможная стратегия: атрибут `ActionMetadata.skip_middleware`.

## Дополнение: per-spec миграция (post-sprint-2, 2026-05-01)

### Обнаружение проблемы пространств имён

При попытке включения `USE_ACTION_DISPATCHER_FOR_HTTP=true` выявлено,
что `ActionSpec.name` (имя HTTP-роута, например `healthcheck_database`)
и имя handler в `ActionHandlerRegistry` (например `tech.check_database`)
исторически принадлежат **разным пространствам имён**: пересечение
по 119 actions было `0`. Без связи `_dispatch_via_gateway` всегда
уходил на fallback (прямой `service.method(**)`), и Gateway-цепочка
никогда не выполнялась.

### Решение: явная связь через `ActionSpec.action_id`

Добавлено опциональное поле `ActionSpec.action_id: str | None = None`.
Если задано — это идентификатор handler'а в реестре; если `None` —
fallback на `spec.name` (обратная совместимость).

Адаптер `action_spec_to_metadata` использует `action_id or name` для
`ActionMetadata.action`. `ActionRouterBuilder.add_action()` регистрирует
metadata под этим же ключом. Таким образом, если разработчик задаёт
`ActionSpec(action_id="tech.check_database", ...)`, то и handler (из
`setup.register_action_handlers`), и metadata (из `add_action`) лежат
в реестре под одним ключом, а Gateway-dispatch попадает на handler.

### Per-spec включение Gateway

Добавлено поле `ActionSpec.use_dispatcher: bool | None = None`.
Precedence (см. `_should_use_dispatcher` в `actions.py`):

| `spec.use_dispatcher` | env `USE_ACTION_DISPATCHER_FOR_HTTP` | Путь |
|---|---|---|
| `True` | (любое) | через Gateway (middleware + envelope) |
| `False` | (любое) | прямой путь |
| `None` (default) | `false` (default) | прямой путь |
| `None` (default) | `true` | через Gateway |

Это даёт безопасную поэтапную миграцию: разработчик помечает
`use_dispatcher=True` пилотную группу, остальные остаются на прямом
пути до своей очереди.

### Пилотная группа (4 healthcheck-action)

Включены через `action_id` + `use_dispatcher=True` в
`src/entrypoints/api/v1/endpoints/tech.py`:

* `healthcheck_database` → `tech.check_database`
* `healthcheck_redis` → `tech.check_redis`
* `healthcheck_s3` → `tech.check_s3`
* `healthcheck_all_services` → `tech.check_all_services`

Все четыре — GET, `side_effect="read"`, `idempotent=True`. Остальные
4 healthcheck (`s3_bucket`, `graylog`, `smtp`, `rabbitmq`) пока
не имеют handler в `setup.py` и не входят в пилот.

### Дальнейшая миграция

Расширение пилота — за счёт:

1. регистрации недостающих handler'ов в `dsl/commands/setup.py`
   (для оставшихся 84 ActionSpec без handler-привязки);
2. постепенного добавления `action_id="<service>.<method>"` +
   `use_dispatcher=True` группами по 10–20 actions;
3. прогон `tests/unit/dsl/test_action_metadata_contract.py` после
   каждой группы.

Глобальный env-flag `USE_ACTION_DISPATCHER_FOR_HTTP` остаётся
default-OFF до завершения миграции — сохраняет одношаговый rollback.

## Связанные ADR

- ADR-022 — Connector SPI (контракт сервисов, методы которых
  становятся action handler'ами).
- ADR-031 — DSL durable workflows (workflow-action как клиент
  Gateway).
- ADR-032 — Observability automation (`AuditMiddleware` пишет в
  тот же структурированный лог-стрим).
- ADR-036 — ResilienceCoordinator (rate-limit middleware читает
  политики из того же base.yml).

## Ссылки на коммиты

- `9911182` — `[phase:Wave-14.1.A/contracts]` контракты.
- `eb45b09` — `[phase:Wave-14.1.B/registry-extension]` реестр.
- `2aefff7` — `[phase:Wave-14.1.C/dispatcher-service]` диспетчер +
  middleware.
- `cd3dc03` — `[phase:Wave-14.1.D/router-delegation]` HTTP / WS /
  Scheduler делегация.
- `[phase:Wave-14.1.E/inventory-api]` — Inventory endpoint + ADR-038
  (этот коммит).
