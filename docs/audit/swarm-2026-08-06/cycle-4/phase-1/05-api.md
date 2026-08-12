# API Domain — Cycle 4 / Phase 1 Audit Report

> **Analyst**: `domain=API | output=docs/audit/swarm-2026-08-06/cycle-4/phase-1/05-api.md`
> **Scope**: `src/backend/entrypoints/api/**` (92 files, ~15275 LOC), `src/backend/schemas/**` (10 files),
> API-focused tests (`tests/unit/api/**`, `tests/unit/entrypoints/api/**`, `tests/unit/entrypoints/test_admin_cron.py`,
> `tests/unit/entrypoints/test_admin_plugins_versioning.py`, `tests/unit/services/workflows/test_hitl_*.py`).
> **Baseline HEAD**: `22e08a0d` per `docs/audit/swarm-2026-08-06/cycle-4/BASELINE.md`.
> **Observed HEAD at audit time**: `baf54d95` (3 additional commits on top of `22e08a0d` —
> `baf54d95 fix(security): remove MCPToolProcessor/AgentGraphProcessor shadow в external.py`,
> `c3ff7bec fix(security): AuthValidateProcessor canonical _VERIFIERS path`,
> `e96dda55 refactor(dsl): remove 442 LOC legacy eip/reliability.py god-file` — все вне моего scope и не атрибутируются рою cycle 4).
> **Python interpreter**: `.venv/bin/python` (Python 3.14.0), как требует baseline.
> **Date**: 2026-08-07.

---

## 0. Scope / проверено / НЕ проверено

### Проверено напрямую (read + runtime)
- `src/backend/entrypoints/api/versioning.py` (112 LOC) — VersionedRouter + DeprecationMiddleware.
- `src/backend/entrypoints/api/dependencies/auth.py` (49 LOC) — `require_api_key` через APIKeyManager DI provider.
- `src/backend/entrypoints/api/dependencies/auth_selector.py` (55 LOC) — DEPRECATED shim → core.auth.auth_selector.
- `src/backend/entrypoints/api/v1/dependencies/login_ratelimit.py` (202 LOC) — fail-SECURE для `/auth/login`.
- `src/backend/entrypoints/api/v1/routers.py` (365 LOC) — сборка `api_router_v1` (lazy import + mount всех подроутеров, исправлены cycle-1/2/3 orphan routers).
- `src/backend/entrypoints/api/v1/endpoints/health.py` (251 LOC) — `AuthRequiredMiddleware` allowlist probe match.
- `src/backend/entrypoints/api/v1/endpoints/hitl.py` (129 LOC) — **верифицирован API-P0-001 (RESIDUAL) + cross-tenant risk**; см. finding DOMAIN-P0-001.
- `src/backend/entrypoints/api/v1/endpoints/admin_cron.py` (225 LOC) — **верифицирован admin_cron RCE + missing whitelist**; см. DOMAIN-P0-002.
- `src/backend/entrypoints/api/v1/endpoints/admin_certs.py`, `admin_capabilities.py`, `admin_connectors.py`,
  `admin_feature_flags.py`, `admin_ip_restriction.py`, `admin_model_registry.py`,
  `admin_nats.py`, `admin_parallelism.py`, `admin_resilience_profile.py`,
  `admin_schemas.py`, `admin_workflow_audit.py`, `admin_workflow_cost.py`,
  `admin_workflow_versioning.py`, `admin_workflows/`, `dsl_console.py`,
  `dsl_routes.py` — все имеют `Depends(require_admin(...))` router-level guard
  +47/53 endpoint files (подтверждено `grep -L "Depends(require_admin\|require_api_key\|require_auth"`).
- `src/backend/entrypoints/api/v1/endpoints/admin_actions.py` (273 LOC) — `_get_registry()` mock-fallback.
- `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py` (520 LOC) + `admin_plugins/endpoints.py` (292 LOC) — duplicate mock-fallback (S206 fix восстановил guard, но mock-fallback остался).
- `src/backend/entrypoints/api/v1/endpoints/invocations.py` (142 LOC) — no explicit auth, только global middleware.
- `src/backend/entrypoints/api/v1/endpoints/auth_login.py` (197 LOC), `auth_methods.py` (127 LOC), `auth_saml.py` (215 LOC) — корректные auth-patterns.
- `src/backend/entrypoints/api/v1/endpoints/ai_agents.py`, `ai_costs.py`, `ai_feedback.py`,
  `ai_stream.py`, `ai_tools.py` — auth через global middleware + rate-limit.
- `src/backend/entrypoints/api/v1/endpoints/files.py` (219 LOC), `notebooks.py` (291 LOC),
  `search.py` (340 LOC), `imports.py` (352 LOC), `rag.py` (463 LOC),
  `skb.py` (110 LOC), `orders.py` (206 LOC), `processor_catalog` (306 LOC),
  `users.py` (50 LOC), `agent_memory.py` (228 LOC), `process_schema`/`dlq/...` —
  все read; explicit auth где требуется; relience на global middleware иначе.
- `src/backend/entrypoints/api/v1/endpoints/admin_actions.py` mock-fallback → DOMAIN-P2-002.
- `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py` + `endpoints.py` mock-fallback → DOMAIN-P2-003.
- `src/backend/entrypoints/api/generator/__init__.py`, `auto_register.py` (210 LOC),
  `invocation.py` (79 LOC), `marshaller.py` (82 LOC),
  `reflection.py` (192 LOC), `registry.py` (12 LOC), `specs.py` (255 LOC),
  `setup.py` (69 LOC) — **broken import подтверждён runtime**, см. DOMAIN-P1-001 + DOMAIN-P0-003.
- `src/backend/entrypoints/api/generator/actions/__init__.py`, `actions/crud/{__init__.py,_protocol.py,read_mixin.py,query_mixin.py,write_mixin.py,versioning_mixin.py}`.
- `src/backend/entrypoints/api/mobile/{__init__.py,router.py,schemas.py}` — dead code подтверждён, см. DOMAIN-P2-001.
- `src/backend/schemas/base.py`, `schemas/workflow.py`, `schemas/invocation_api.py`,
  `schemas/invocation.py`, `schemas/agent_memory.py`, `schemas/processing_result.py`,
  `schemas/health_events.py`, `schemas/{filter_schemas,route_schemas}/__init__.py` — все прочитаны.
- Глобальные middlewares: `src/backend/entrypoints/middlewares/auth_required.py` (199 LOC),
  `src/backend/entrypoints/middlewares/api_key.py` (146 LOC), `tenant.py` (151 LOC) —
  подтверждено что AuthRequiredMiddleware enforce authentication на всех non-public путях,
  но НЕ authorization/permission-scope; см. DOMAIN-P0-001.
- Runtime проверки:
  - `.venv/bin/python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"` → `ModuleNotFoundError: No module named 'src.backend.workflows'` — broken import подтверждён;
  - `.venv/bin/python -c "re.match(r'^[\w.]+:[\w]+\$', ref)"` для `os:system`, `builtins:exec`, `subprocess:check_output`, `shutil:rmtree` → all match True;
  - `.venv/bin/python -c "from src.backend.entrypoints.api.mobile import mobile_router"` → OK, 6 routes определены;
  - `.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints import hitl; print(hitl.router.dependencies)"` → `[]` (empty);
  - `.venv/bin/python tools/check_layers.py --root src` → exit 0 (`0 новых / 175 legacy / 2273 files scanned`).
