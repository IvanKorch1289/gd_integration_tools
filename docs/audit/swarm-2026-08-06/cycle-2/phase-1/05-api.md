# API domain audit — cycle 2 / phase 1

- **Date:** 2026-08-06
- **HEAD:** `ca5bff93058f2580041a7339913b52943babb329`
- **Scope:** `src/backend/entrypoints/api/**`, `src/backend/schemas/**`, API-focused tests
  (`tests/unit/entrypoints/**`, `tests/unit/entrypoints/api/**`, `tests/unit/schemas/**`,
  `tests/unit/entrypoints/api/v1/endpoints/test_admin_plugins.py`,
  `tests/unit/entrypoints/api/mobile/test_mobile_bff.py`,
  `tests/unit/entrypoints/api/generator/test_setup.py`,
  `tests/unit/entrypoints/test_admin_cron.py`).
- **Out of scope (заявлено):** `services/*` за пределами контрактов, `cycle-1` отчёты,
  `BASELINE.md cycle-1`, `PHASE-2-SUMMARY.md`, `PHASE-3-PLAN.md`, `KNOWN_ISSUES.md`,
  `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`.
- **Baseline (cycle 2):** commit `ca5bff93`; layer checker 175 legacy / 0 new;
  `pip-audit-allowlist.txt` = **35** активных CVE/GHSA/PYSEC ID; pre-existing
  `M uv.lock` (-15 svcs), `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`,
  `?? pip-audit.json`, `?? .blue_green.state` и 5 uncommitted правок cycle 1
  Phase 4 (T-1.4 / T-1.5 / T-3.1) НЕ атрибутируются рою cycle 2 и не трогались.
- **Найдено:** 11 finding (5 P0, 3 P1, 3 P2, 1 P3, 0 P4).
  Все cycle-1 IDs, упомянутые в задании, перепроверены в коде `ca5bff93`.

---

## 1. Scope / что проверено / что не проверено

### 1.1 Проверено (по файлам)

| Файл / артефакт | Прочитано | Примечание |
|---|---|---|
| `src/backend/entrypoints/api/v1/endpoints/hitl.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_cron.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_nats.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_actions.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_plugins/__init__.py` | да | decomp shim |
| `src/backend/entrypoints/api/v1/endpoints/admin_plugins/endpoints.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_plugins/helpers.py` | частично | вызовы mock_* |
| `src/backend/entrypoints/api/v1/endpoints/admin_plugins/schemas.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_resilience_profile.py` | да | head + auth-блоки |
| `src/backend/entrypoints/api/v1/endpoints/admin_ip_restriction.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/admin_parallelism.py` | да | guard-блок |
| `src/backend/entrypoints/api/v1/endpoints/admin_scheduler_dlq.py` | да | guard-блок |
| `src/backend/entrypoints/api/v1/endpoints/invocations.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/ai_stream.py` | да | целиком |
| `src/backend/entrypoints/api/v1/endpoints/health.py` | да | head + auth-блок |
| `src/backend/entrypoints/api/v1/routers.py` | да | целиком |
| `src/backend/entrypoints/api/mobile/router.py` | да | целиком |
| `src/backend/entrypoints/api/mobile/schemas.py` | да | целиком |
| `src/backend/entrypoints/api/mobile/__init__.py` | да | re-exports |
| `src/backend/entrypoints/api/generator/setup.py` | да | целиком |
| `src/backend/entrypoints/api/generator/auto_register.py` | да | целиком |
| `src/backend/entrypoints/api/generator/invocation.py` | да | целиком |
| `src/backend/entrypoints/api/generator/registry.py` | да | целиком |
| `src/backend/entrypoints/api/generator/actions/crud/__init__.py` | да | целиком |
| `src/backend/entrypoints/api/dependencies/auth.py` | да | целиком |
| `src/backend/entrypoints/api/dependencies/auth_selector.py` | да | целиком |
| `src/backend/entrypoints/api/versioning.py` | да | целиком |
| `src/backend/entrypoints/middlewares/auth_required.py` | да | целиком |
| `src/backend/schemas/__init__.py` | да | marker-only |
| `src/backend/schemas/base.py` | да | целиком |
| `src/backend/schemas/invocation.py` | да | re-exports |
| `src/backend/schemas/invocation_api.py` | да | целиком |
| `src/backend/schemas/workflow.py` | да | целиком |
| `src/backend/schemas/agent_memory.py` | да | целиком |
| `src/backend/schemas/health_events.py` | да | целиком |
| `src/backend/schemas/processing_result.py` | да | целиком |
| `src/backend/schemas/filter_schemas/__init__.py` | да | marker-only |
| `src/backend/schemas/route_schemas/__init__.py` | да | marker-only |
| `tests/unit/entrypoints/test_admin_cron.py` | да | целиком |
| `tests/unit/entrypoints/api/mobile/test_mobile_bff.py` | да | целиком |
| `tests/unit/entrypoints/api/v1/endpoints/test_admin_plugins.py` | да | целиком |
| `tests/unit/entrypoints/api/generator/test_setup.py` | да | целиком |

### 1.2 Не проверено

- `src/backend/entrypoints/api/v1/endpoints/dsl_*`, `ai_*`, `auth_*`,
  `admin_workflows/*`, `plugin_inventory.py`, `rag*`, `imports.py`, `langmem_admin.py`,
  `notebooks.py`, `orders.py`, `skb.py`, `search.py`, `tech.py`, `admin_*.py` (кроме
  перечисленных в задании) — **не в scope этого phase-1**, проверены только тесты и
  упоминания в `routers.py`. Если потребуется — отдельный audit.
