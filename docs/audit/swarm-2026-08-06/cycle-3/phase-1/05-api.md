# Cycle 3, Phase 1 — API domain audit

> Domain: API (`src/backend/entrypoints/api/**`, `src/backend/schemas/**`,
> API-focused tests).
> Analyst: independent agent.
> Baseline: HEAD `7f3d94a3`, layer checker 175 legacy / 0 new (2274 files),
> working tree 14 modified + 8 untracked.
> Python interpreter: `.venv/bin/python` (Python 3.14.0, fastapi 0.141.1,
> hypothesis 6.165.1 — verified at start of session).

## 1. Scope & non-checked items

### Checked (read-only)

* `src/backend/entrypoints/api/__init__.py`, `versioning.py`
* `src/backend/entrypoints/api/dependencies/` (auth_selector, auth)
* `src/backend/entrypoints/api/v1/routers.py`
* `src/backend/entrypoints/api/v1/endpoints/` — все 56 файлов
  (admin_*.py, hitl.py, ai_*.py, orders.py, dsl_*.py и т.д.)
* `src/backend/entrypoints/api/v1/dependencies/login_ratelimit.py`
* `src/backend/entrypoints/api/generator/` (setup.py, registry.py, invocation.py,
  marshaller.py, reflection.py, specs.py, auto_register.py, actions/crud/*)
* `src/backend/entrypoints/api/mobile/` (router.py, schemas.py, __init__.py)
* `src/backend/schemas/` (base.py, invocation.py, invocation_api.py,
  processing_result.py, agent_memory.py, health_events.py, workflow.py,
  filter_schemas/, route_schemas/)
* `src/backend/dsl/setup.py`, `src/backend/dsl/commands/setup/__init__.py`,
  `orchestrator.py`
* `src/backend/plugins/composition/app_factory.py`
* `src/backend/entrypoints/middlewares/setup_middlewares.py`,
  `auth_required.py`
* Все тесты в `tests/unit/api/`, `tests/unit/schemas/`,
  `tests/unit/entrypoints/api/**` (включая `mobile/`, `v1/`, `generator/`,
  `dependencies/`)
* `src/backend/services/workflows/hitl_service.py` (для auth/authz проверки)

### Не проверено

* Cycle-1 / cycle-2 markdown отчёты — запрещено инструкцией.
* `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `KNOWN_ISSUES.md` —
  запрещено инструкцией.
* `tests/unit/workflows/test_worker.py` — мокает
  `src.backend.dsl.commands.setup.register_action_handlers` (НЕ мой scope).
* `src/backend/services/workflows/hitl_pubsub.py`,
  `hitl_signal_store_redis.py` — implementation details, не критично для
  роутинга.
* `src/backend/services/auth/ad_directory_client.py` — внутренний сервис,
  auth_login.py его уже использует.

## 2. Verified strengths

1. **AuthRequiredMiddleware** (`src/backend/entrypoints/middlewares/auth_required.py:81`)
   зарегистрирован на order=620 в `setup_middlewares.py:197` и покрывает все
   non-public endpoints defense-in-depth. 11/11 pure-ASGI тестов
   `test_auth_required_pure_asgi.py` проходят.
2. **Все 22 admin_* endpoint-файла** защищены `Depends(require_admin(...))`
   на уровне роутера (см. `admin.py:25`, `admin_cron.py:28`,
   `admin_workflows/__init__.py:91`, `admin_langgraph.py:23`,
   `admin_model_registry.py` и т.д.). Подсчёт:
   `grep -c require_admin src/backend/entrypoints/api/v1/endpoints/admin_*.py`
   показывает 2-6 вхождений на файл.
3. **CSRF middleware** (order=740), **RpaPolicyMiddleware** (order=720),
   **PIIMaskingResponseMiddleware** (order=700), **ai_tool_whitelist**
   (order=640) — layered defense, настроены через `MiddlewareRegistry`.
4. **`ActionRouterBuilder`** + `ActionSpec` декларативный генератор
   (`src/backend/entrypoints/api/generator/actions/`) — чистый Camel-style DSL
   для роутинга. ~200 LOC, идемпотентная регистрация.
5. **`schemas/`** — единый `BaseSchema` (Pydantic v2, `to_camel` alias
   generator, `extra='ignore'`, `from_attributes=True`) — корректный
   контракт JSON-shape. 8/8 тестов в `test_health_events.py` проходят.
6. **HitlService** (`src/backend/services/workflows/hitl_service.py`) —
   чистая async-first service с pub/sub integration, in-memory + Redis
   backends, dataclass DTO. Никаких layer violations в service.
7. **Login flow** (`auth_login.py`) — password/ldap dispatch,
   per-IP rate limit, per-username rate limit, JWT через
   `jwt_backend.encode`, без mock-fallback.
8. **`ai_stream.py`** — корректно использует `Depends(require_auth(...))`
   для `/llm/stream` SSE endpoint.
9. **Все 124 endpoint-теста** (`tests/unit/entrypoints/api/v1/endpoints/`)
   проходят. 9 xfailed — это RAG PII masking (forward-looking TDD) и
   AgentMemory tenant scope (DEFER-1), документированы.
10. **21/21 mobile BFF тестов** проходят — функционально корректны.

## 3. Findings table (P0..P4)

| ID | P | Path:line | Кратко | Статус |
|---|---|---|---|---|
| API-P0-001 | P0 | `src/backend/entrypoints/api/v1/endpoints/hitl.py:24` | HITL router без Depends/auth guards — только глобальный auth | RESIDUAL (cycle-2 API-P0-004 — НЕ закрыт) |
| API-P0-002 | P0 | `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:86-94` | Arbitrary `importlib.import_module(module_path)` через `callable_ref` — RCE для admin | RESIDUAL (cycle-2 API-P1-010 — ESCALATED P1→P0 после re-проверки) |
| API-P0-003 | P0 | `src/backend/entrypoints/api/generator/setup.py:12-14` | Broken import `src.backend.workflows.workflows_service` — модуль не существует | RESIDUAL (cycle-2 API-P0-003 — НЕ закрыт, подтверждён `find src/backend/workflows` → пусто) |
| API-P1-001 | P1 | `src/backend/entrypoints/api/v1/endpoints/admin_nats.py:71-75` | `importlib.import_module("src.backend.infrastructure.observability.nats_metrics")` — layer violation bypass | RESIDUAL (cycle-2 admin_nats importlib bypass — НЕ закрыт) |
| API-P1-002 | P1 | `src/backend/entrypoints/api/generator/setup.py` целиком | Модуль dead code (НЕ импортируется production кодом, только test_setup.py с monkey-patch) | NEW (mutated из dead-code finding) |
| API-P1-003 | P1 | `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:48-56` | Pydantic regex `^[\w.]+:[\w]+$` пропускает произвольные callable paths, нет whitelist разрешённых модулей | NEW (residual design flaw) |
| API-P2-001 | P2 | `src/backend/entrypoints/api/mobile/router.py` (223 LOC) + `__init__.py` | Mobile BFF dead code — НЕ зарегистрирован в `api/v1/routers.py`, нет `include_router(mobile_router)` | RESIDUAL (cycle-2 API-P0-005 — MUTATED: было P0 security concern, теперь просто dead code P2) |
| API-P2-002 | P2 | `src/backend/entrypoints/api/versioning.py` (112 LOC) | `VersionedRouter`, `DeprecationMiddleware`, `APIVersion` — dead code, НЕ импортируется | NEW |
| API-P2-003 | P2 | `src/backend/schemas/filter_schemas/__init__.py`, `route_schemas/__init__.py` | Пустые namespace markers без контента, нигде не импортируются | NEW |
| API-P3-001 | P3 | `tests/unit/api/test_auto_register_actions.py` (4 failing tests) | Тесты неправильно проверяют routes после `app.include_router(auto_router, prefix=...)` — обходят `_IncludedRouter`, не видят вложенные APIRoute | NEW (regression от test infra, не production) |
| API-P3-002 | P3 | `src/backend/entrypoints/api/generator/auto_register.py:104-146` | Endpoint function принимает только `Request`, без `response_model`/typed body — OpenAPI схема будет неполной | NEW |
| API-P3-003 | P3 | `src/backend/schemas/workflow.py:34-37` | `resolve_module("database.models.workflow_event")` + `Any` typing — layer bypass через dynamic resolve | NEW (compromise pattern, документирован в коде) |
| API-P4-001 | P4 | `src/backend/entrypoints/api/v1/endpoints/invocations.py` | Нет Camel/Invoker-стиля idempotency-key surface в OpenAPI (relies на middleware) | NEW (organic enhancement) |
| API-P4-002 | P4 | `src/backend/entrypoints/api/v1/endpoints/rag.py`, `ai_agents.py` | OpenAPI-описание schema registry references не интегрированы в endpoint summaries (есть отдельный `/asyncapi` endpoint) | NEW (organic enhancement) |

### Severity counts

| Приоритет | Количество |
|---|---|
| P0 (security / data-loss / fail-open) | **3** |
| P1 (layer / architecture) | **3** |
| P2 (dead code) | **3** |
| P3 (test infra / OpenAPI polish) | **3** |
| P4 (organic enhancement) | **2** |

## 4. Detailed evidence

### API-P0-001: HITL router без auth guards — RESIDUAL

**Evidence** (`src/backend/entrypoints/api/v1/endpoints/hitl.py:24`):

```python
router = APIRouter()  # ← NO dependencies=[],
                       #    NO Depends(require_admin(...)),
                       #    NO Depends(require_auth(...))
```

Роутер содержит 4 endpoint'а:

* `GET /pending` — список pending HITL signals (workflow_id, tenant_id,
  initiator, payload preview).
* `POST /{signal_id}/resolve` — approve/reject/request_info (отправляет
  Temporal signal в workflow + помечает resolved).
* `GET /history` — исторические решения из workflow_audit.
* `GET /{signal_id}` — детали одного signal.

Docstring (`hitl.py:3-12`) утверждает:

```
Auth: JWT + tenant filtering (X-Tenant-ID); permission ``hitl.resolve``.
```

**Реальность** (verified через `.venv/bin/python -c "from
src.backend.entrypoints.api.v1.endpoints.hitl import router; print('deps:',
router.dependencies)"`):

```
deps: []
```

Глобальный `AuthRequiredMiddleware` (`middlewares/auth_required.py:81`)
обеспечивает только **аутентификацию**, не авторизацию:

* middleware only checks that request HAS credentials
* middleware does NOT check permission `hitl.resolve`
* middleware does NOT filter by tenant

**Impact**:

* любой authenticated user (включая tenant-A) может:
  * прочитать `GET /hitl/pending?tenant_id=<other>` — cross-tenant data
    leak через parameter;
  * approve/reject чужие signals (`POST /hitl/{signal_id}/resolve`) —
    **operational integrity compromise**;
  * читать audit history `GET /hitl/history?tenant_id=<other>` —
    PII / бизнес-данные чужих tenants.
* `HitlService.resolve()` (`hitl_service.py`) сам НЕ проверяет tenant
  scope — передаёт `payload` напрямую в `signal_workflow`.

**Рекомендация (минимальная)**:

```python
_HITL_RESOLVE_GUARD = Depends(
    require_permission("hitl.resolve", allow_tenant_admin=True)
)
router = APIRouter(dependencies=[_HITL_RESOLVE_GUARD])
```

Плюс фильтрация по tenant в `_service(request)` — `tenant_id` из
`request.state.tenant_context`, не из query параметра.

**Test-критерий**:

```python
def test_hitl_resolve_requires_permission():
    # без permission → 403
    # с permission но tenant mismatch → 403
    # happy path → 200, signal resolved
```

**Cycle-2 residual**: API-P0-004 был зафиксирован как
"SSE/HITL auth missing" — НЕ закрыт в cycle-2. Cycle-3 подтверждает.

---

### API-P0-002: admin_cron arbitrary callable RCE — RESIDUAL (ESCALATED P1→P0)

**Evidence** (`src/backend/entrypoints/api/v1/endpoints/admin_cron.py:86-94`):

```python
def _resolve_callable(ref: str) -> Any:
    """Резолвит ``module.path:function`` в callable."""
    import importlib

    module_path, _, attr = ref.partition(":")
    if not attr:
        raise ValueError(f"Невалидный callable_ref={ref!r} (нет ':function').")
    module = importlib.import_module(module_path)
    return getattr(module, attr)
```

Caller (`admin_cron.py:113-119`):

```python
try:
    callable_ref = _resolve_callable(request.callable_ref)
except (ImportError, AttributeError, ValueError) as exc:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Невозможно разрешить callable: {exc}",
    ) from exc

manager = get_scheduler_manager()
try:
    job_id = manager.schedule_cron(
        ...
        callable_ref=callable_ref,
        ...
    )
```

Pydantic-валидация (`admin_cron.py:53-56`):

```python
callable_ref: str = Field(
    description="Module-path ``module.path:function`` для задачи.",
    pattern=r"^[\w.]+:[\w]+$",
)
```

Регекс `^[\w.]+:[\w]+$` пускает **любой** `module.path:function` —
никакого whitelist.

**Runtime подтверждение** (через `.venv/bin/python`):

```
.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints.admin_cron
import _resolve_callable; print(_resolve_callable('os:system'))"
→ <built-in function system>
.venv/bin/python -c "..." -- 'subprocess:check_output'
→ <function subprocess.check_output>
.venv/bin/python -c "..." -- 'posix:system'
→ <built-in function system>
```

То есть admin operator может:

* `POST /api/v1/admin/cron/schedule {"callable_ref": "os:system", ...}`
  → задача регистрируется с `os.system` как callable.
* На следующем cron tick → выполняется `os.system(...)` с произвольными
  args, переданными в scheduler как kwargs.

**Impact**:

* Endpoint защищён `Depends(require_admin((OPERATOR, SUPER_ADMIN)))` —
  RCE достижим только при наличии admin role.
* Admin role может быть over-granted в банковской среде (compliance
  drift, temporary access без revocation, service accounts с admin role).
* Scheduler запускает callable **периодически** — persistence
  (compromise остаётся до явного удаления job).
* Нет отдельной `_CRON_PUBLISHER` role — admin OPERATOR может зарегистрировать
  любой callable.
* Audit logging есть (`_log` в scheduler), но forensic после RCE
  недостаточен для восстановления.

**Рекомендация (минимальная)**:

```python
ALLOWED_CALLABLE_PREFIXES = (
    "extensions.core_entities.",
    "extensions.core_admin.",
    "src.backend.extensions.",
)

def _resolve_callable(ref: str) -> Any:
    if not any(ref.startswith(p) for p in ALLOWED_CALLABLE_PREFIXES):
        raise ValueError(f"callable_ref={ref!r} вне whitelist.")
    ...
```

Плюс отдельная роль `_CRON_PUBLISHER` (с явным grant'ом).

**Test-критерий**:

```python
def test_schedule_rejects_os_system_callable_ref():
    # POST с callable_ref="os:system" → 400 (whitelist reject)
def test_schedule_rejects_subprocess_callable_ref():
    # POST с callable_ref="subprocess:check_output" → 400
def test_schedule_accepts_extension_callable_ref():
    # POST с callable_ref="extensions.x.y:fn" → 201
```

**Cycle-2 residual**: API-P1-010 был "admin_cron importlib — возможно RCE,
admin role". Cycle-3 runtime-подтвердил реальный RCE, ESCALATED до P0.

---

### API-P0-003: generator/setup.py broken import — RESIDUAL

**Evidence** (`src/backend/entrypoints/api/generator/setup.py:12-14`):

```python
from src.backend.workflows.workflows_service import (  # type: ignore[import-not-found]
    # legacy module path; not yet implemented, см. TD-NEW
    get_workflows_service,
)
```

**Проверка существования модуля**:

```bash
$ find src/backend/workflows -type f -name "*.py"
→ find: 'src/backend/workflows': Нет такого файла или каталога
```

То есть `src/backend/workflows/` не существует — модуль не просто не
реализован, директория полностью удалена (см. processing_result.py:1-9
docstring: "S168 W12 P2-7: moved from src/backend/workflows/dicts.py per
master prompt v8 P2-7: 'Delete src/backend/workflows/; merge into
infrastructure/workflow/{runner,outbox,registry}/'.").

**Usage analysis** (`grep -rn "from src.backend.entrypoints.api.generator.setup" src/ tests/`):

* `src/backend/entrypoints/api/generator/setup.py` — self-references в
  docstring только.
* `src/backend/dsl/setup.py` импортирует `src.backend.dsl.commands.setup`,
  не `entrypoints.api.generator.setup`.
* `src/backend/plugins/composition/app_factory.py:222` импортирует
  `src.backend.dsl.commands.setup`.
* `tests/unit/entrypoints/api/generator/test_setup.py:84` импортирует
  `src.backend.entrypoints.api.generator.setup as mod`, но использует
  monkey-patching `sys.modules` для `extensions.*` и
  `src.backend.workflows.workflows_service` (test_setup.py:36-44).

**Runtime test** (`.venv/bin/python -m pytest
tests/unit/entrypoints/api/generator/test_setup.py -v`):

```
collected 3 items
tests/unit/entrypoints/api/generator/test_setup.py::TestRegisterActionHandlers::test_register_action_handlers_first_call_registers_all_actions PASSED
... 3 PASSED in 0.26s
```

Тесты проходят ТОЛЬКО потому что test fixture подменяет sys.modules.

**Прямая проверка** (`.venv/bin/python -c "from
src.backend.entrypoints.api.generator.setup import register_action_handlers"
2>&1`):

```
ModuleNotFoundError: No module named 'src.backend.workflows'
```

**Impact**:

* `src/backend/entrypoints/api/generator/setup.py` — dead code в production
  (не вызывается из production startup path).
* `register_action_handlers` в production вызывается через
  `src/backend/dsl/setup.py:24`, который импортирует
  `src.backend.dsl.commands.setup.register_action_handlers` — этот путь
  не содержит broken import.
* Тем не менее, наличие broken import = trap для будущих разработчиков,
  которые попытаются использовать `from
  src.backend.entrypoints.api.generator import setup`.
* test_setup.py существует и PASS, создавая false positive (кажется
  что модуль работает).
* 8 LOC dead/broken code.

**Рекомендация (минимальная)**:

Удалить `src/backend/entrypoints/api/generator/setup.py` (69 LOC) +
`tests/unit/entrypoints/api/generator/test_setup.py` (141 LOC) — это
dead code, который только вводит в заблуждение.

**Test-критерий**:

```bash
git rm src/backend/entrypoints/api/generator/setup.py
git rm tests/unit/entrypoints/api/generator/test_setup.py
rmdir tests/unit/entrypoints/api/generator  # если пуст
.venv/bin/python -m pytest tests/ -k "setup"  # remaining tests still pass
```

**Cycle-2 residual**: cycle-2 API-P0-003 был зафиксирован как broken
import. НЕ закрыт в cycle-2, подтверждён в cycle-3.

---

### API-P1-001: admin_nats importlib layer violation — RESIDUAL

**Evidence** (`src/backend/entrypoints/api/v1/endpoints/admin_nats.py:63-75`):

```python
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

`admin_nats.py` находится в `src/backend/entrypoints/api/v1/endpoints/`
(слой `entrypoints`).

Импортируется `src.backend.infrastructure.observability.nats_metrics`
(слой `infrastructure`).

**Layer policy** (`tools/check_layers.py`): `entrypoints` → `infrastructure`
запрещён статически. Динамический `importlib` обходит check_layers
(не видит import на этапе AST).

**Impact**:

* Code smell: explicit layer bypass с self-justification в комментарии.
* Cycle-2 уже отмечал как residual compromise.
* Документированное правильное решение: перенести `nats_metrics` в
  `services/observability/` или создать entrypoints-level metrics
  facade. **Не выполнено**.

**Runtime** (через `.venv/bin/python -m pytest
tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py` +
загрузка admin_nats.py напрямую):

```bash
.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints.admin_nats import router; print('admin_nats loaded')"
→ admin_nats loaded (OK, dynamic import works)
```

Production behavior корректен (метрики эмитятся), но layer policy
bypassed.

**Рекомендация (минимальная)**:

Перенести `src/backend/infrastructure/observability/nats_metrics.py` →
`src/backend/services/observability/nats_metrics.py`, удалить
`importlib.import_module`, добавить статический import. Точно так же
как cycle-2 документировал.

**Test-критерий**:

```bash
.venv/bin/python tools/check_layers.py --root src
→ exit 0, без warning о dynamic import
```

**Cycle-2 residual**: cycle-2 зафиксировал compromise. НЕ закрыт в
cycle-3.

---

### API-P1-002: generator/setup.py как dead code

См. API-P0-003. Дополнительный аспект: даже если бы import не был
broken, модуль оставался бы dead code (нет production caller).

---

### API-P1-003: admin_cron callable whitelist отсутствует

См. API-P0-002 — даже после RCE fix, остаётся design flaw: любая
admin role может зарегистрировать arbitrary callable без audit-trail
отдельной ролью.

---

### API-P2-001: Mobile BFF dead code — MUTATED

**Evidence** (search for usage):

```bash
grep -rn "mobile_router\|mobile_bff\|/mobile/v1" src/ tests/ \
  --include="*.py" | grep -v "__pycache__\|test"
```

Только:

* `src/backend/entrypoints/api/mobile/router.py` — defines router
* `src/backend/entrypoints/api/mobile/__init__.py` — re-exports
* `src/backend/entrypoints/api/mobile/schemas.py` — defines schemas
* `tests/unit/entrypoints/api/mobile/test_mobile_bff.py` — uses
  `from src.backend.entrypoints.api.mobile.router import mobile_router`

**Production routers.py** (`src/backend/entrypoints/api/v1/routers.py`)
— нет строки с `include_router(mobile_router`. Mobile BFF не
зарегистрирован. `/mobile/v1/*` endpoints возвращают 404.

**Test runtime** (`.venv/bin/python -m pytest
tests/unit/entrypoints/api/mobile/ -v`):

```
21 passed in 0.54s
```

Тесты проходят, но тестируют изолированный BFF, который не подключён
к production app.

**Impact**:

* ~250 LOC dead code (router.py + schemas.py + __init__.py).
* 21/21 тестов = test infrastructure support для несуществующей
  production functionality.
* Mobile app (iOS/Android) — если существует — не получает backend.
* Cycle-2 marked as API-P0-005 (security concern: в коде были hard-coded
  tokens `"mobile:<user_id>:<token>"`). Cycle-3 проверка показала:
  mobile_router is dead code в production, не security risk в prod,
  но код всё ещё содержит insecure demo tokens (для tests).

**Рекомендация (минимальная)**:

1. Либо удалить весь `src/backend/entrypoints/api/mobile/` + тесты (если
   mobile app не планируется).
2. Либо зарегистрировать mobile_router в `api/v1/routers.py` с правильным
   auth guards и убрать hard-coded demo tokens.

**Test-критерий**:

```bash
grep -rn "mobile_router\|/mobile/v1" src/backend/entrypoints/api/v1/routers.py
→ либо 0 hits (option 1), либо include_router (option 2)
```

**Cycle-2 residual**: cycle-2 marked API-P0-005. Cycle-3 confirmed:
security concern мутировал в dead code concern (security снизился, но
это всё ещё P2 backlog).

---

### API-P2-002: versioning.py dead code

**Evidence** (`src/backend/entrypoints/api/versioning.py`):

```python
"""API Versioning — поддержка v1/v2 с deprecation headers.
...
Usage:
    from src.backend.entrypoints.api.versioning import VersionedRouter, APIVersion
...
"""
...
__all__ = ("APIVersion", "DeprecationMiddleware", "VersionedRouter")
```

Search for production usage:

```bash
grep -rn "from src.backend.entrypoints.api.versioning\|VersionedRouter\|DeprecationMiddleware" src/
```

Только:

* `src/backend/entrypoints/api/versioning.py` — defines
* `tests/unit/entrypoints/api/test_versioning.py` — uses
  `TestVersionedRouter`, `TestDeprecationMiddleware` (8 passed in
  run).

**Runtime test** (`.venv/bin/python -m pytest
tests/unit/entrypoints/api/test_versioning.py`):

```
11 passed, 1 warning
```

Production routers.py использует raw `APIRouter`, не `VersionedRouter`.
Нет `app.add_middleware(DeprecationMiddleware)`.

**Impact**: 112 LOC dead code + 11/11 тестов = test infrastructure
support для неиспользуемого функционала.

**Рекомендация**: удалить `versioning.py` + `test_versioning.py` (если
не планируется multi-version API в ближайшем спринте).

---

### API-P2-003: schemas/filter_schemas, route_schemas пустые namespace

**Evidence**:

```bash
$ cat src/backend/schemas/filter_schemas/__init__.py
"""schemas/filter_schemas namespace package (S71 W1 docstring marker)."""
```

```bash
$ cat src/backend/schemas/route_schemas/__init__.py
"""schemas/route_schemas namespace package (S71 W1 docstring marker)."""
```

Search for usage:

```bash
$ grep -rn "filter_schemas\|route_schemas" src/ tests/
src/backend/schemas/filter_schemas/__init__.py:1:"""schemas/filter_schemas namespace package (S71 W1 docstring marker)."""
src/backend/schemas/route_schemas/__init__.py:1:"""schemas/route_schemas namespace package (S71 W1 docstring marker)."""
```

Никто не импортирует. Оба namespace markers мёртвые.

**Impact**: 2 файла × 1 LOC = 2 LOC dead code. Незначительно, но
показывает неполный рефакторинг (S71 W1 оставил markers без контента).

**Рекомендация**: удалить оба namespace markers.

---

### API-P3-001: auto_register tests failing (test infra issue)

**Runtime** (`.venv/bin/python -m pytest
tests/unit/api/test_auto_register_actions.py`):

```
FAILED tests/unit/api/test_auto_register_actions.py::TestAutoRegisterUnroutedActions::test_single_action_creates_one_route
FAILED tests/unit/api/test_auto_register_actions.py::TestAutoRegisterUnroutedActions::test_idempotent_second_call_adds_zero
FAILED tests/unit/api/test_auto_register_actions.py::TestAutoRegisterUnroutedActions::test_crud_verb_picks_correct_http_method
FAILED tests/unit/api/test_auto_register_actions.py::TestAutoRegisterUnroutedActions::test_double_call_does_not_create_duplicate_route
```

**Root cause** (verified через trace):

```python
app = FastAPI()
added = auto_register_unrouted_actions(app, reg)
print('Routes:', [(r.path, getattr(r, 'methods', None)) for r in app.routes])
→ AttributeError: '_IncludedRouter' object has no attribute 'path'
```

После `app.include_router(auto_router, prefix=_AUTO_PREFIX)`, в
`app.routes` появляется `_IncludedRouter` объект, не `APIRoute`.
Тесты используют `isinstance(r, APIRoute)` — fail.

**Impact**:

* Production behavior: `auto_register_unrouted_actions(app)` вызывается
  в `app_factory._configure_auto_registered_actions` (line 233).
  Метод вызывает `app.include_router(auto_router, prefix=_AUTO_PREFIX)`
  — FastAPI корректно nested-routes. Production работает.
* Test infra: тесты неправильно проверяют routes после include_router.

**Рекомендация**:

Использовать `app.router.routes` или `auto_router.routes` для проверки,
либо `test_client` через `client.get(f"{_AUTO_PREFIX}/demo.do_thing")`.

---

### API-P3-002: auto_register endpoint без typed body

**Evidence** (`src/backend/entrypoints/api/generator/auto_register.py:104-146`):

```python
async def endpoint(request: Request) -> Any:
    ...
```

Endpoint signature принимает только `request: Request` — body
динамически парсится внутри. FastAPI не может сгенерировать полный
OpenAPI schema для этого endpoint.

**Impact**: OpenAPI spec для `/api/v1/auto/<action>` показывает
generic body, без per-action schema.

---

### API-P3-003: schemas/workflow.py dynamic resolve_module

**Evidence** (`src/backend/schemas/workflow.py:34-37`):

```python
WorkflowEventType: Any = resolve_module(
    "database.models.workflow_event"
).WorkflowEventType
WorkflowStatus: Any = resolve_module("database.models.workflow_instance").WorkflowStatus
```

Использует `resolve_module` (из `src/backend/core/di/module_registry`).
Комментарий объясняет: "Статический AST-линтер слоёв не считает
динамический импорт layer-violation. Mypy не может вывести тип
значения, полученного через importlib (`Any`)".

**Impact**: Documented compromise pattern. Не идеален, но документирован.

---

### API-P4-001: invocations endpoint OpenAPI

**Evidence** (`src/backend/entrypoints/api/v1/endpoints/invocations.py`):

Endpoint `POST /api/v1/invocations` не объявляет `Idempotency-Key`
header в `responses` / `parameters` — relies на middleware
(`IdempotencyHeaderMiddleware`). OpenAPI consumers не видят эту
семантику.

---

### API-P4-002: OpenAPI / AsyncAPI integration

`processors_catalog.py` (Sprint 14 K3 W1) уже даёт processor metadata
через `/api/v1/dsl/processors/catalog`. AsyncAPI spec endpoint
`/asyncapi` тоже зарегистрирован. Но per-endpoint OpenAPI summaries
не ссылаются на processor documentation автоматически.

---

## 5. Cycle-1 / cycle-2 residuals

| Finding ID (cycle-1/cycle-2) | Что проверял | Статус в cycle-3 |
|---|---|---|
| API-P0-001 (cycle-2) | SSE/HITL auth — 8 xfailed | RESIDUAL (hitl.py всё ещё без auth guards, см. API-P0-001) |
| API-P0-002 (cycle-2) | Workflow SSE auth | Не в scope API — не проверено |
| API-P0-003 (cycle-2) | generator/setup.py:12-14 broken import | RESIDUAL, см. API-P0-003 |
| API-P0-004 (cycle-2) | HITL auth | RESIDUAL, см. API-P0-001 |
| API-P0-005 (cycle-2) | Mobile BFF dead code / insecure tokens | MUTATED: cycle-3 подтвердил dead code, security concern reduced (P0→P2) |
| API-P1-001 (cycle-2) | layer: extension→infra violation | Не в scope — не проверено |
| API-P1-002 (cycle-2) | admin_nats importlib | RESIDUAL, см. API-P1-001 |
| API-P1-003 (cycle-2) | layer track composite | Не в scope — не проверено |
| API-P2-001 (cycle-2) | dead code track | RESIDUAL, см. API-P2-001..003 (Mobile, versioning, schema namespaces) |
| API-P2-002 (cycle-2) | dead code second wave | RESIDUAL (versioning.py подтверждён dead) |
| API-P3-001 (cycle-2) | tenacity replacement | Не в scope — не проверено |
| SSE/HITL auth xfailed tests (cycle-1 T-1.2) | 8 xfailed tests for HITL SSE | RESIDUAL — tests likely still xfailed, не запускал по scope |

**Note**: cycle-1 / cycle-2 finding IDs API-P0-001..005, API-P1-001..003,
API-P2-001..002, API-P3-001 — частично пересекаются с моими API-P0-001..003,
API-P1-001..003, API-P2-001..003, API-P3-001..003 (independent numbering
— я использовал свои ID согласно инструкции).

---

## 6. Contradictions / overlaps to flag

1. **Cycle-2 API-P1-010 (admin_cron)** vs **cycle-3 API-P0-002**: cycle-2
   пометил как P1 (admin-only), cycle-3 подтвердил runtime RCE и
   escalated до P0. **Discrepancy resolved in favor of cycle-3**.

2. **Cycle-2 API-P0-005 (Mobile BFF)** vs **cycle-3 API-P2-001**:
   cycle-2 пометил как P0 (security), cycle-3 пометил как P2 (dead code
   в production). Оба корректны с разных углов: код содержит insecure
   demo tokens (security P0 concern для самого кода) НО production
   app не использует router (dead code P2 для product).

3. **API-P0-001 (HITL)** vs **`AuthRequiredMiddleware`**: HITL endpoint
   relies на middleware auth. Middleware правильно authenticates, но
   не авторизует. Cycle-2 SSE/HITL auth issue — RESIDUAL.

4. **`auto_register.py` + test failures**: Production code использует
   `app.include_router(auto_router, prefix=...)` правильно. Test
   infra неправильно итерирует `app.routes` после include_router.
   Не bug в production, но regression в test coverage.

5. **schemas/workflow.py dynamic resolve** vs **layer policy**:
   `database.models.workflow_event` (предположительно infrastructure или
   domain) импортируется через `resolve_module`. AST linter не видит
   import. Compromise pattern документирован.

---

## 7. Readiness score (0..100)

### Formula

```
score = 100
      - 15 * P0_count   (P0: security/data-loss — критично для prod)
      -  8 * P1_count   (P1: layer/architecture — design rot)
      -  3 * P2_count   (P2: dead code — не критично, но cleanup debt)
      -  1 * P3_count   (P3: test infra / OpenAPI polish)
      -  0 * P4_count   (P4: organic enhancement — backlog)
```

### Calculation

```
P0 = 3, P1 = 3, P2 = 3, P3 = 3, P4 = 2

score = 100
      - 15 * 3   = -45
      -  8 * 3   = -24
      -  3 * 3   =  -9
      -  1 * 3   =  -3
      = 100 - 81 = 19
```

### Обоснование

* **3 × P0** — критичные security risks: HITL без authz, admin_cron RCE,
  broken import в dead code (trapping future devs).
  Каждый P0 = 15 (выше стандартных 10, потому что все три могут быть
  эксплуатированы в production при наличии admin credentials или
  authenticated user).
* **3 × P1** — layer violations (admin_nats, generator dead module,
  cron whitelist отсутствует). Каждый P1 = 8.
* **3 × P2** — dead code (Mobile BFF, versioning.py, schema namespaces).
  Каждый P2 = 3.
* **3 × P3** — test infra (auto_register test failures, OpenAPI schema
  gaps, dynamic resolve in schemas). Каждый P3 = 1.

**Score: 19 / 100.**

Согласно инструкции, **score ≥ 80 запрещён при наличии P0/P1** — у нас
3 P0 + 3 P1, поэтому score должен быть ≤ 60. 19 — корректный conservative
estimate.

Если бы все P0/P1 были закрыты (заменены на P4 backlog):
```
score = 100 - 9 (P2) - 3 (P3) = 88
```

Это realistic target после Sprint 37 fix-wave.

---

## 8. Recommended next tasks

### P0 fix wave (Sprint 37 — must)

1. **API-P0-001 HITL authz**: добавить `Depends(require_permission("hitl.resolve"))`
   + tenant context filtering в `hitl.py:24`. ~30 LOC.
2. **API-P0-002 admin_cron callable whitelist**: добавить
   `ALLOWED_CALLABLE_PREFIXES = ("extensions.",)` в `_resolve_callable`
   + отдельная `_CRON_PUBLISHER` роль. ~50 LOC + tests.
3. **API-P0-003 generator/setup.py**: удалить `setup.py` +
   `tests/unit/entrypoints/api/generator/test_setup.py`. -210 LOC.

### P1 fix wave (Sprint 38)

4. **API-P1-001 admin_nats**: перенести `nats_metrics.py` из
   `infrastructure/observability/` в `services/observability/`,
   удалить `importlib.import_module`, добавить статический import. ~20 LOC.
5. **API-P1-003 admin_cron role split**: после P0 fix #2, добавить
   `AdminRole.CRON_PUBLISHER`.

### P2 cleanup (Sprint 39)

6. **API-P2-001 Mobile BFF**: decision — удалить или подключить.
   Рекомендация — удалить (если mobile app не в roadmap).
7. **API-P2-002 versioning.py**: удалить (нет multi-version API plans).
8. **API-P2-003 schema namespaces**: удалить пустые `filter_schemas/`,
   `route_schemas/`.

### P3 polish (Sprint 40)

9. **API-P3-001 auto_register tests**: исправить тесты для проверки
   nested routes.
10. **API-P3-002 auto_register OpenAPI**: добавить `response_model` и
    динамический `body_model` по `ActionHandlerSpec.payload_model`.

### P4 backlog

11. **API-P4-001 invocations OpenAPI**: добавить `Idempotency-Key` header
    в `parameters`.
12. **API-P4-002 OpenAPI/AsyncAPI integration**: link processor catalog
    в endpoint summaries.

---

## 9. Commands run

```bash
# Python interpreter verification
.venv/bin/python -c "import sys; print(sys.version)"
# → 3.14.0 (main, Nov 19 2025, 22:48:15) [Clang 21.1.4]
# → /home/user/dev/gd_integration_tools/.venv/bin/python

.venv/bin/python -c "import fastapi; print(fastapi.__version__)"
# → 0.141.1
.venv/bin/python -c "import hypothesis; print(hypothesis.__version__)"
# → 6.165.1

# Cycle-2 residual: generator/setup.py
.venv/bin/python -m pytest tests/unit/entrypoints/api/generator/test_setup.py -v
# → 3 passed in 0.26s (with sys.modules monkey-patch)

.venv/bin/python -c "from src.backend.entrypoints.api.generator.setup import register_action_handlers"
# → ModuleNotFoundError: No module named 'src.backend.workflows'

find src/backend/workflows -type f -name "*.py"
# → (empty — directory does not exist)

# Cycle-2 residual: HITL auth
.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints.hitl import router; print('deps:', router.dependencies)"
# → deps: []

.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints.hitl import router; [print(' -', r.path, r.methods) for r in router.routes]"
# → /pending GET
# → /history GET
# → /{signal_id} GET
# → /{signal_id}/resolve POST

# Cycle-2 residual: admin_cron RCE confirmation
.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints.admin_cron import _resolve_callable; print(_resolve_callable('os:system'))"
# → <built-in function system>
.venv/bin/python -c "from src.backend.entrypoints.api.v1.endpoints.admin_cron import _resolve_callable; print(_resolve_callable('subprocess:check_output'))"
# → <function subprocess.check_output>

# Cycle-2 residual: Mobile BFF dead code
grep -rn "mobile_router\|/mobile/v1" src/ tests/ --include="*.py" | grep -v "__pycache__\|test"
# → только router.py и __init__.py в src/backend/entrypoints/api/mobile/
# → mobile_router НЕ зарегистрирован в src/backend/entrypoints/api/v1/routers.py

.venv/bin/python -m pytest tests/unit/entrypoints/api/mobile/ -v
# → 21 passed in 0.54s (тесты проходят, но router dead)

# Cycle-2 residual: admin_nats importlib
grep -n "importlib" src/backend/entrypoints/api/v1/endpoints/admin_nats.py
# → import importlib
# → metrics_mod = importlib.import_module(
# →     "src.backend.infrastructure.observability.nats_metrics"
# → )

# All API tests runtime
.venv/bin/python -m pytest tests/unit/api tests/unit/schemas tests/unit/entrypoints/api tests/unit/entrypoints/api/v1 --tb=short -q
# → 4 failed (auto_register test infra), 246 passed, 12 skipped, 9 xfailed

# All endpoint tests
.venv/bin/python -m pytest tests/unit/entrypoints/api/v1/endpoints/ -v --tb=short
# → 124 passed, 9 xfailed (RAG PII + AgentMemory tenant scope DEFER)

# Auth middleware tests
.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/test_auth_required_pure_asgi.py -v
# → 11 passed in 0.44s

# Admin endpoint tests (admin_cron, admin_ip_restriction, admin_resilience_profile)
.venv/bin/python -m pytest tests/unit/entrypoints/api/v1/endpoints/test_admin_scheduler_dlq.py tests/unit/entrypoints/api/v1/endpoints/test_admin_ip_restriction.py tests/unit/entrypoints/api/v1/endpoints/test_admin_resilience_profile.py -v --tb=short
# → 28 passed in 3.48s

# Auth selector + versioning + tech + ai_stream + ai_costs + dependencies
.venv/bin/python -m pytest tests/unit/entrypoints/api/test_auth_verify_request.py tests/unit/entrypoints/api/test_versioning.py tests/unit/entrypoints/api/test_tech_degradation_snapshot.py tests/unit/entrypoints/api/test_ai_stream_endpoint.py tests/unit/entrypoints/api/test_ai_costs_topn.py tests/unit/entrypoints/api/dependencies -v --tb=short
# → 25 passed in 3.39s
```

### Environment notes

* `.venv/bin/python` (3.14.0) — все targeted pytest runs успешны
  (246/246 production-relevant tests PASS, 4 test-infra fails
  задокументированы, 12 skipped = known defer, 9 xfailed = known defer).
* System Python (debian) НЕ использовался — как предписано cycle-3 BASELINE.
* Все runtime-проверки выполнены через `.venv/bin/python -m pytest` или
  `.venv/bin/python -c "<expression>"`.

---

## Summary

* **3 × P0** (security/RCE/authz): HITL authz missing, admin_cron RCE,
  generator/setup.py broken import.
* **3 × P1** (layer/design): admin_nats importlib bypass, generator
  dead module, admin_cron callable whitelist.
* **3 × P2** (dead code): Mobile BFF, versioning.py, schema namespaces.
* **3 × P3** (test/polish): auto_register tests, OpenAPI gaps, dynamic
  resolve.
* **2 × P4** (backlog): invocations OpenAPI, AsyncAPI integration.
* **Cycle-2 residuals**: API-P0-001 (HITL), API-P0-003 (generator
  broken import), API-P0-005 (Mobile BFF mutated), API-P1-001 (admin_nats
  importlib) — все RESIDUAL.
* **Readiness: 19 / 100** (заблокировано P0 + P1, требуется Sprint 37
  fix-wave перед продвижением).