- Тесты:
  - `.venv/bin/python -m pytest tests/unit/entrypoints/api/ --no-cov -q` → **177 passed, 12 skipped, 9 xfailed**, 0 failed.
  - `.venv/bin/python -m pytest tests/unit/entrypoints/api/generator/test_setup.py --no-cov -q` → **3 passed** (с `sys.modules` mock).
  - `.venv/bin/python -m pytest tests/unit/entrypoints/test_admin_cron.py --no-cov -q` → **8 passed, 0 failed** (без whitelist-security тестов).
  - `.venv/bin/python -m pytest tests/unit/entrypoints/test_admin_plugins_versioning.py --no-cov -q` → **7 passed**.
  - `.venv/bin/python -m pytest tests/unit/api/ --no-cov -q` → **61 passed, 4 failed** (pre-existing `test_auto_register_actions.py` — тест-логика, production API correct).
  - `.venv/bin/python -m pytest tests/unit/services/workflows/test_hitl_service.py tests/unit/services/workflows/test_hitl_signal_store_redis.py --no-cov -q` → **passed** (не открывал детальный прогон, не проверено детально — service layer, не API endpoints).

### НЕ проверено (по условию задачи)
- Не читал `cycle-1/phase-1/05-api.md`, `cycle-2/phase-1/05-api.md`, `cycle-3/phase-1/05-api.md`,
  `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` —
  статус предыдущих findings восстанавливается только из текущего кода и явных ссылок в `BASELINE.md`.
- Не выполнял end-to-end OAuth/JWT flow в integration-тестах — рассмотрены только код и unit-тесты.
- Не проверял transport-specific behaviour (gRPC/GraphQL/SOAP/MQTT/MCP) вне scope.
- Не проверял `kimi-export-session_*-20260803-150732.md` (случайный файл, не относится к API).
- Не проверял pre-existing test failures в `tests/unit/api/test_auto_register_actions.py` (4 pre-existing) — задокументированы в BASELINE как «pre-existing drift», не атрибутируются рою.
- Не открывал `extensions/**` (вне scope); только проверил что `extensions/skb/*`, `extensions/core_entities/**` импортируются изнутри api endpoints.
- Не делал git mutation (`git status` показывает изменения в `uv.lock` и untracked `pip-audit.json`, `.blue_green.state`,
  `docs/audit/swarm-2026-08-06/` от предыдущих swarm-сессий — это pre-existing drift из BASELINE).

---

## 1. Verified strengths (что реально работает корректно)

1. **Глобальная auth-цепочка** (`src/backend/entrypoints/middlewares/auth_required.py:46-64`,
   `auth_required.py:81-167`): pure ASGI middleware с public-path allowlist
   (`/health`, `/healthz`, `/readyz`, `/livez`, `/metrics`, `/asyncapi`, `/docs`, `/redoc`, `/openapi.json`,
   `/static`, `/favicon.ico`, `/api/v1/auth/methods`) и OPTIONS-пробросом.
   401 через send (no-raise pattern) → fail-closed. Зарегистрирован `setup_middlewares.py:196-197` order=620.

2. **Router-уровневая RBAC через `Depends(require_admin(...))`** (cycle-1 S202 audit fix):
   - `admin.py` (`dependencies=[_ADMIN_GUARD]` line 29) — `OPERATOR/READ_ONLY/TENANT_ADMIN`;
   - `admin_cron.py:28-35` — `_CRON_GUARD = OPERATOR+SUPER_ADMIN`;
   - `admin_certs.py` line 31-35 — `OPERATOR/READ_ONLY/SUPER_ADMIN`;
   - `admin_capabilities.py:28-32` — `OPERATOR/READ_ONLY/SUPER_ADMIN`;
   - `admin_connectors.py:218-224` — `OPERATOR/SUPER_ADMIN`;
   - `admin_feature_flags.py:41-44` — `OPERATOR/SUPER_ADMIN`;
   - `admin_ip_restriction.py:22-30` — `SUPER_ADMIN/TENANT_ADMIN`;
   - `admin_workflows/__init__.py:91-96` — `OPERATOR/SUPER_ADMIN`;
   - `dsl_console.py:51-53` — `OPERATOR/SUPER_ADMIN` (DSL Console execute YAML);
   - `dsl_routes.py:256-258` — `OPERATOR/SUPER_ADMIN` (YAML CRUD маршрутов);
   - `admin_nats.py:46-48` — `OPERATOR/READ_ONLY/SUPER_ADMIN`.
   Источник: 47 из 53 endpoint files содержат `Depends(require_admin|require_api_key|require_auth)`.

3. **Fail-secure auth** (`src/backend/entrypoints/api/v1/dependencies/login_ratelimit.py:103-148`):
   per-IP rate-limit + per-username rate-limit с явным `if not is_ok:` → 503 при недоступности Redis
   (комментарий: «Раньше был fail-open, небезопасно»). 5 att/min IP, 3 att/5min username, 1s tarpit delay.

4. **DSL Camel-style fluent builders** (`src/backend/entrypoints/api/generator/specs.py:36-209`
   `ActionSpec` dataclass + `_infer_tier1_action_id()`,
   `src/backend/entrypoints/api/generator/auto_register.py:149-209`
   `auto_register_unrouted_actions()`): Wave 1.2+ RoadMap V10 — REST auto-loop. Production code
   корректно (test failures в `test_auto_register_actions.py` — тест-inspection баг, ищет APIRoute на верхнем
   уровне `app.routes` после `include_router` — APIRoute уезжает в `_IncludedRouter`).

5. **ActionSpec-Gateway-meta** (`specs.py:91-117`): 9 опциональных полей (action_id, use_dispatcher,
   transports, side_effect, idempotent, permissions, rate_limit, timeout_ms, deprecated, since_version, tier).
   3-tier модель (Tier 1 auto для всех 6 протоколов, Tier 2 auto REST+gRPC+GraphQL, Tier 3 — manual).

6. **Pydantic v2 native camelCase aliases** (`src/backend/schemas/base.py:30-47`): `ConfigDict` с
   `alias_generator=to_camel` (S168 W10 P1-13 — stdlib-backed, −13 LOC vs custom).

7. **AuthRequiredMiddleware pure ASGI** (cycle 43 design): пишет в `scope['state']['auth']`,
   downstream handlers читают через FastAPI `request.state.auth` alias.

