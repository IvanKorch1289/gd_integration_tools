# ADR-0421 — Авторизация на action-поверхности (permissions + admin-префикс)

* Статус: Accepted (2026-11-02, волна 24, кластер F6a — «авторизация на action-поверхности»)
* Cycle: 184 (волна 24)
* Связан с:
  - ADR-0420 (предыдущий кластер волны 24 — ротация кредов БД),
  - ADR-0383 (санитизация ошибок — секреты и внутренние детали не утекают в лог/ответ),
  - ADR-0410 / ADR-0404 (order-dependent загрязнение process-global состояния — реестр action'ов),
  - ADR-0100 (прецедент: мёртвый код удаляется либо получает реального потребителя),
  - ADR-0284 (матрица межслойных импортов — новых нарушений не добавляем)
* Затрагивает:
  - `src/backend/dsl/commands/action_registry.py` (enforcement прав в `dispatch()`),
  - `src/backend/entrypoints/api/generator/auto_register.py` (auto-поверхность `/api/v1/auto/*`),
  - `src/backend/entrypoints/api/generator/legacy_aliases.py` (legacy-алиасы + утечка `str(exc)`),
  - `src/backend/entrypoints/api/v1/endpoints/invocations.py` (универсальный диспетчер),
  - `src/backend/entrypoints/soap/soap_handler.py` (SOAP-диспатч + утечка `str(exc)` в Fault),
  - `src/backend/entrypoints/api/v1/routers.py` (двойные префиксы + монтаж NATS),
  - `src/backend/entrypoints/api/v1/endpoints/admin_connectors.py` (утечка деталей ошибки),
  - `src/backend/services/core/admin.py` (документирование контракта admin-action'ов),
  - `tests/unit/dsl/test_action_registry_permissions.py` (новый),
  - `tests/unit/api/test_action_permission_surfaces.py` (новый),
  - `tests/unit/api/test_router_prefixes.py` (новый),
  - `tests/unit/entrypoints/test_action_surface_error_leaks.py` (новый)

---

## Контекст

Волна 24 мультироевого аудита зафиксировала четыре класса дефектов на
action-поверхности — общей точке, где любой зарегистрированный action
становится достижимым из HTTP/SOAP/WS/GraphQL.

**Дефект 1 (critical) — `ActionMetadata.permissions` не проверялась нигде.**
Поле `permissions` было объявлено в `ActionMetadata`
(`core/interfaces/action_dispatcher.py`), пробрасывалось из `ActionSpec`
(`core/actions/spec_to_metadata.py`) и **больше нигде не читалось**: grep
`.permissions` давал только пропагацию. `ActionHandlerRegistry.dispatch()`
(`dsl/commands/action_registry.py`) валидировал лишь payload. Итог:
объявленное право на action не давало никакого эффекта.

**Дефект 2 (critical) — `admin.*`-действия без авторизации.**
Проба аудита: `POST /api/v1/auto/admin.get_config` отдавал
`settings.model_dump()` (`services/core/admin.py:79-86`) любому
аутентифицированному пользователю, а `POST /api/v1/auto/admin.invalidate_cache`
(`services/core/admin.py:142`) выполнял admin-действие (полная инвалидация
кэша). 253 из 470 effective-роутов не имели ни одной auth-зависимости — только
аутентификации.

**Дефект 3 (high) — `POST /api/v1/invocations` без авторизации.**
`entrypoints/api/v1/endpoints/invocations.py:38-61` — универсальный
диспетчер, регистрировавший роут без `dependencies`. Любой action из
`action_handler_registry` достижим аутентифицированному пользователю:
достаточно указать имя action'а в теле запроса.

**Дефект 4 (high) — двойные префиксы в v1-роутере.**
`admin_langgraph` монтировался с `prefix="/admin"` при собственном
`prefix="/admin/langgraph"` → `/api/v1/admin/admin/langgraph/*`;
`admin_plugins` — с `prefix="/admin/plugins"` при собственном
`prefix="/admin/plugins"` → `/api/v1/admin/plugins/admin/plugins/*`.
Streamlit-клиент уже обращался к `/api/v1/admin/plugins` и
`/api/v1/admin/langgraph/checkpoints` — то есть фронтенд был сломан.
`admin_nats.py` не был смонтирован вообще → 404.

**Дефект 5 (medium) — утечки внутренних ошибок в ответе.**
`legacy_aliases.py:88` — `f"Action dispatch failed: {exc}"`;
`soap_handler.py:240,260` — `_build_soap_fault("Server", str(exc))`;
`admin_connectors.py:119` — `detail=f"Reload failed: {type(exc).__name__}: {exc}"`
(плюс `str(exc)[:200]` в теле ответа health-check'а и reload-статуса).
Внутренние тексты (DSN, пути, строки подключения) уходили наружу.

## Решение

### 1. Единая каноническая проверка прав в `ActionHandlerRegistry.dispatch()`

В `dsl/commands/action_registry.py` добавлен слой авторизации:

* `required_action_permissions(action, metadata)` — требуемые permissions:
  1. явно объявленные `ActionMetadata.permissions`;
  2. `admin`-префикс имени action'а (`admin.` / `admin_`) → `role:admin`;
  3. иначе — пусто (backward compat: обычные action'ы не требуют прав).
* `enforce_action_permissions(action=..., required=..., granted=..., principal=...)`
  — проверка с **AND**-семантикой (как `permission_step` из
  `AuthorizationGateway`: требуются *все* permissions), fail-closed.
* `ActionPermissionDeniedError(BaseError)` — HTTP 403 с безопасным
  `to_detail()` (`code`/`action`/`required`), без внутренних деталей.
* `resolve_action_permissions(auth)` — единый сбор эффективных прав из
  `AuthContext`: user-permissions (`metadata["permissions"]` либо
  OAuth-`scope`) **плюс** `role:admin`, если principal обладает хотя бы одной
  admin-ролью (`metadata["admin_roles"]`). Каналы разные, action'у нужно
  единое множество прав.
* `dispatch()` вызывает `_enforce_permissions(command)` **до** обращения к
  обработчику; при отказе эмитится audit-событие
  `action.permission_denied` (`outcome="denied"`, `severity="warning"`)
  через `core.audit.facade.audit_service` и бросается 403.

Транспортная независимость сохранена: DSL-слой не тянет `fastapi`
(константа `_FORBIDDEN_STATUS = 403` рядом с `BaseError`).

### 2. Права на auto-/invocation-поверхности

* **Auto-роуты** (`entrypoints/api/generator/auto_register.py`): endpoint
  собирает `meta.permissions` через `resolve_action_permissions` и переводит
  `ActionPermissionDeniedError` в HTTP 403 (`detail=exc.to_detail()`).
* **Legacy-алиасы** (`entrypoints/api/generator/legacy_aliases.py`): то же
  самое, но в формате `JSONResponse(403)`.
* **`POST /api/v1/invocations`** (`entrypoints/api/v1/endpoints/invocations.py`):
  добавлен параметр `request: Request`; перед вызовом Invoker'а endpoint
  спрашивает у глобального реестра `required_permissions(action)` и
  прогоняет ту же `enforce_action_permissions`. Отказ → 403 **до**
  `invoker.invoke(...)` (Invoker сам ошибки превращает в
  `status="error"` с HTTP 200, поэтому pre-check обязателен).
  `principal`/`permissions` теперь передаются в `InvocationRequest` —
  они доходят до `ActionCommandSchema.meta` и до реестра.
* **SOAP** (`entrypoints/soap/soap_handler.py`): `permissions` собираются
  через `resolve_action_permissions`, поэтому admin-action'ы через SOAP
  закрыты так же, как через REST; отказ приходит как `BaseError` → SOAP
  Fault c кодом `Client` (403 < 500).

### 3. Двойные префиксы и монтаж NATS

`entrypoints/api/v1/routers.py`: роутеры, уже несущие собственный префикс,
подключаются **без** дополнительного:

* `admin_langgraph_router` → `/api/v1/admin/langgraph/*`;
* `admin_plugins_router` → `/api/v1/admin/plugins/*`;
* `admin_nats_router` (префикс `/admin/nats` в самом модуле) — **смонтирован**,
  ранее был orphan → `/api/v1/admin/nats/consumers`.

Префиксы в `admin_langgraph.py` / `admin_plugins/endpoints.py` не менялись:
канонический путь — префикс на самом роутере, а `routers.py` его не дублирует.

### 4. Утечки внутренних ошибок

* `legacy_aliases.py` — вместо `f"Action dispatch failed: {exc}"` отдаётся
  `{"detail": "Action dispatch failed"}`, детали — в `logger.exception`.
  Аналогично для «плохого запроса».
* `soap_handler.py` — Fault `Server` формируется с безопасной строкой
  `Internal server error`; `str(exc)` и текст `exchange.error` уходят
  только в лог.
* `admin_connectors.py` — `detail="Connector reload failed"`; в теле ответа
  по health-check'у вместо `str(exc)[:200]` возвращается только
  `type(exc).__name__`; детали — в лог.

## Альтернативы

* **Проверка только через `check_route_permission`
  (`services/routes/route_authz.py`) — отклонено.** Канонический механизм
  DSL-роутов (`dsl/service/facade.py`) опирается на `AuthorizationGateway`,
  который резолвится через `ai_agent._authz_gateway` и за feature-flag'ом
  `route_authz_requires_permission`. Для action-поверхности это даёт
  fail-closed «gateway_not_registered» в окружениях без AI-agent service
  (легитимный админ получил бы 403) и не выражает OR-семантику
  admin-ролей. В ADR-0421 **переиспользована та же конвенция** строк
  (`role:`/`scope:`) и та же AND-семантика, что и у `permission_step`,
  но проверка детерминирована и не зависит от feature-flag'ов.
* **`ActionMetadata.permissions` как единственный триггер — отклонено.**
  Тогда потребовалось бы перерегистрировать все 7 `admin.*`-action'ов с
  явными метаданными (`dsl/commands/setup/registers_domains.py` — вне
  зоны кластера). Правило по префиксу покрывает и новые admin-action'и
  автоматически.
* **Передача admin-ролей отдельным полем в `ActionCommandMetaSchema` —
  отклонено.** `core/types/invocation_command.py` вне зоны кластера, а
  `extra="ignore"` отбрасывает лишние поля. Роли сводятся к permission-строке
  `role:admin` на границе entrypoint.
* **Проверка прав только в HTTP-слое (guard на роутере) — отклонено.**
  Не закрывает SOAP/WS/GraphQL/MCP-пути, ведущие в тот же реестр.
  Реестр — единственная точка, где действие реально исполняется.

## Последствия

* **Позитивные.** `admin.get_config` / `admin.invalidate_cache` больше не
  отдают конфигурацию и не выполняют admin-действия для пользователя без
  admin-прав; `POST /api/v1/invocations` перестал быть «универсальным
  диспетчером без авторизации»; отказ фиксируется в audit-трейле; пути
  `/api/v1/admin/plugins/*` и `/api/v1/admin/langgraph/*` снова совпадают
  с тем, что вызывает Streamlit; NATS-инвентарь доступен.
* **Fail-closed.** Action с `admin`-префиксом недоступен анонимно и
  пользователю без admin-роли — даже если метаданные не объявляли прав.
* **Обратная совместимость.** Action'ы без `permissions` и без
  `admin`-префикса работают как раньше (прав не требуется).
* **Изменение сигнатуры `post_invocation`.** Endpoint теперь принимает
  `request: Request`; прямые вызовы в тестах обновлены
  (`tests/unit/api/test_invocations_endpoint.py`).
* **Пути, закрытые для WS/GraphQL-транспортов.** WS и GraphQL собирают
  `meta.permissions` из `extract_user_permissions` и **не** добавляют
  `role:admin` из `admin_roles` — эти транспорты вне зоны кластера. Следствие:
  admin-action'ы через WS/GraphQL отклоняются (fail-closed). Требуется
  отдельная правка `entrypoints/websocket/ws_handler.py` и
  `entrypoints/graphql/schema.py` — см. «вне зоны».
* **Совместимость с `AuthorizationGateway`.** Имена требуемых прав
  (`role:admin`, `scope:<x>`) совпадают с конвенцией `route.toml
  [security] requires_permission`, поэтому один и тот же principal может
  получить доступ и к DSL-роуту, и к action'у.

### Вне зоны кластера F6a (не менялось)

* `src/backend/entrypoints/websocket/ws_handler.py`,
  `src/backend/entrypoints/graphql/schema.py` — не добавляют `role:admin`
  из `admin_roles` в `meta.permissions` (admin-action'ы через эти транспорты
  закрыты fail-closed, но легитимный админ тоже не пройдёт).
* `src/backend/entrypoints/mcp/**` — отдельная поверхность вызова
  инструментов; проверка прав в ней не менялась.
* `src/backend/dsl/commands/setup/registers_domains.py` — регистрация
  `admin.*`-action'ов с явными `ActionMetadata.permissions` (не требуется:
  правило по префиксу покрывает их).
* `src/backend/core/types/invocation_command.py` — расширение
  `ActionCommandMetaSchema` полем `admin_roles` (не требуется: роли
  сводятся к `role:admin` на границе entrypoint).
* `docs/adr/INDEX.md` — индекс ADR обновляется генератором
  (`tools/build_adr_index.py`); в этой задаче не редактировался.

## Проверка

```bash
.venv/bin/python -m pytest \
    tests/unit/dsl/test_action_registry_permissions.py \
    tests/unit/api/test_action_permission_surfaces.py \
    tests/unit/api/test_router_prefixes.py \
    tests/unit/entrypoints/test_action_surface_error_leaks.py \
    tests/unit/api/test_invocations_endpoint.py -q -p no:randomly
.venv/bin/python -m ruff check <изменённые файлы>
.venv/bin/python tools/check_layers.py --strict        # 41 (новых нет)
.venv/bin/python tools/config_audit.py --scope orphans  # 0
.venv/bin/python tools/checks/mypy_budget.py            # OK (8 ошибок, budget 30)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0  # 0 missing
```

Red→green (фактический прогон):

* **RED** (на исходном коде, правки откачены): 4 новых файла →
  `16 failed, 24 passed`; после возврата утечки в `legacy_aliases.py` —
  `17 failed` (падали `test_internal_error_detail_hidden`,
  `test_internal_error_fault_is_generic`,
  `test_reload_failure_detail_is_safe`,
  `test_post_reload_health_error_is_safe`, оба теста на 403 auto/soap,
  `test_admin_action_denied_without_rights` ×2,
  `test_anonymous_admin_action_denied` ×2, `test_denial_emits_audit_event`,
  `test_denied_when_metadata_permission_missing`,
  `test_admin_prefix_denied_without_role_admin`, 6 тестов на префиксы и
  NATS-монтаж).
* **GREEN** (после правок): 4 новых файла → `40 passed`;
  вместе с `tests/unit/api/` и `tests/unit/dsl/test_action_registry.py` →
  `99 passed`.

### Pre-existing падения (не связаны с ADR-0421)

Полный прогон `tests/unit/entrypoints tests/unit/api tests/unit/dsl` даёт
order-dependent падения, зафиксированные в ADR-0404/ADR-0410:
`test_load_verifiers_returns_seven_auth_methods` (загрязнение
`core.auth.auth_selector._VERIFIERS`) и
`test_transports_is_non_empty_tuple_of_strings` (legacy-регистрации
bootstrap'а в глобальном `action_handler_registry`). Оба падают и **без**
новых файлов кластера; в изоляции проходят.

## Связи с другими ADR

* **ADR-0420** — предыдущий кластер волны 24; тот же формат отчёта
  (file:line, red→green, pre-existing падения).
* **ADR-0383** — санитизация ошибок: внутренние детали — в лог, наружу —
  безопасное сообщение (здесь применено к SOAP Fault и admin-коннекторам).
* **ADR-0410 / ADR-0404** — order-dependent загрязнение глобального
  `action_handler_registry`; новые тесты используют изолированные реестры,
  чтобы не добавлять жертв в банк.
* **ADR-0100** — мёртвый код (`ActionMetadata.permissions` без потребителя)
  получает реального потребителя.
* **ADR-0284** — матрица межслойных импортов: новых нарушений нет
  (`entrypoints → dsl` и `dsl → core` разрешены; `check_layers.py --strict`
  остаётся на 41).