- `extensions/**` — запрещено scope (бизнес-логика только extensions; в этом phase-1
  заглядывал только в `extensions.core_entities.orders.schemas.route` через импорт
  setup.py и в `test_setup.py` — это лишь для подтверждения broken import).
- Реализации сервисов за пределами контрактов (cycle 1 уже закрыл по `services/`).
- Поведение `AuthRequiredMiddleware` в production-deploy (cycle 36 fix, но я не
  верифицировал, что middleware реально подключён в `setup_middlewares.py` —
  это out of scope, только чтение показало наличие middleware).

---

## 2. Verified strengths (cycle-2 подтверждено, не изменилось)

| Аспект | Доказательство | Где проверено |
|---|---|---|
| Глобальный auth-guard pure ASGI существует и reject'ит non-public без auth | `AuthRequiredMiddleware.__call__`, public-prefix allowlist из 14 префиксов, 401 через send (no-raise) | `entrypoints/middlewares/auth_required.py:81-199` |
| Все 9 проверенных admin-роутеров имеют `Depends(require_admin(...))` | `admin.py`, `admin_actions.py`, `admin_plugins.py` (+ decomposed `endpoints.py`), `admin_cron.py`, `admin_nats.py`, `admin_resilience_profile.py`, `admin_scheduler_dlq.py`, `admin_parallelism.py`, `admin_ip_restriction.py` | прямой grep |
| Роутер `routers.py` собирает все v1-роуты с lazy-import + единым `api_router_v1` | 88+ `include_router` вызовов, 365 LOC, теги и prefix'ы корректны | `entrypoints/api/v1/routers.py:1-365` |
| Action-bus инвокация через `Invoker` с `Depends(get_invoker_dep)` | DI через `core.di.dependencies`, отдельный `ReplyChannelRegistryProtocol` | `invocations.py:41-101` |
| Pydantic v2 c `to_camel` alias generator, `extra='ignore'`, `from_attributes=True`, `validate_assignment=True` | конфиг в `BaseSchema`; pydantic v2 native | `schemas/base.py:30-47` |
| Шим `schemas/invocation.py` явно переэкспортирует `InvokeMode` + `ActionCommandSchema` etc из `core.types.invocation_command` | docstring ссылается на relocation, чтобы убрать `core → schemas` reverse-layer | `schemas/invocation.py:1-24` |
| Cycle-1 fix (admin_actions/admin_plugins): router-level guard восстановлен после S62 W1 decomp | `_ADMIN_GUARD_OPERATOR` явно задан в `endpoints.py:34-42` + комментарий "S206 fix" | `admin_plugins/endpoints.py:31-42` |
| Generator: auto_register_unrouted_actions сканирует FastAPI routes + idempotent | `_collect_existing_route_names` с `existing_names.add(route_name)` | `generator/auto_register.py:90-209` |
| `ActionRouterBuilder` (`generator/actions/__init__.py`) даёт декларативную регистрацию actions → REST endpoints с auto-CRUD через `CrudMixin` | `_register_crud_action_metadata` корректно регистрирует action с metadata (transports/side_effect/idempotent/tags) | `generator/actions/crud/__init__.py:60-129` |
| `VersionedRouter` + `DeprecationMiddleware` поддерживают v1/v2 c `Deprecation`/`Sunset`/`Link` (RFC 8594) headers | `versioning.py:38-111`, dataclass `APIVersion`, `dispatch` ветвится по path-prefix | `entrypoints/api/versioning.py:38-111` |
| `schemas/agent_memory.py` использует `_StrictModel = ConfigDict(extra="forbid")` — strict validation | 10 моделей, все `_StrictModel`-наследники | `schemas/agent_memory.py:32-100` |
| `ai_stream.py` SSE-endpoint имеет явный `Depends(require_auth([API_KEY, JWT]))` на роуте | decorator-level `dependencies=[...]` + capability-check через `litellm_gateway_settings.enabled` | `ai_stream.py:95-112` |

---

## 3. Findings table