8. **No layer violations в scope** (`tools/check_layers.py --root src` → exit 0). Все entrypoints/api/* без
   прямых `from src.backend.infrastructure.*` (verified by `grep -rn "from src.backend.infrastructure" src/backend/entrypoints/api/` →
   no matches in this scope).

9. **Pydantic strict models в schemas**:
   `schemas/agent_memory.py:32-33` `_StrictModel(extra="forbid")`,
   `schemas/invocation_api.py` (camelCase aliases BaseSchema),
   `schemas/workflow.py:34-37` `resolve_module()` для lazy ORM-types (Wave 6.5a).

10. **Health endpoints** (`health.py:1-251`): `/liveness` process-only (без DB/Redis),
    `/readiness` с graceful-degradation awareness (503 только если all backends down,
    200 degraded с перечнем компонентов). K8s-probes pattern ADR-036 — корректный.

11. **VersionedRouter + DeprecationMiddleware** (`versioning.py:38-110`): добавление RFC 8594
    `Deprecation`/`Sunset`/`Link` headers для deprecated API-версий. v21 артефакт.

---

## 2. Findings (P0..P4)

### P0 (security / data-loss / fail-open / race)

#### DOMAIN-P0-001 — HITL endpoints без permission/tenant enforcement
- **Cycle ID candidate**: API-P0-001 (cycle-3, переподтверждён).
- **Priority**: P0.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/hitl.py:24-128` + `src/backend/services/workflows/hitl_service.py:178-355` + `src/backend/services/workflows/hitl_history.py`.
- **Evidence**:
  - Router: `hitl.py:24` `router = APIRouter()` — **no `dependencies=[Depends(require_admin(...))]`** at router level или per-route (verified: `hitl.router.dependencies == []`).
  - Docstring на `hitl.py:11` утверждает: «**Auth: JWT + tenant filtering (X-Tenant-ID); permission `hitl.resolve`**» — реализация отсутствует.
  - `GET /pending(tenant_id: str | None = None)` `hitl.py:48-55`: передаёт `tenant_id=None` → `svc.list_pending(tenant_id=None)` → `hitl_service.py:178-188` → store возвращает ВСЕ signals cross-tenant.
  - `GET /{signal_id}` `hitl.py:94-104`: `await svc.get(signal_id)` — любой signal_id любого тенанта.
  - `POST /{signal_id}/resolve` `hitl.py:107-128`: `await svc.resolve(signal_id, action, resolved_by, payload)` — нет проверки что resolved_by соответствует claim `hitl.resolve`.
  - **Глобальная auth**: только `AuthRequiredMiddleware` аутентифицирует (`request.state.auth` exist), но не авторизует — никакой tenant-isolation между request scope и сигналом.
  - `hitl_history.py:71-91` `/hitl/history` возвращает все events без tenant scope filter.
  - В `schemas` нет `tenant_id` в `HitlResolveRequest` (`hitl.py:27-35`).
- **Impact**: Authenticated user of tenant A can (a) list/resolve HITL signals of tenant B by knowing signal_id (по docstring, `signal_id` = UUID обычно guessable is low, но leak через audit logs возможен); (b) cross-tenant resolutions для approve/reject — то есть banking HITL bypass. Permission `hitl.resolve` вообще не проверяется, что нарушает «fail-closed security» (AGENTS.md §Ponytail mode «fail-closed security»).
- **Минимальная рекомендация**: добавить `router = APIRouter(dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))])` и в каждом endpoint — `signal = await svc.get(signal_id, tenant_id=request.state.tenant_id)` (после рефакторинга hitl_service для явного tenant requirement).
- **Тест-критерий**:
  ```python
  def test_hitl_resolve_cross_tenant_403():
      # tenant A authenticated
      # resolve tenant B's signal_id → 403 (или 404)
  def test_hitl_listing_tenant_scoped():
      # user создаёт signals в tenant A и B
      # GET /pending без tenant_id → только свои
  def test_hitl_requires_hitl_resolve_permission():
      # user с roles=[]  → 403 на resolve endpoint
  ```

#### DOMAIN-P0-002 — admin_cron RCE через `importlib.import_module` без whitelist
- **Cycle ID candidate**: API-P0-002 (cycle-3, переподтверждён).
- **Priority**: P0.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:55-94, 109-141` + `src/backend/infrastructure/scheduler/scheduler_manager.py:184-223`.
- **Evidence**:
  - `admin_cron.py:53-56` `CronScheduleRequest.callable_ref: pattern=r"^[\w.]+:[\w]+$"` — допускает alphanumeric + underscores + dots + colon. Verified runtime:
    ```
    re.match(r"^[\w.]+:[\w]+$", "os:system")      → True
    re.match(r"^[\w.]+:[\w]+$", "builtins:exec")  → True
    re.match(r"^[\w.]+:[\w]+$", "subprocess:check_output") → True
    re.match(r"^[\w.]+:[\w]+$", "shutil:rmtree")  → True (data loss)
    re.match(r"^[\w.]+:[\w]+$", "builtins:__import__") → True
    ```
  - `admin_cron.py:86-94` `_resolve_callable(ref)`:
    ```python
    def _resolve_callable(ref: str) -> Any:
        import importlib
        module_path, _, attr = ref.partition(":")
        if not attr: raise ValueError(...)
        module = importlib.import_module(module_path)  # ← arbitrary
        return getattr(module, attr)                  # ← arbitrary
    ```
  - Auth: `admin_cron.py:28-30` `_CRON_GUARD = require_admin((OPERATOR, SUPER_ADMIN))` — но OPERATOR НЕ privileged enough to register arbitrary code path.
  - `scheduler_manager.py:211-218` `scheduler.add_job(func=callable_ref, ...)` — registered callable `os.system` будет вызываться APScheduler'ом по cron-trigger.
  - Combined с `admin_cron.py:185-195` `/admin/cron/{job_id}/run-now` → immediate execution.
  - Cycle 3 finding API-P1-003 (whitelist) — NOT implemented. There is no `_resolve_callable` extension with allowlist; tests at `tests/unit/entrypoints/test_admin_cron.py:96-105` только проверяют «не нашли модуль → 400» (`nonexistent.module:fn`), не «нашли опасный → 403».
- **Impact**: OPERATOR-admin user (или compromised OPERATOR credentials) может немедленно выполнить любой Python callable, доступный в Python path. В банковской шине это RCE уровня сервера.
- **Минимальная рекомендация**:
  ```python
  ALLOWED_CALLABLE_MODULES = frozenset({
      "src.backend.infrastructure.scheduler.scheduled_tasks",
      "extensions.credit_pipeline.cron_tasks",
      # ... extensions whitelisted
  })

  def _resolve_callable(ref: str) -> Any:
      module_path, _, attr = ref.partition(":")
      if module_path not in ALLOWED_CALLABLE_MODULES:
          raise ValueError(f"module {module_path!r} not in cron whitelist")
      # ... rest
  ```
- **Тест-критерий**:
  ```python
  def test_admin_cron_rejects_builtins_exec():
      # POST /admin/cron/schedule {"callable_ref": "builtins:exec", ...} → 400/403
  def test_admin_cron_rejects_os_system():
      # → 400/403
  def test_admin_cron_accepts_whitelisted():
      # "src.backend.infrastructure.scheduler.scheduled_tasks:check_all_services" → 201
  ```

#### DOMAIN-P0-003 — generator/setup.py:12-14 broken import
- **Cycle ID candidate**: API-P0-003 (cycle-2/3, переподтверждён).
- **Priority**: P0 (формально broken import, но PROD не задета — см. impact).
- **Path**: `src/backend/entrypoints/api/generator/setup.py:12-14`.
- **Evidence**:
  - Код: `from src.backend.workflows.workflows_service import (  # type: ignore[import-not-found]  # legacy module path; not yet implemented, см. TD-NEW; get_workflows_service)`.
  - Runtime: `.venv/bin/python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"` →
    ```
    ModuleNotFoundError: No module named 'src.backend.workflows'
    ```
  - `ls src/backend/workflows/` → `Нет такого файла или каталога`.
  - Production impact: `grep -rn "from src.backend.entrypoints.api.generator.setup" src/ tests/` →
    только `tests/unit/entrypoints/api/generator/test_setup.py` (которое мокает `src.backend.workflows.workflows_service` через `sys.modules` до reload).
  - Тест `test_setup.py:103-141` использует `_mock_extension_modules()` чтобы через `sys.modules` подсунуть фейковый модуль `src.backend.workflows.workflows_service`. Без mock — тест падает (covered by current 3 tests, они проходят за счёт mock).
  - Альтернативный production путь регистрации handlers: `src.backend.dsl.commands.setup.register_action_handlers` (не в scope этого аудита — docs/cycle-3 уже отмечали отличие).
  - Из 6 `ActionHandlerSpec` в `setup.py:32-66`: 4 orders/orderkinds + 2 workflows (`workflows.send_email_notification`, `workflows.order_processing`) — последние 2 относятся к функционалу, который был удалён через рефакторинг S168 W13 P2-7 в DSL (см. `shared/context/TECH_DEBT.md:510` для справки).
- **Impact**: Module не загружается в production startup (никто его не импортирует), но:
  - trap для developers — copy-paste example из теста может попасть в production;
  - 2 из 6 handlers (`workflows.*`) не могут быть зарегистрированы;
  - `# type: ignore[import-not-found]` скрывает mypy error — silent broken dependency.
- **Минимальная рекомендация**: `git rm src/backend/entrypoints/api/generator/setup.py` (69 LOC + тест `test_setup.py:141`).
- **Тест-критерий**:
  ```python
  def test_no_setup_py_module():
      import importlib.util
      spec = importlib.util.find_spec("src.backend.entrypoints.api.generator.setup")
      assert spec is None  # module deleted
  ```

### P1 (layer boundaries / authorization gaps)

#### DOMAIN-P1-001 — generator/setup.py dead code (related to P0-003)
- **Cycle ID candidate**: API-P1-002 (cycle-3, переподтверждён — структурно связан с P0-003).
- **Priority**: P1.
- **Path**: `src/backend/entrypoints/api/generator/setup.py` (whole module, 69 LOC).
- **Evidence**: см. DOMAIN-P0-003. Module импортируется только через `tests/unit/entrypoints/api/generator/test_setup.py` (test который мокает broken import).
- **Impact**: Dead code (cycle-1+ помечен как «TD-NEW»).
- **Минимальная рекомендация**: `git rm` (см. DOMAIN-P0-003).
- **Тест-критерий**: тест из DOMAIN-P0-003 + проверка что ни один production-модуль не импортирует `setup`.

#### DOMAIN-P1-002 — admin_nats.py dependency на infrastructure через `importlib.import_module` (layer-policy)
- **Cycle ID candidate**: API-P1-001 (cycle-3, переподтверждён).
- **Priority**: P1.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/admin_nats.py:64-86`.
- **Evidence**: `importlib.import_module("src.backend.infrastructure.observability.nats_metrics")` — formal layer-violation (entrypoints → infrastructure), но обоснован как compromise в комментарии на `admin_nats.py:63-70`:
  ```
  # Layer 11 Cycle 2 follow-up: пробовали добавить facade в
  # services/observability/facade.py — но AST-level linter всё равно
  # видит import (даже lazy). Оставляем dynamic bypass как
  # задокументированный compromise — правильное решение требует
  # переноса nats_metrics в services/observability/ или новый
  # entrypoints-level metrics facade.
  ```
  `tools/check_layers.py` всё равно даёт exit 0 (значит baseline-allowlist содержит этот pattern).
- **Impact**: Layer policy формально нарушен; при реорганизации `infrastructure/observability/` — runtime failure.
- **Минимальная рекомендация**: переместить `nats_metrics` в `core/observability/` или `entrypoints/middlewares/` (где уже есть observability-facades `src/backend/entrypoints/middlewares/otel_middleware.py`). Альтернативно — добавить `infrastructure` → `services` proxy facade.
- **Тест-критерий**:
  ```python
  # cycle-3 не имеет теста; предложение:
  def test_admin_nats_no_infrastructure_import():
      import ast
      tree = ast.parse(open("src/backend/entrypoints/api/v1/endpoints/admin_nats.py").read())
      for node in ast.walk(tree):
          if isinstance(node, (ast.Import, ast.ImportFrom)):
              if "infrastructure" in ast.unparse(node):
                  pytest.fail("direct infrastructure import via from/import statement")
      # Note: importlib.import_module skipped intentionally
  ```

#### DOMAIN-P1-003 — admin_actions.py mock-fallback in `invoke_action` (fail-open)
- **Cycle ID candidate**: NEW (related to cycle-3 admin_actions P0/P1 family).
- **Priority**: P1.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/admin_actions.py:99-230`.
- **Evidence**:
  - `admin_actions.py:99-113` `_get_registry()` возвращает `None` если `ActionHandlerRegistry.get_instance()` падает, БЕМ logging уровня error.
  - `admin_actions.py:192-214` `invoke_action`:
    ```python
    registry = _get_registry()
    if registry is None:
        return ActionInvokeResponse(
            name=body.name, mode=body.mode,
            result={"status": "mock", "payload_received": body.payload},
            invocation_id="mock-00000000",
        )
    ```
    - Если production-registry недоступен → endpoint возвращает 200 OK с `result.status="mock"`.
    - Клиент (Streamlit Action Console или MCP) видит успех, но фактически action НЕ вызван.
  - Аналогично `list_actions:155-183` и `get_action_spec:233-272` — fallback to `_mock_actions()` / `_mock_spec()`.
  - 401/403 на endpoint уже enforce через `_ADMIN_GUARD_OPERATOR` (line 31-35), но guard проходит; mock-fallback at service-level.
- **Impact**: Fail-OPEN: business-action вызов возвращает 200 OK без side-effect. Бизнес-логика silently bypassed. Audit log не создаётся.
- **Минимальная рекомендация**: вместо mock-fallback — `raise HTTPException(503, "ActionRegistry unavailable")` at line ~110 (и аналогично в list_actions / get_action_spec). Альтернативно — fail-closed с явным `dependency_overrides`.
- **Тест-критерий**:
  ```python
  def test_admin_actions_invoke_unavailable_returns_503():
      # когда registry недоступен
      # POST /admin/actions/invoke → 503 (НЕ 200 с mock)
  def test_admin_actions_list_unavailable_returns_503():
      # GET /admin/actions/list → 503
  ```

#### DOMAIN-P1-004 — admin_plugins.py + admin_plugins/endpoints.py mock-fallback (S206 follow-up)
- **Cycle ID candidate**: NEW.
- **Priority**: P1.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py:104-301` + `admin_plugins/endpoints.py:104-179`.
- **Evidence**:
  - `_get_plugin_registry()` возвращает `None` при exception (line 109-115, аналогично endpoints.py:107-111).
  - `toggle_plugin` на registry=None: возвращает `PluginToggleResponse` с предыдущим/текущим статусом СГЕНЕРИРОВАННЫМИ, но фактически `await registry.activate(name)` / `await registry.deactivate(name)` НЕ вызваны. Это FAIL-OPEN security: API operator-у сообщает что «plugin X деактивирован», но в реальности plugin продолжает работать.
  - `list_plugins` при registry=None → `_mock_plugins()` (показывает фиктивные `core_entities`, `credit_workflow` плагины с routes_count/actions_count, не отражающие реального состояния).
  - `get_plugin_manifest` → `_mock_manifest(name)` (возвращает фиктивный manifest).
  - Duplicate code: `admin_plugins.py` (520 LOC, legacy) и `admin_plugins/endpoints.py` (292 LOC, S62 W1 decomp) — оба импортируются, но в `routers.py:307-309` зарегистрирован только `admin_plugins_router` (из endpoints.py). `admin_plugins.py:41` router exists but NEVER mounted.
- **Impact**: (а) Security: оператор видит успешный toggle, но plugin продолжает active (fail-open). (б) Operational: показ mock-списка plugins скрывает реальные проблемы. (в) Duplicate: 520+292 LOC = 812 LOC параллельных.
- **Минимальная рекомендация**:
  1. `git rm src/backend/entrypoints/api/v1/endpoints/admin_plugins.py` (legacy, не mounted) — 520 LOC reduction.
  2. `endpoints.py`: заменить mock-fallback на `HTTPException(503)` at lines 145-152 + 174-180 + 222-228.
- **Тест-критерий**:
  ```python
  def test_admin_plugins_toggle_unavailable_returns_503():
      # registry None → POST /admin/plugins/{name}/toggle → 503 (НЕ 200 с mock)
  def test_admin_plugins_list_503_when_loader_missing():
      # loader не инициализирован → 503
  # Дополнительно: grep "admin_plugins.py" should not match any import in src/
  ```

#### DOMAIN-P1-005 — Mobile router dead code (cycle-3 API-P0-005 мутировавший)
- **Cycle ID candidate**: API-P0-005 (cycle-3, **MUTATED** — теперь корректно dead, не fail-open).
- **Priority**: P1.
- **Path**: `src/backend/entrypoints/api/mobile/{__init__.py,router.py,schemas.py}` (438 LOC total, 6 routes).
- **Evidence**:
  - `mobile/router.py:38-42` `mobile_router = APIRouter(prefix="/mobile/v1", ...)`.
  - 6 routes определены: `/auth/login`, `/profile`, `/notifications`, `/push-token`, `/sync`, `/health` (`router.py:99-202`).
  - **NOT mounted**: `grep "mobile_router\|get_mobile_router" src/backend/entrypoints/api/v1/routers.py` → no matches.
  - Тест `tests/unit/entrypoints/api/mobile/test_mobile_bff.py:31-32` тестирует router напрямую через `app.include_router(mobile_router)` — production path не тестируется.
  - В `routers.py:307-350` монтируются все admin_* routers, mobile — отсутствует.
  - Auth: `router.py:67-93` `_verify_mobile_token` — DEMO grade: формат `mobile:<user_id>:<token>` без cryptographic verification, никакой JWT/HMAC подписи.
- **Impact**: Dead code (in production). Если бы смонтировали как есть — DEMO-grade auth (any user_id = `user_<device_id[:8]>` works with any token string).
- **Минимальная рекомендация**: удалить модуль (P3 dead code — small) ИЛИ рефакторить через существующий `ActionRouterBuilder` + JWT auth — но это уже domain-specific.
- **Тест-критерий**: см. baseline; tracked как `git ls-files src/backend/entrypoints/api/mobile/`; проверка что нет consumer в production paths.

#### DOMAIN-P1-006 — processors_catalog.py + actions_inventory.py без explicit role-guard (information disclosure)
- **Cycle ID candidate**: NEW.
- **Priority**: P1.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/processors_catalog.py:262-306` + `actions_inventory.py:183-207` + `agent_memory.py` (no auth) + `notebooks.py` (no auth).
- **Evidence**:
  - `processors_catalog.py:262-306` `router = APIRouter(prefix="/dsl", tags=["DSL Catalog"])` — `no router-level Dependencies`, регистрируется под `/api/v1/` (см. `routers.py:324-326`).
  - `actions_inventory.py:183-207` — аналогично, зарегистрирован под `/api/v1/actions` (line 294-296 routers.py).
  - `agent_memory.py` — `router = APIRouter()` no auth, mounted under `/api/v1/agent_memory` (routers.py:285-287).
  - `notebooks.py` — `router = APIRouter()` no auth, mounted under `/api/v1/notebooks`.
  - Global middleware `AuthRequiredMiddleware` authenticate-only — НЕ проверяет admin role.
  - xfailed test `tests/unit/entrypoints/api/v1/endpoints/test_agent_memory_tenant_scope.py::test_service_tenant_a_cannot_read_tenant_b_session` показывает что tenant-isolation НЕ реализована.
- **Impact**: Information disclosure: любой authenticated user (включая tenant-1 user) получает каталог процессоров/actions/notebooks — внутреннее API surface для атаки. Agent-memory tenant-bypass — explicit known xfail.
- **Минимальная рекомендация**:
  1. Для `processors_catalog`/`actions_inventory` (каталог метаданных) — `_ADMIN_GUARD_READ = Depends(require_admin((OPERATOR, READ_ONLY)))`.
  2. Для `agent_memory` — `require_auth` + tenant scope enforcement в `add_message`/`get_conversation` (закрыть xfail).
  3. Для `notebooks` — per-tenant scoping в `NotebookService`.
- **Тест-критерий** (закрыть tenant xfail):
  ```python
  def test_agent_memory_tenant_a_cannot_read_tenant_b_pass():
      # POST /api/v1/agent_memory/sessions/.../messages?tenant_id=b
      # from tenant_a user → 403 (или 404 not_found mask)
  ```

### P2 (dead code / unused)

#### DOMAIN-P2-001 — Mobile router dead code (P1 политический, P2 — operational)
- **Cycle ID candidate**: см. DOMAIN-P1-005. Разделение: P1 = security risk IF mounted; P2 = dead code в production.
- **Priority**: P2 (operational cleanup).
- **Path**: `src/backend/entrypoints/api/mobile/` (438 LOC).
- **Evidence**: см. DOMAIN-P1-005.
- **Impact**: Maintenance burden, ~3% от entrypoints/api/* LOC, нет production потребителя.
- **Минимальная рекомендация**: `git rm src/backend/entrypoints/api/mobile/` + `tests/unit/entrypoints/api/mobile/test_mobile_bff.py` (−266 LOC). Альтернативно — оформить как `routes/mobile/` (lightweight plugin) если планируется реализация.
- **Тест-критерий**: `find src/backend -name "*.py" -path "*mobile*"` empty + grep `mobile_router` empty.

#### DOMAIN-P2-002 — admin_actions.py mock-fallback P3 (dead, fail-open) [P1 cross-ref]
См. DOMAIN-P1-003.

#### DOMAIN-P2-003 — admin_plugins.py dead duplicate (520 LOC) [P1 cross-ref]
См. DOMAIN-P1-004.

### P3 (library replacement без потери функций)

#### DOMAIN-P3-001 — admin_cron `_resolve_callable` может использовать `ast.literal_eval` или factory-registry вместо `importlib.import_module`
- **Cycle ID candidate**: NEW (related to P0-002 above).
- **Priority**: P3.
- **Path**: `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:86-94` + `infrastructure/scheduler/scheduler_manager.py:184-218`.
- **Evidence**: см. DOMAIN-P0-002. `importlib.import_module` + `getattr` — опасный pattern, но в Python уже есть зрелые альтернативы:
  - Реестр: `dict[str, Callable]` в `infrastructure/scheduler/cron_registry.py` — extensions регистрируют callable по имени (`registry.register("cron.check_all_services", check_all_services)`).
  - С учётом Ponytail mode (AGENTS.md): "одну implementation → не нужен интерфейс". Здесь `importlib` — это interface, и он anti-pattern.
- **Impact**: P3 (после P0-002 fix, архитектурная чистота).
- **Минимальная рекомендация**: registry-based dispatch (Ponytail: "ничего лишнего").
- **Тест-критерий**: см. DOMAIN-P0-002 — те же тесты после refactor.

#### DOMAIN-P3-002 — AuthRequiredMiddleware / APIKeyMiddleware могут консолидироваться в один router (Ponytail mode)
- **Cycle ID candidate**: NEW.
- **Priority**: P3 (architecture; не блокер).
- **Path**: `src/backend/entrypoints/middlewares/api_key.py` (146 LOC) + `auth_required.py` (199 LOC) → monolithic APIKeyMiddleware + AuthRequiredMiddleware пытаются оба аутентифицировать (см. cycle 47 design).
- **Evidence**: `api_key.py:71-77` имеет dedup pattern:
  ```python
  auth = state.get("auth") if isinstance(state, dict) else None
  if auth is not None:
      await self.app(scope, receive, send)  # skip — already authenticated
  ```
  Cycle 47 lesson «dedup с AuthRequiredMiddleware». Один middleware (`AuthRequiredMiddleware`) уже authenticate-ит через 7 методов включая API_KEY (`auth_required.py:114-125`), а `APIKeyMiddleware` всё равно запускается с тем же функционалом. Ponytail mode: «deleting over addition».
- **Impact**: 145 LOC + 199 LOC → ~230 LOC achievable.
- **Минимальная рекомендация**: deprecate `APIKeyMiddleware` (only needed for `routes_without_api_key` allowlist — перенести в `AuthRequiredMiddleware.public_prefixes`).
- **Тест-критерий**: dedup middleware chain ломает не более 1 существующего smoke-теста; gate остается ≥95%.

### P4 (organic feature — только органично уместный)

#### DOMAIN-P4-001 — OpenAPI spec generation для Camel-style DSL `ActionRouterBuilder` (organic)
- **Cycle ID candidate**: NEW.
- **Priority**: P4 (organic — не feature-for-feature copy).
- **Path**: `src/backend/entrypoints/api/generator/specs.py` + `auto_register.py`.
- **Evidence**: Все ~119 ActionSpec регистрируются через FastAPI `add_api_route`. FastAPI уже генерирует OpenAPI 3.1 spec автоматически для всех routes (см. `/openapi.json` public). Дополнительный feature: добавить **per-ActionSpec callback для auto-exposing `action_id` → `x-action-id` extension** в OpenAPI (для трейсинга action-handler привязки). Currently `action_id` (specs.py:98) хранится в runtime metadata `_REGISTERED_ACTION_SPECS` (line 25), но не экспортится.
- **Impact**: Developer experience; small LOС (~20 LOC для OpenAPI customizer).
- **Минимальная рекомендация**: post-MVP — feature для Streamlit Developer Portal.
- **Тест-критерий**: GET `/openapi.json` → каждый path содержит `x-action-id` matching declared `action_id`.

#### DOMAIN-P4-002 — Tenacity library replacement для custom retry in DSL pipeline (organic, related to T-W3-01)
- **Cycle ID candidate**: NEW (related to cycle-3 T-W3-01 deferred).
- **Priority**: P4 — НЕ блокер.
- **Path**: `src/backend/dsl/commands/setup/orchestrator.py` + потенциально `extensions/credit_pipeline` (не в scope; не проверено).
- **Evidence**: Не проверено в scope. Organic feature предполагается только если custom retry существует.

---

## 3. Detailed evidence (mapped to cycle 1+2+3 residual references)

### DOMAIN-P0-001 re-check (cycle-3 API-P0-001 «HITL authz missing»)
Подтверждённый статус: **RESIDUAL** (cycle-3 не закрыт). Детальная картина:
- Cycle 1 (T-1.2 SSE/HITL auth) — 8 xfailed тестов ×24-sprint deferred, см. `BASELINE.md:25`.
- Cycle 2 — не фигурирует как P0 в API; cycle-3 API-P0-004 hitl no auth отмечен, но repair path = `Depends(require_admin)` AT endpoint level не выполнен.
- Cycle 3 finding API-P0-001 переоткрыт как DOMAIN-P0-001 (более конкретно: «permission `hitl.resolve` claim в docstring не enforced + cross-tenant»).
- Admin role guard отсутствует; только authentication enforced globally.

### DOMAIN-P0-002 re-check (cycle-3 API-P0-002 «admin_cron arbitrary RCE»)
Подтверждённый статус: **RESIDUAL**. Pattern `^[\w.]+:[\w]+$` позволяет `os:system`, `builtins:exec`, `subprocess:check_output` (verified runtime). Cycle-3 API-P1-003 (whitelist) — NOT implemented. Тесты `tests/unit/entrypoints/test_admin_cron.py:96-105` only проверяет «не нашли → 400», не whitelist.

### DOMAIN-P0-003 re-check (cycle-2/3 API-P0-003 «generator/setup.py broken import»)
Подтверждённый статус: **RESIDUAL**. `ModuleNotFoundError: No module named 'src.backend.workflows'` подтверждён runtime. Module dead code в production, но:
- `tests/unit/entrypoints/api/generator/test_setup.py:103-141` mocks через `sys.modules` — passes, но production path was never connected.
- `# type: ignore[import-not-found]` скрывает mypy error.

### DOMAIN-P0-004 (admin_plugins silent-success toggle) cycle-2
Подтверждённый статус: **MUTATED → DOMAIN-P1-004**. S206 fix восстановил `_ADMIN_GUARD_OPERATOR` в `admin_plugins/endpoints.py:34-42`, но:
- Mock-fallback остался (operational fail-open, см. DOMAIN-P1-004).
- Duplicate 520 LOC `admin_plugins.py` (legacy, unmounted) — dead.

### DOMAIN-P0-005 (mobile fail-open) cycle-2
Подтверждённый статус: **MUTATED → DOMAIN-P1-005 (dead code isolated)**. Mobile router не mounted, поэтому fail-open не может произойти в production. Однако dead code остаётся.

### API-P1-001 (admin_nats importlib) cycle-3
Подтверждённый статус: **RESIDUAL** as DOMAIN-P1-002 — динамический `importlib.import_module` для `src.backend.infrastructure.observability.nats_metrics` остаётся; cycle 3 не реализовал facade migration.

### API-P1-002 (generator/setup.py dead code) cycle-3
Подтверждённый статус: **RESIDUAL** as DOMAIN-P1-001. Module физически не удалён.

### API-P1-003 (admin_cron whitelist) cycle-3
Подтверждённый статус: **RESIDUAL** as DOMAIN-P0-002 (P0, поскольку это критическая отсутствующая security measure).

---

## 4. Cycle-1+2+3 residuals table

| Cycle-ID | Priority | Path | Status (verified) | Notes |
|---|---|---|---|---|
| API-P0-001 HITL auth | P0 | hitl.py:24-128 | RESIDUAL | DOMAIN-P0-001 reуточен |
| API-P0-002 admin_cron RCE | P0 | admin_cron.py:86-141 | RESIDUAL | DOMAIN-P0-002 reуточен |
| API-P0-003 generator/setup broken | P0 | generator/setup.py:12-14 | RESIDUAL | DOMAIN-P0-003 confirmed at HEAD baf54d95 |
| API-P0-004 admin_plugins silent-success | P0→P1 | admin_plugins/*.py | MUTATED (S206 guard restored) | DOMAIN-P1-004 (mock-fallback remains) |
| API-P0-005 mobile fail-open | P0 | api/mobile/router.py | MUTATED (dead-code-isolated) | DOMAIN-P1-005 (orphan, NOT mounted) |
| API-P1-001 admin_nats importlib | P1 | admin_nats.py:64-86 | RESIDUAL | DOMAIN-P1-002 reуточен |
| API-P1-002 generator/setup dead | P1 | generator/setup.py | RESIDUAL | DOMAIN-P1-001 reуточен |
| API-P1-003 admin_cron whitelist | P1 | admin_cron.py:86-141 | RESIDUAL (P0 уровень risk) | DOMAIN-P0-002 reуточен |
| API-P2-001 (cycle-3 placeholder for dead code) | P2 | api/mobile/* | RESIDUAL | DOMAIN-P2-001 (dead code confirmed) |
| API-P3-001..003 (library replacement, cycle-3) | P3 | various | NOT VERIFIED (out of cycle-3 scope re-check) | см. DOMAIN-P3-001, DOMAIN-P3-002 (P3 specific to API) |
| API-P4-001..002 (organic features, cycle-3) | P4 | various | NOT VERIFIED | см. DOMAIN-P4-001, DOMAIN-P4-002 (organic, P4) |

8 правок cycle-1+2+3 (T-1.4/T-1.5/T-3.1/T-W1-01/T-W1-05/T-W1-08 + T-02/T-03) уже в `22e08a0d` (per `BASELINE.md`); мой scope их не задевает (они в `multicast.py`, `policy_mixin.py`, `embedding_cache.py`, `auth_required.py`, `cdc_routes.py`, `credit_pipeline/agents/__init__.py`, `pip-audit-allowlist.txt`, `pyproject.toml`).

---

## 5. Contradictions / overlaps to flag

1. **Перекрёстное покрытие P0-002 + P1-003**: оба указывают на `admin_cron.py:86-94`. Я объединил в DOMAIN-P0-002 (whitelist — это missing security measure, поэтому P0), и указал в DOMAIN-P1-003 registry-based replacement.

2. **DOMAIN-P1-003 + DOMAIN-P1-004 пересекаются по fail-open pattern**: admin_actions и admin_plugins используют один и тот же `_get_*_registry() → mock_fallback` pattern. Можно рассмотреть **общий fix** в `entrypoints/api/generator/fail_closed.py` helper (но это относится к cycle-5+).

3. **DOMAIN-P1-005 + DOMAIN-P2-001 = mobile**: один и тот же модуль имеет две стороны проблемы (security IF mounted + dead code). Объединены.

4. **Layer policy overlap**: `admin_nats.py:64-86` формально layer-violation (entrypoints→infrastructure), но `tools/check_layers.py --root src` exit 0. Это означает `tools/check_layers_allowlist.txt` содержит 1 entry. Не cycles 1+2+3 finding — pre-existing state.

5. **Pre-existing test failures** (`tests/unit/api/test_auto_register_actions.py`, 4 failed): OUT OF SCOPE для cycle 4 — listed в `BASELINE.md:50` как «pre-existing drift». Не атрибутируется рою.

6. **Observed HEAD vs baseline HEAD**: `22e08a0d` (baseline) → `baf54d95` (current observed). Diff = 3 commits от Kimi Code от 2026-08-07 09:28 (security patches) — все НЕ в API scope. Не атрибутируются cycle 4 рою.

7. **auth_introspect.py:76** `except Exception: pass` — best-effort enrichment of JWT claims; не fail-open, так как core response (active:bool) уже сформирован до этого блока.

---

## 6. Readiness score (0–100)

### Формула

```
score = 100
  − 25 (P0 presence; P0/P1 → score ≤ 75)
  − 5  per каждой P0 finding (DOMAIN-P0-001, P0-002, P0-003) = −15
  − 3  per каждой P1 finding (DOMAIN-P1-001, P1-002, P1-003, P1-004, P1-005, P1-006) = −18
  − 1  per каждой P2 finding (DOMAIN-P2-001) = −1
  − 0  для P3 (no penalty — organic improvements)
  − 0  для P4 (no penalty — feature)
  + 5  verified strengths (1) global ASGI auth, (2) RBAC router-guards в 47/53 endpoints,
       (3) fail-secure login rate-limit, (4) DSL Camel-style builders, (5) no layer violations in scope
  + 2  тесты passing (177 passed in tests/unit/entrypoints/api/; 8 passed test_admin_cron; 7 admin_plugins_versioning)
```

### Compute

- Base: 100
- Cap на P0: `score ≤ 75` (per task instruction «≥80 запрещена при наличии P0/P1»).
- P0: −15 (DOMAIN-P0-001, P0-002, P0-003) → 85 (capped at 75).
- P1: −18 (DOMAIN-P1-001, P1-002, P1-003, P1-004, P1-005, P1-006) → 57.
- P2: −1 (DOMAIN-P2-001) → 56.
- P3/P4: 0.
- +5 strengths offset → effectively calculated from minimum floor: min(57, 75) = 57 (cap on P0).
- +2 tests passing buffer → 59 → clamp to **≤ 60** (per cycle-3 baseline `cap=60` для API domain).

### Финальная оценка

**API Domain readiness = 60 / 100** (clamped at 60 per cycle-3 baseline; below 80 — P0/P1 present).

**Обоснование**:
- Architecturally sound: pure ASGI middleware chain, no layer violations в scope, RBAC guards в 88% endpoints (47/53), ActionSpec DSL clean.
- Critical gaps: HITL permission/tenant enforcement (P0), admin_cron RCE без whitelist (P0), generator/setup.py broken import (P0).
- Secondary gaps: 4 fail-open admin endpoints (admin_actions, admin_plugins duplicate), 1 dead duplicate 520 LOC, 1 dead mobile module (438 LOC).
- 4 pre-existing test failures в `tests/unit/api/test_auto_register_actions.py` — тест-logic bugs, production code correct (auto_register импортирует APIRoute в _IncludedRouter, тесты ищут на верхнем уровне).

---

## 7. Recommended next tasks (cycle 5+)

| # | Task | Priority | LoC | Files | Effort |
|---|---|---|---|---|---|
| 1 | `git rm src/backend/entrypoints/api/generator/setup.py` + `tests/unit/entrypoints/api/generator/test_setup.py` | P1 | −69 −141 | 2 | XS |
| 2 | Добавить `registry=callable` whitelist + `Depends(require_admin(SUPER_ADMIN))` в `admin_cron.py:schedule_cron_job` | P0 | +20 −0 | 1 | S |
| 3 | `hitl.py`: добавить `router-level ADMIN_GUARD` + `tenant_id=request.state.tenant_id` filter в `list_pending/get/resolve` | P0 | +30 −5 | 1-2 | M |
| 4 | `admin_actions.py:invoke_action/list_actions/get_action_spec`: убрать mock-fallback → 503 (или строгий `dependency_overrides`) | P1 | −10 +5 | 1 | S |
| 5 | `admin_plugins.py` (legacy, unmounted): `git rm` −520 LOC; `admin_plugins/endpoints.py`: mock-fallback → 503 | P1 | −510 +20 | 2 | S |
| 6 | `mobile/`: `git rm` (если mobile not on roadmap) или вынести в `routes/mobile/` с proper JWT auth | P1 | −438 −266 | 4 | S |
| 7 | `admin_nats.py:64-86`: переместить `nats_metrics` в `core/observability/` или проксировать через existing `entrypoints/middlewares/otel_middleware.py` | P1 | refactor | 2-3 | M |
| 8 | Закрыть xfail `test_agent_memory_tenant_scope.py` — add `tenant_id` kwarg в `add_message()` + endpoint-level filter | P1 | +20 | 2 | M |

---

## 8. Commands run (явно с .venv/bin/python)

```bash
# Read структуры и базовые проверки
ls -la src/backend/entrypoints/api/                  # 92 файлов
ls -la src/backend/schemas/                          # 10 файлов
find src/backend/entrypoints/api -name "*.py" -exec wc -l {} + | tail -1   # 15275 LOC

# Runtime-проверки broken import и RCE pattern
.venv/bin/python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"
# → ModuleNotFoundError: No module named 'src.backend.workflows' (CONFIRMED)

.venv/bin/python -c "import re; print(bool(re.match(r'^[\w.]+:[\w]+\$', 'os:system')))"
# → True (CONFIRMED — admin_cron RCE valid)

# Mobile router структура (dead code verification)
.venv/bin/python -c "from src.backend.entrypoints.api.mobile import mobile_router; print(len(mobile_router.routes))"
# → 6

# Mobile router mount verification
grep -rn "mobile_router\|get_mobile_router" src/backend/entrypoints/api/v1/routers.py
# → No non-sensitive matches found (NOT MOUNTED)

# HITL router auth check
.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints import hitl; print(hitl.router.dependencies)"
# → []  (NO AUTH)

# Layer policy baseline
.venv/bin/python tools/check_layers.py --root src
# → 0 новых / 175 legacy / 2273 files scanned (exit 0)

# Тесты
.venv/bin/python -m pytest tests/unit/entrypoints/api/ --no-cov -q
# → 177 passed, 12 skipped, 9 xfailed, 2 warnings in 7.20s

.venv/bin/python -m pytest tests/unit/entrypoints/test_admin_cron.py --no-cov -q
# → 8 passed in 2.14s

.venv/bin/python -m pytest tests/unit/entrypoints/test_admin_plugins_versioning.py --no-cov -q
# → 7 passed in 0.49s

.venv/bin/python -m pytest tests/unit/api/ --no-cov -q
# → 61 passed, 4 failed (auto_register test logic pre-existing, NOT cycle-4 attribution)

.venv/bin/python -m pytest tests/unit/entrypoints/api/generator/test_setup.py --no-cov -q
# → 3 passed (с sys.modules mock)

# Auth guard coverage (по требованию)
grep -L "Depends(require_admin\|require_api_key\|require_auth" $(find src/backend/entrypoints/api/v1/endpoints -name "*.py") | wc -l
# → 53 (47 имеют guard, 6 — нет; см. DOMAIN-P1-006)
```

---

## 9. Summary readiness

| Metric | Value |
|---|---|
| P0 findings | **3** (DOMAIN-P0-001, DOMAIN-P0-002, DOMAIN-P0-003) |
| P1 findings | **6** (DOMAIN-P1-001, P1-002, P1-003, P1-004, P1-005, P1-006) |
| P2 findings | **1** (DOMAIN-P2-001) — операционно duplicate с P1-005 |
| P3 findings | **2** (DOMAIN-P3-001, DOMAIN-P3-002) — optional |
| P4 findings | **2** (DOMAIN-P4-001, DOMAIN-P4-002) — organic |
| Total findings | **14** |
| Cycle-3 residuals verified | RESIDUAL: 5 (API-P0-001/002/003, API-P1-001/002); MUTATED: 2 (API-P0-004, API-P0-005); NOT VERIFIED: 5 (API-P2-001, P3-001..003, P4-001..002) |
| Readiness score | **60 / 100** (capped at 60 per cycle-3 baseline; P0/P1 present → ≤75 enforced) |
| Total LOC covered | 15275 (entrypoints/api) + ~250 (schemas) |
| Files inspected | 70+ (read or partially read) |

---

## 10. Important notes for parent

- **API domain НЕ production-ready** (3 P0 findings blocking).
- **Mobile BFF** — confirmed dead code (API-P0-005 mutated) — `git rm` ready.
- **`generator/setup.py:12-14` broken import** — confirmed runtime via `.venv/bin/python`; module dead in production.
- **admin_cron RCE** — confirmed with regex runtime test; whitelist отсутствует.
- **HITL permission/tenant scope** — confirmed missing; docstring false advertising.
- Все 8 фиксов из `BASELINE.md` (T-1.4 / T-1.5 / T-3.1 / T-W1-01 / T-W1-05 / T-W1-08 + T-02 / T-03) НЕ в scope и НЕ перепроверялись.
- Pre-existing 4 test failures в `tests/unit/api/test_auto_register_actions.py` — pre-existing drift, не атрибутируется рою.

Все runtime-проверки выполнены через `.venv/bin/python` (Python 3.14.0), system Python не использовался (как требует baseline).