| ID | Приоритет | Title | Path:line | Status vs cycle-1 |
|---|---|---|---|---|
| API-P0-001 | P0 | admin_actions silent-success mock-fallback на POST /invoke | `src/backend/entrypoints/api/v1/endpoints/admin_actions.py:206-214` | RESIDUAL (логика не изменилась) |
| API-P0-002 | P0 | admin_plugins silent-success mock-fallback на POST /{name}/toggle | `src/backend/entrypoints/api/v1/endpoints/admin_plugins/endpoints.py:145-155` (дубль в `admin_plugins.py:267-277`) | RESIDUAL (логика не изменилась) |
| API-P0-003 | P0 | generator/setup.py broken import `src.backend.workflows.workflows_service` (модуль не существует) | `src/backend/entrypoints/api/generator/setup.py:12-14` | RESIDUAL (комментарий `# type: ignore[import-not-found]` сохранён) |
| API-P0-004 | P0 | hitl.py — нет router-level auth-guard (только docstring обещание) | `src/backend/entrypoints/api/v1/endpoints/hitl.py:48-129` | RESIDUAL (нет `Depends(require_auth)` ни на одном endpoint'е) |
| API-P0-005 | P0 | mobile/router.py — fail-open token-парсер + in-memory state; роутер orphan (не mounted) | `src/backend/entrypoints/api/mobile/router.py:55-93`; orphan в `routers.py` | MUTATED → сужено: код жив только в тестах, в production недоступен |
| API-P1-004 | P1 | admin_nats — dynamic layer violation (importlib entrypoints → infrastructure) | `src/backend/entrypoints/api/v1/endpoints/admin_nats.py:63-86` | RESIDUAL (закомментирован как «документированный compromise») |
| API-P1-010 | P1 | admin_cron — `importlib.import_module(module_path)` без sandbox allowlist | `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:86-94, 106-141` | RESIDUAL (regex `^[\w.]+:[\w]+$` разрешает `os:system`, `subprocess:run`, `shutil:rmtree`) |
| API-P1-NEW-001 | P1 | invocations POST /api/v1/invocations — нет router-level auth; выполняет произвольный action по имени | `src/backend/entrypoints/api/v1/endpoints/invocations.py:38-46` | NEW (не упоминалось в задании cycle-1, проверено в этом phase) |
| API-P2-NEW-001 | P2 | mobile_router orphan — определён и тестируется, но не подключён в `routers.py` | `src/backend/entrypoints/api/v1/routers.py` (нет `mobile_router`); `mobile/__init__.py:27-29` | NEW (dead code в scope) |
| API-P2-NEW-002 | P2 | Empty namespace packages `schemas/filter_schemas/` и `schemas/route_schemas/` (только docstring) | `src/backend/schemas/filter_schemas/__init__.py:1`, `schemas/route_schemas/__init__.py:1` | NEW |
| API-P3-NEW-001 | P3 | `schemas/invocation.py` backward-compat shim — 20+ импортов, можно мигрировать на `core.types.invocation_command` и `core.enums.invocation` напрямую | `src/backend/schemas/invocation.py:1-24`; импорт-сайты в `entrypoints/{base,mcp,stream,mqtt}` и `generator/{invocation,auto_register,marshaller,reflection}` | NEW |

---

## 4. Detailed evidence

### API-P0-001 — admin_actions silent-success mock-fallback (RESIDUAL)

- **Path:** `src/backend/entrypoints/api/v1/endpoints/admin_actions.py:99-114, 186-230, 254-272`
- **Evidence:**
  ```python
  # строка 99-113
  def _get_registry() -> Any:
      try:
          from src.backend.core.actions.registry import (
              ActionHandlerRegistry,
          )
          return ActionHandlerRegistry.get_instance()
      except Exception as _:
          logger.warning("ActionHandlerRegistry недоступен — используется mock")
          return None

  # строка 207-214 (POST /invoke)
      registry = _get_registry()
      if registry is None:
          # Mock-ответ при недоступном реестре
          return ActionInvokeResponse(
              name=body.name,
              mode=body.mode,
              result={"status": "mock", "payload_received": body.payload},
              invocation_id="mock-00000000",
          )
  ```
- **Поведение:** при недоступности `ActionHandlerRegistry.get_instance()` (например, на cold-start до завершения bootstrap) endpoint возвращает `200 OK` с `invocation_id="mock-00000000"` и `result.status="mock"`. Клиент/Streamlit думает, что action вызван.
- **Cycle-1 статус:** RESIDUAL. Логика не менялась между `b69d6b49` и `ca5bff93` (admin role guard добавлен в S202, но mock-fallback сохранён).
- **Impact:** silent corruption — админ может «вызвать» action и получить success при том, что handler не существует / упал на init. В проде через `require_admin((OPERATOR, SUPER_ADMIN))` это не открытый доступ, но семантика «fail-open» в админском endpoint'е.
- **Минимальная рекомендация:** при `_get_registry() is None` или любом Exception внутри try → `HTTPException(503, "ActionHandlerRegistry недоступен")`. Удалить `_mock_actions`, `_mock_spec` и mock-ветку; gate оставить fail-closed.
- **Тест-критерий:** `tests/unit/entrypoints/api/v1/endpoints/test_admin_actions.py::test_invoke_returns_503_when_registry_missing` (новый).

### API-P0-002 — admin_plugins silent-success mock-fallback (RESIDUAL)

- **Path:** `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py:118-155, 267-277`; дубль в `admin_plugins/endpoints.py:118-155, 145-155`.
- **Evidence:**
  ```python
  # admin_plugins.py:267-277 (POST /{name}/toggle)
  registry = _get_plugin_registry()
  if registry is None:
      # Mock-ответ при недоступном реестре
      previous = "inactive" if body.active else "active"
      current = "active" if body.active else "inactive"
      return PluginToggleResponse(
          name=name, active=body.active,
          previous_status=previous, current_status=current,
      )
  ```
  Тот же fail-open в `list_plugins` (`_mock_plugins()`) и `get_plugin_manifest` (`_mock_manifest(name)`).
- **Cycle-1 статус:** RESIDUAL. Поведение и сигнатуры идентичны. S62 W1 decomp вынес в `endpoints.py` / `helpers.py`, но логика не изменилась.
- **Impact:** критичнее, чем API-P0-001: `toggle_plugin` при падении PluginLoader возвращает `200 OK` со «статусом», но реальный plugin в реестре остаётся в исходном состоянии. Оператор уверен, что плагин активирован/деактивирован. Это data-state divergence между UI и реестром.
- **Минимальная рекомендация:** при `registry is None` → `HTTPException(503, "PluginLoader недоступен")`. Удалить `_mock_plugins`, `_mock_manifest`.
- **Тест-критерий:** `test_toggle_returns_503_when_loader_missing`, `test_manifest_returns_503_when_loader_missing` (новые).

### API-P0-003 — generator/setup.py broken import (RESIDUAL)

- **Path:** `src/backend/entrypoints/api/generator/setup.py:12-14`
- **Evidence:**
  ```python
  from src.backend.workflows.workflows_service import (  # type: ignore[import-not-found]  # legacy module path; not yet implemented, см. TD-NEW
      get_workflows_service,
  )
  ```
  Прямой прогон:
  ```bash
  $ .venv/bin/python -c "import src.backend.workflows.workflows_service"
  ModuleNotFoundError: No module named 'src.backend.workflows'
  ```
- **Cycle-1 статус:** RESIDUAL. `# type: ignore[import-not-found]` остался — это явное подавление mypy-ошибки. Никаких других источников `get_workflows_service` в `src/` не существует:
  ```
  $ grep -rn "send_notification_workflow\|order_processing_workflow\|get_workflows_service" src/ --include='*.py'
  src/backend/entrypoints/api/generator/setup.py:13:    get_workflows_service,
  src/backend/entrypoints/api/generator/setup.py:58:                service_getter=get_workflows_service,
  src/backend/entrypoints/api/generator/setup.py:59:                service_method="send_notification_workflow",
  src/backend/entrypoints/api/generator/setup.py:63:                service_getter=get_workflows_service,
  src/backend/entrypoints/api/generator/setup.py:64:                service_method="order_processing_workflow",
  ```
  Соседний рабочий путь — `src/backend/dsl/commands/setup.py:register_action_handlers()` (вызывается из `app_factory`, `startup.py`, `workflow/worker.py`).
- **Impact:** модуль `src/backend/entrypoints/api/generator/setup.py` физически не импортируется ни одним production-кодом
  (`grep -rn "from src.backend.entrypoints.api.generator.setup\|generator.setup" src/ tests/` пуст).
  Только `tests/unit/entrypoints/api/generator/test_setup.py` его использует и
  подменяет `sys.modules["src.backend.workflows.workflows_service"]` фейком
  (см. `test_setup.py:36-77`). То есть модуль — broken-import-only-for-tests.
  Если кто-то позже добавит реальный импорт — старт упадёт.
- **Минимальная рекомендация:** либо удалить модуль, либо переписать на
  `src.backend.services.workflows.<concrete_service>:get_workflows_service` —
  и убрать `# type: ignore[import-not-found]` (он маскирует реальность).
- **Тест-критерий:** `tests/unit/entrypoints/api/generator/test_setup_no_broken_import.py`
  — `import src.backend.entrypoints.api.generator.setup` без mock должен либо успешно
  импортироваться, либо выдавать осмысленную ошибку (а не `ModuleNotFoundError` в проде).

### API-P0-004 — hitl.py без router-level auth guard (RESIDUAL)

- **Path:** `src/backend/entrypoints/api/v1/endpoints/hitl.py:48-129`
- **Evidence:** все 4 endpoint'а объявлены без `dependencies=[Depends(...)]`:
  ```python
  router = APIRouter()                       # строка 24 — нет router-level deps
  ...
  @router.get("/pending", ...)               # строка 48
  async def list_pending(...): ...
  @router.get("/history", ...)               # строка 59
  async def hitl_history(...): ...
  @router.get("/{signal_id}", ...)           # строка 94
  async def get_signal(...): ...
  @router.post("/{signal_id}/resolve", ...)  # строка 107
  async def resolve_signal(...): ...
  ```
  Docstring (строка 11) обещает: `"Auth: JWT + tenant filtering (X-Tenant-ID); permission hitl.resolve"`.
  Ни X-Tenant-ID, ни permission check в коде нет.
- **Cycle-1 статус:** RESIDUAL. Сравнение с предполагаемым фиксом (см. задание Phase 4
  cycle 1, deferred T-1.2 «SSE/HITL auth») — T-1.2 в working tree не закрыт (его
  коммит отдельный; см. `git log ca5bff93~ -- hitl.py`).
- **Impact:** полагается только на глобальный `AuthRequiredMiddleware` (V7). Если
  middleware отключен / вынесен из deploy / bypass-нут (например, через reverse-proxy
  auth-off, или feature-flag), endpoints открыты, и `POST /hitl/{id}/resolve`
  позволяет approve/reject любой HITL-signal любому авторизованному пользователю
  (без разрешения `hitl.resolve`). HITL — критический security primitive в workflow.
- **Минимальная рекомендация:** добавить router-level guard с explicit permission
  (cycle 1 T-1.2):
  ```python
  router = APIRouter(
      prefix="/hitl",
      tags=["HITL"],
      dependencies=[Depends(require_auth([AuthMethod.JWT])),
                    Depends(require_permission("hitl.resolve"))],
  )
  ```
  И tenant filtering в каждом endpoint (read tenant_id из `request.state.auth.tenant_id`).
- **Тест-критерий:** `tests/unit/entrypoints/api/v1/endpoints/test_hitl_auth.py::test_resolve_requires_permission`,
  `test_resolve_filters_by_tenant`.

### API-P0-005 — mobile/router.py fail-open auth + in-memory state (MUTATED → сужено)

- **Path:** `src/backend/entrypoints/api/mobile/router.py:55-93`
- **Evidence:**
  ```python
  _profiles: dict[str, MobileProfile] = {}        # строка 58 — module-level
  _notifications: dict[str, list[MobileNotification]] = {}
  _push_tokens: dict[str, list[PushTokenRequest]] = {}
  _sync_states: dict[str, MobileSyncState] = {}

  async def _verify_mobile_token(authorization: str | None) -> str:
      ...
      token = authorization[7:]
      if not token.startswith("mobile:"):
          raise HTTPException(401, "Invalid mobile token format")
      parts = token.split(":", 2)
      if len(parts) < 3:
          raise HTTPException(401, "Malformed mobile token")
      return parts[1]            # возвращает user_id из СТРОКИ, без валидации
  ```
  Token format `mobile:<user_id>:<anything>` принимается как валидный — никакой
  подписи, никакой JWT-валидации. Злоумышленник с любым user_id получает полный
  доступ к профилю/notifications/push-tokens/sync этого user_id.
  Кроме того, `_wrap` всегда ставит `compressed=True`, и `PayloadOptimizer.compact`
  дропает `None`-поля (что усугубляет PII-утечку через error masking).
- **Cycle-1 статус:** MUTATED (ужесточён): проверил `routers.py` (365 LOC) —
  `mobile_router` НЕ подключён в продакшен-роутере:
  ```bash
  $ grep -n "mobile_router\|get_mobile_router" src/backend/entrypoints/api/v1/routers.py
  (пусто)
  $ grep -rn "from src.backend.entrypoints.api.mobile" src/ --include='*.py'
  src/backend/entrypoints/api/mobile/router.py:23:from src.backend.entrypoints.api.mobile.schemas import (...)
  src/backend/entrypoints/api/mobile/__init__.py:27:from src.backend.entrypoints.api.mobile.router import (...)
  ```
  То есть код **orphan** — существует и тестируется (test_mobile_bff.py, 266 LOC,
  24 теста), но в `app.include_router(mobile_router)` его не вызывают.
  Таким образом, fail-open auth недоступен в production (но это не значит «не
  проблема» — это dead code, который нужно либо подключить с правильной auth,
  либо удалить).
- **Impact (в текущем коде):** dead code + учебный пример fail-open. Если кто-то
  подключит его без переписывания auth — RCE-grade.
- **Минимальная рекомендация:** два варианта.
  1. (YAGNI) Удалить весь `entrypoints/api/mobile/` как неподключённый мёртвый код
     (Cycle 1 backlog T-2.1 / reverse-layer cleanup).
  2. (если продукт хочет mobile) Переписать `_verify_mobile_token` на
     `verify_jwt(authorization, expected_audience="mobile")` через
     `src.backend.core.auth.gateway`; in-memory state заменить на DI-сервис.
- **Тест-критерий:** `test_mobile_router_not_mounted_in_production` (negative test)
  ИЛИ, при варианте 2, `test_verify_mobile_token_rejects_unsigned_token`.

### API-P1-004 — admin_nats dynamic layer violation (RESIDUAL)

- **Path:** `src/backend/entrypoints/api/v1/endpoints/admin_nats.py:63-86`
- **Evidence:**
  ```python
  # строки 63-75
  # Lazy importlib для соблюдения layer policy (entrypoints не зависит
  # от infrastructure статически; metrics-emitter резолвится в runtime).
  # Layer 11 Cycle 2 follow-up: пробовали добавить facade в
  # services/observability/facade.py — но AST-level linter всё равно
  # видит import (даже lazy). Оставляем dynamic bypass как
  # задокументированный compromise — правильное решение требует
  # переноса nats_metrics в services/observability/ или новый
  # entrypoints-level metrics facade.
  import importlib

  metrics_mod = importlib.import_module(
      "src.backend.infrastructure.observability.nats_metrics"
  )
  ```
  Это **сам по себе** cycle 1 уже документированный «compromise» — но AST-level
  linter layer-checker действительно не видит dynamic imports, и в
  `tools/check_layers_allowlist.txt` нет строки для этого файла (entrypoints → infrastructure).
  Cycle 1 занёс это как архитектурный debt.
- **Cycle-1 статус:** RESIDUAL. Код не изменился.
- **Impact:** P1 не из-за уязвимости (есть admin guard `require_admin(OPERATOR, READ_ONLY)`),
  а из-за layer-violation, которая формально работает, но препятствует архитектурной
  чистоте. Не блокирует прод.
- **Минимальная рекомендация:** добавить `src.backend.services.observability.nats_metrics`
  facade, переключить `admin_nats.py` на статический import оттуда, удалить
  «compromise»-комментарий.
- **Тест-критерий:** `make check-layers` без `admin_nats.py` в allowlist.

### API-P1-010 — admin_cron importlib без sandbox (RESIDUAL)

- **Path:** `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:48-56, 86-94, 106-141`
- **Evidence:**
  ```python
  # строки 48-56 — pydantic-валидация
  class CronScheduleRequest(BaseModel):
      name: str = Field(min_length=1, max_length=120)
      cron_expr: str = Field(min_length=1, max_length=255)
      callable_ref: str = Field(
          description="Module-path ``module.path:function`` для задачи.",
          pattern=r"^[\w.]+:[\w]+$",  # ← разрешает ЛЮБОЕ имя модуля
      )
      timezone: str = Field(default="Europe/Moscow", max_length=64)

  # строки 86-94 — резолв
  def _resolve_callable(ref: str) -> Any:
      import importlib
      module_path, _, attr = ref.partition(":")
      if not attr:
          raise ValueError(f"Невалидный callable_ref={ref!r} (нет ':function').")
      module = importlib.import_module(module_path)   # ← import любого модуля
      return getattr(module, attr)
  ```
  Regex `^[\w.]+:[\w]+$` пропускает `os:system`, `subprocess:run`, `shutil:rmtree`,
  `pathlib:Path.rmtree`, `socket:gethostbyname`, и т.п. — всё, что есть в `sys.path`.
- **Cycle-1 статус:** RESIDUAL. Auth-guard есть (`require_admin(OPERATOR, SUPER_ADMIN)`),
  но это по-прежнему RCE для compromised admin-token.
- **Impact:** OPERATOR может выполнить произвольный Python-модуль. Защиты от RCE нет.
  Audit-event для schedule не регистрирует callable_ref (cycle 1 не закрыл).
- **Минимальная рекомендация:** hardcoded whitelist модулей в `core/scheduler/registry.py`
  (например, `{"src.backend.scheduled_tasks": [...]}`). При попытке импорта вне whitelist
  → `HTTPException(400, "callable_ref not in allowed list")`. Альтернатива:
  AST-парсинг callable без выполнения (cycle 1 уже предлагал, не закрыто).
- **Тест-критерий:** `test_schedule_rejects_os_system`, `test_schedule_rejects_subprocess_run`,
  `test_schedule_rejects_relative_import`.

### API-P1-NEW-001 — invocations POST без router-level auth (NEW)

- **Path:** `src/backend/entrypoints/api/v1/endpoints/invocations.py:38-46, 104-123`
- **Evidence:**
  ```python
  # строка 38 — роутер без зависимостей
  router = APIRouter(tags=["Invocations"])

  # строки 41-46 — endpoint через Depends(get_invoker_dep), но без require_auth
  async def post_invocation(
      request_body: InvocationRequestSchema,
      response: Response,
      invoker: Invoker = Depends(get_invoker_dep),
      _rate_limit: None = Depends(get_default_rate_limiter()),
  ) -> InvocationResponseSchema:
  ```
  Подтверждено runtime:
  ```
  router tags: ['Invocations']
  router deps: []
  routes count: 2
    {'POST'}  deps=[]
    {'GET'} /{invocation_id} deps=[]
  ```
- **Impact:** POST `/api/v1/invocations` исполняет произвольный action по имени
  (см. `request_body.action`, `invoker.invoke(InvocationRequest(...))`). Без явного
  auth-guard на роутере. Если global `AuthRequiredMiddleware` отключён, в deploy
  с другим ASGI-стеком или bypass'ом — это RPC-сall для всех.
- **Минимальная рекомендация:** добавить router-level guard:
  ```python
  router = APIRouter(
      tags=["Invocations"],
      dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
  )
  ```
  И проверить, что `Invocations` находится в non-public-prefix allowlist
  `auth_required.py:46-64` (сейчас не в allowlist — это ОК, защита идёт через middleware).
- **Тест-критерий:** `test_post_invocation_requires_auth` (на уровне router, не через
  middleware-bypass).

### API-P2-NEW-001 — mobile_router orphan (NEW)

- **Path:** `src/backend/entrypoints/api/mobile/router.py`, `mobile/__init__.py`,
  `tests/unit/entrypoints/api/mobile/test_mobile_bff.py` (266 LOC, 24 теста).
- **Evidence:** см. API-P0-005.
- **Impact:** dead code в scope; tests только для внутреннего `FastAPI()` (строка 31-33
  test_mobile_bff.py), никогда не подключённого к production-app. Cycle-1 backlog
  T-2.1 «reverse-layer cleanup» — кандидат.
- **Рекомендация:** см. API-P0-005 (удалить или переподключить с правильной auth).

### API-P2-NEW-002 — пустые namespace packages в schemas/ (NEW)

- **Path:** `src/backend/schemas/filter_schemas/__init__.py:1`,
  `src/backend/schemas/route_schemas/__init__.py:1`.
- **Evidence:** каждый файл — 1 строка с docstring. Никаких импортов, ни атрибутов.
  ```bash
  $ grep -rn "filter_schemas\|route_schemas" src/backend/ --include='*.py'
  src/backend/schemas/filter_schemas/__init__.py:1:"""schemas/filter_schemas ..."""
  src/backend/schemas/route_schemas/__init__.py:1:"""schemas/route_schemas ..."""
  ```
- **Impact:** dead code — пустые sub-package'ы без содержимого. Упоминаются в PLAN.md V22
  как S71 W1 namespace markers, но не развиты.
- **Рекомендация:** либо удалить директории, либо заполнить (вне scope этого phase).

### API-P3-NEW-001 — schemas/invocation.py backward-compat shim (NEW)

- **Path:** `src/backend/schemas/invocation.py:1-24`
- **Evidence:**
  ```python
  from src.backend.core.enums.invocation import InvokeMode
  from src.backend.core.types.invocation_command import (
      ActionCommandMetaSchema,
      ActionCommandSchema,
      InvocationOptionsSchema,
      InvocationResultSchema,
  )
  ```
  Импортеры (20+): `entrypoints/{base.py, mcp, mqtt, stream}`, `generator/{invocation, auto_register, marshaller, reflection, actions/__init__}`.
- **Cycle-1 статус:** NEW — shim сохранён целенаправленно (см. docstring
  «S71 W1 docstring marker»). Библиотек-замен нет (это внутренний re-export).
- **Рекомендация (P3, не блокер):** можно оставить как backward-compat; альтернатива —
  `sed`-перевод всех импортеров на `src.backend.core.enums.invocation:InvokeMode`
  и `src.backend.core.types.invocation_command:*`. Это даст -24 LOC (1 файл
  исчезает) и уберёт один уровень indirection.

---

## 5. Cycle-1 residuals (verified или mutated)

| Cycle-1 ID | Что сделано в cycle 1 (из `git log`) | Cycle-2 verification (этот phase-1) | Итог |
|---|---|---|---|
| API-P0-001 admin_actions mock-fallback | T-0.1 admin_actions require_admin guard добавлен (см. `admin_actions.py:31-35`), но mock-fallback остался | Mock-ветка в `admin_actions.py:206-214, 254-272` нетронута | **RESIDUAL** (логика не изменилась) |
| API-P0-002 admin_plugins mock-fallback | T-0.1 admin_plugins require_admin guard добавлен, S62 W1 decomp вынес endpoints | Mock-ветка в `admin_plugins.py:267-277` и `endpoints.py:145-155` идентичны cycle 1 | **RESIDUAL** |
| API-P0-003 generator/setup.py:12-14 broken import | Cycle 1 оставил `# type: ignore[import-not-found]` как workaround | Импорт `src.backend.workflows.workflows_service` всё ещё `ModuleNotFoundError`; тест-only существование | **RESIDUAL** |
| API-P0-004 hitl.py no auth guard | Cycle 1 Phase 4 T-1.2 «SSE/HITL auth» deferred в backlog | `hitl.py:48-129` — нет `Depends(require_auth(...))` ни на одном endpoint'е | **RESIDUAL** |
| API-P0-005 mobile/router.py fail-open + in-memory | Cycle 1 не закрыл; working tree changes не относятся к mobile | Код не подключён в `routers.py` (orphan) — сужает attack surface до test-only | **MUTATED** (dead-code-isolated) |
| API-P1-004 admin_nats importlib infrastructure bypass | Cycle 1 зафиксировал как «compromise» | Логика идентична `ca5bff93`; комментарий «Cycle 2 follow-up» сохранён, но никаких facade не появилось | **RESIDUAL** |
| API-P1-010 admin_cron RCE | Cycle 1 S202 audit добавил guard, но sandbox allowlist не появился | `_resolve_callable` и pydantic-regex идентичны | **RESIDUAL** |

Дополнительно проверены (не были в задании):
- **API-P1-NEW-001 invocations без auth** — NEW, см. detailed evidence.
- **API-P2-NEW-001 mobile_router orphan** — NEW (следствие API-P0-005).
- **API-P2-NEW-002 schemas/{filter,route}_schemas/__init__.py empty** — NEW.
- **API-P3-NEW-001 schemas/invocation.py shim** — NEW (библиотек-замен нет).

---

## 6. Contradictions / overlaps to flag

1. **Layer allowlist count: 175 vs 180.**
   - `wc -l tools/check_layers_allowlist.txt` = **180** (число строк, включая пустые и комментарии).
   - Уникальных путей в allowlist = **175** (соответствует `BASELINE.md cycle 2`: «175 legacy / 0 new»).
   - Заявление пользователя о «росте 173→180» — это **видимый** рост `wc -l` (за счёт 5 не-уникальных строк, например, дублирующихся путей или недавно добавленных комментариев), но **фактического** роста legacy violations нет (175 = baseline).
   - Не приписываю cycle 2: в `git diff ca5bff93 -- tools/check_layers_allowlist.txt` не видно новых строк, относящихся к API-scope. Цифра 175 ↔ 180 — шум между `wc -l` и `grep -c "^src/"`.

2. **Auth-стратегия: defense-in-depth vs single layer.**
   - `AuthRequiredMiddleware` (pure ASGI, V7) — глобальный guard, reject'ит всё,
     что не в `DEFAULT_PUBLIC_PATH_PREFIXES` (14 prefix'ов, см.
     `auth_required.py:46-64`).
   - `hitl.py`, `invocations.py`, `mobile/*` НЕ имеют локального router-level guard.
   - Зависимость только от middleware — fragile: если middleware отключён / deploy
     на другом ASGI-стеке / reverse-proxy auth-off / feature-flag bypass →
     все non-public endpoints открыты. Это и есть API-P0-004 и API-P1-NEW-001.

3. **Backward-compat shim vs dead code.**
   - `schemas/invocation.py` — полезный shim (20+ импортеров).
   - `mobile_router` — orphan, dead code.
   - `schemas/filter_schemas/__init__.py`, `schemas/route_schemas/__init__.py` —
     namespace markers, никогда не наполнялись.
   - Разные категории: shim живой, mobile_router стоит удалить, namespace markers
     — решить по roadmap.

4. **Mock-fallback vs mock-only-for-tests.**
   - `admin_actions._mock_actions()` и `admin_plugins._mock_plugins()` —
     production-fail-open (см. P0).
   - `test_setup._mock_extension_modules()` — test-only (нормально).
   - Не путать категории: разные finding IDs, разные фиксы.

5. **`generator/setup.py` vs `dsl/commands/setup.py`.**
   - Это **разные** модули:
     - `src/backend/entrypoints/api/generator/setup.py` — broken import (см. P0).
     - `src/backend/dsl/commands/setup.py` — рабочий, вызывается из
       `app_factory.py:222`, `lifecycle/startup.py:411`, `workflow/worker.py:156`.
   - В задании cycle 1 упомянут только `generator/setup.py` — это правильно.

---

## 7. Readiness score

**Формула:** `score = 100 - 20·P0 - 10·P1 - 4·P2 - 2·P3 - 1·P4`.

Подсчёт:
- P0 = 5 (API-P0-001, API-P0-002, API-P0-003, API-P0-004, API-P0-005)
- P1 = 3 (API-P1-004, API-P1-010, API-P1-NEW-001)
- P2 = 2 (API-P2-NEW-001 mobile orphan, API-P2-NEW-002 schemas namespace markers)
- P3 = 1 (API-P3-NEW-001 invocation shim)
- P4 = 0

**Score = 100 − 20·5 − 10·3 − 4·2 − 2·1 = 100 − 100 − 30 − 8 − 2 = −40.**

Нижняя граница — clamp до **0**.

**Обоснование:**
- ≥80 запрещён при наличии P0/P1 — условие выполнено (score = 0, не 80+).
- 5 P0 критических: 2 admin mock-fallback (silent-success), 1 broken import,
  1 hitl без auth, 1 mobile fail-open (изолированно, но всё ещё P0).
- 3 P1: 2 layer-violations (RCE/CVE-категория), 1 invocations без auth.
- API не готов к production hardening (Sprint 36 Production Readiness 90%+).
- Strengths (см. §2) НЕ компенсируют security/layer issues.

---

## 8. Recommended next tasks (cycle 2 phase 2 candidates)

| Task | Scope | Effort | Impact | Notes |
|---|---|---|---|---|
| T-API-1: Закрыть admin_actions mock-fallback → 503 | `admin_actions.py:206-214, 254-272` + `_mock_actions/_mock_spec` | S | P0 | fail-closed security |
| T-API-2: Закрыть admin_plugins mock-fallback → 503 | `admin_plugins.py:267-277`, `endpoints.py:145-155` + `_mock_plugins/_mock_manifest` | S | P0 | fail-closed + убрать data-state divergence |
| T-API-3: Удалить или починить `generator/setup.py` broken import | `generator/setup.py:12-14` | S | P0 | либо удалить модуль, либо перевести на `src.backend.services.workflows.<X>.get_workflows_service` |
| T-API-4: hitl.py router-level auth + tenant filter | `hitl.py:24` + per-endpoint tenant_id | M | P0 | Cycle 1 Phase 4 deferred T-1.2 |
| T-API-5: удалить `mobile/` или переподключить с JWT | `mobile/router.py`, `mobile/__init__.py` | M | P0 (если переподключать) / P2 (если удалять) | YAGNI рекомендует удалить |
| T-API-6: invocations router-level auth | `invocations.py:38` | S | P1 | defense-in-depth |
| T-API-7: admin_cron callable_ref whitelist | `admin_cron.py:48-56, 86-94` + новый `core/scheduler/registry.py:ALLOWED_MODULES` | M | P1 | RCE prevention |
| T-API-8: admin_nats facade в services/observability | `admin_nats.py:71-75` + новый facade | M | P1 | layer violation cleanup |
| T-API-9: удалить schemas/{filter,route}_schemas namespace markers | `schemas/filter_schemas/__init__.py`, `schemas/route_schemas/__init__.py` | XS | P2 | dead code |
| T-API-10: schemas/invocation shim → direct imports | `schemas/invocation.py` + 20 импортеров | M | P3 | backward-compat cleanup |

Effort key: XS = ≤30 LOC, S = ≤100 LOC, M = ≤300 LOC.

---

## 9. Commands run

```bash
# Проверка рабочей копии
git status --short | head -30

# Layer checker (baseline numbers)
timeout 30 python tools/check_layers.py --root src | head -3
wc -l tools/check_layers_allowlist.txt            # 180
grep -c "^src/" tools/check_layers_allowlist.txt   # 175
grep -c "^src/backend/entrypoints/" tools/check_layers_allowlist.txt   # 59

# Security allowlist baseline
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
# 35

# Broken import verification
.venv/bin/python -c "import src.backend.workflows.workflows_service"
# ModuleNotFoundError: No module named 'src.backend.workflows'
.venv/bin/python -c "
import importlib
mod = importlib.import_module('src.backend.entrypoints.api.v1.endpoints.invocations')
print('router tags:', mod.router.tags)
print('router deps:', mod.router.dependencies)
"
# router tags: ['Invocations']
# router deps: []
# routes count: 2
#   {'POST'}  deps=[]
#   {'GET'} /{invocation_id} deps=[]

# Module / импорт-проверка
grep -rn "from src.backend.workflows" src/ --include='*.py' | head -5
# src/backend/infrastructure/workflow/worker_probes.py:3:# S168 W13 P2-7: moved from src/backend/workflows/...
# src/backend/infrastructure/workflow/outbox_worker.py:1:# S168 W13 P2-7: moved from src/backend/workflows/...
# src/backend/schemas/processing_result.py:3:# S168 W12 P2-7: moved from src/backend/workflows/dicts.py
# src/backend/entrypoints/api/generator/setup.py:12:from src.backend.workflows.workflows_service import (  # type: ignore[import-not-found]  # legacy module path; not yet implemented

# Workflow service существование
grep -rn "send_notification_workflow\|order_processing_workflow\|get_workflows_service" src/backend/ --include='*.py'
# 4 hits — все в generator/setup.py (broken import)

# Auth-guard покрытие admin endpoints
grep -rn "Depends(require_admin" src/backend/entrypoints/api/v1/endpoints/admin_*.py | head -10

# mobile_router mounting
grep -n "mobile_router\|get_mobile_router" src/backend/entrypoints/api/v1/routers.py
# (пусто — orphan)
grep -rn "from src.backend.entrypoints.api.mobile" src/ --include='*.py' | head -5
# (только self-imports из mobile/*)

# Импорт-сайты schemas/invocation (для P3)
grep -rn "from src.backend.schemas" src/backend/entrypoints/ --include='*.py' | head -20

# TODO / FIXME / pass / NotImplemented в scope (sanity)
grep -rn "TODO\|FIXME\|pass$\|NotImplemented\|XXX" src/backend/entrypoints/api/v1/endpoints/hitl.py \
  src/backend/entrypoints/api/mobile/ \
  src/backend/entrypoints/api/v1/endpoints/admin_cron.py \
  src/backend/entrypoints/api/v1/endpoints/admin_nats.py \
  src/backend/entrypoints/api/v1/endpoints/admin_actions.py \
  src/backend/entrypoints/api/v1/endpoints/admin_plugins.py \
  src/backend/entrypoints/api/generator/ \
  --include='*.py' 2>&1 | head -5
# 1 hit: generator/actions/crud/__init__.py:19: pass (TYPE_CHECKING guard, не stub)
```

---

## 10. Итог для parent agent

- **Readiness score:** 0 / 100 (clamped; P0 блокируют ≥80).
- **P0 / P1 / P2 / P3 / P4:** 5 / 3 / 2 / 1 / 0.
- **Top blockers:** API-P0-002 (admin_plugins silent-success toggle), API-P0-001 (admin_actions silent-success invoke), API-P0-004 (hitl без auth), API-P0-003 (broken import generator/setup.py), API-P1-010 (admin_cron RCE через importlib).
- **Cycle-1 residuals:** API-P0-001/002/003/004 и API-P1-004/010 — RESIDUAL;
  API-P0-005 — MUTATED (dead-code-isolated, не подключён в production router).
- **Отчёт сохранён:** `docs/audit/swarm-2026-08-06/cycle-2/phase-1/05-api.md`.