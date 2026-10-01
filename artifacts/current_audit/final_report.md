# final_report.md — gd_integration_tools, повторный доказательный аудит

> **Дата:** 2026-10-01
> **Worktree:** `/home/user/dev/gd_reaudit` (отдельный, detached)
> **Исследованный HEAD:** `3b509542e96d89d79df45200d31904cd4fa97947`
> **Интерпретатор:** `/home/user/dev/gd_reaudit/.venv/bin/python` — **Python 3.14.0** (канонический)
> **Окружение:** `uv sync --frozen --all-extras` завершён успешно

---

## 0. Baseline — и почему прежние claims не перенесены

| Параметр | Значение |
|---|---|
| `git rev-parse HEAD` (primary worktree, master) | `3b509542e96d89d79df45200d31904cd4fa97947` |
| Ожидаемый исследованный commit | `2c39e4469fbdf473a027de06e123b3d34c19525f` |
| Отношение | `2c39e446` — **предок** master, master опережает на **16 коммитов** |
| `python --version` (системный) | **3.12.3** → для проекта непригоден, все измерения на 3.14.0 |
| `uv --version` | 0.11.7 (x86_64-unknown-linux-gnu) |
| Незакоммиченные изменения в primary worktree | **37 файлов** (чужые; не тронуты, не удалены) |

**Вывод по baseline.** Ожидаемый commit не является текущим HEAD, поэтому по правилу
задачи инвентаризация выполнена заново на `3b509542e`. Claims предыдущей волны
(база `a1c72378f`) не переносились. 16 коммитов, включая шесть P0-фиксов
(lifecycle MongoDB, scheduler async, saga re-entry, GraphQL guards, dedup),
уже присутствуют в master — ряд решений, ожидавших владельца, был закрыт
до начала этой волны.

**Изоляция.** Вся работа выполнена в отдельном worktree. Primary worktree
`/home/user/dev/gd_integration_tools` не изменялся.

---

## 1. ГЛАВНАЯ P0-ПРОВЕРКА: фактический порядок middleware

### 1.1 Метод

Инструментирован **каждый** из 37 middleware событиями `enter:<name>` / `exit:<name>`
на реальном `FastAPI`-приложении, собранном через production-фабрику
`src/backend/plugins/composition/app_factory.py:31`. Регистрация перехвачена
патчем `Starlette.add_middleware` **до** `create_app()`.

Артефакт: `artifacts/current_audit/middleware_actual_order.json`.

**Моя ошибка, зафиксированная честно:** первый вариант пробы обходил lifespan
через `TestClient(app)` (упал: требуется живая инфраструктура) и затем вызывал
`build_middleware_stack()` напрямую — это дало `KeyError: 'app'`, потому что
`scope["app"]` выставляет именно `Starlette.__call__`. Обе ошибки — мои, не дефекты
приложения. Второй вариант пробил обход `lifespan` и вызвал `app.__call__` напрямую.
Третья ошибка — склейка двух разных классов `PrometheusMiddleware` по `__name__`
(из-за неё первый замер дал 36 вместо 37); исправлено на `qualname`.

### 1.2 Фактический порядок (37/37, фрагмент)

Индекс 0 = **outermost**, входит в запрос **первым**.

| idx | middleware | registry order | | idx | middleware | order |
|---:|---|---:|---|---:|---|---:|
| 0 | prometheus | 840 / +вне реестра | | 19 | timeout | 400 |
| 1 | graceful_shutdown | 880 | | 20 | request_body_cache | 380 |
| 2 | security_headers | 860 | | 21 | degradation | 360 |
| 3 | otel | 820 | | 22 | idempotency | 340 |
| 4 | inner_request_logging | 800 | | 23 | tenant_resource_isolation | 330 |
| 5 | audit_replay | 780 | | 24 | request_context | 320 |
| 6 | audit_log | 760 | | 25 | **tenant** | **300** |
| 7 | csrf | 740 | | 26 | correlation_id | 280 |
| 8 | rpa_policy | 720 | | 27 | request_id | 260 |
| 9 | pii_masking_response | 700 | | 28 | circuit_breaker | 250 |
| 10 | webhook_signature | 680 | | 29 | api_key | 110 |
| 11 | ws_rate_limit | 660 | | 30 | ip_restriction | 90 |
| 12 | login_step_up | 650 | | 31 | blocked_routes | 70 |
| 13 | ai_tool_whitelist | 640 | | 32 | trusted_host | 50 |
| 14 | **auth_required** | **620** | | 33 | cors | 30 |
| 15 | auth_method_header | 600 | | 34 | global_ratelimit | 20 |
| 16 | data_masking | 580 | | 35 | exception_handler | 10 |
| 17 | gzip | 560 | | | | |
| 18 | response_cache | 520 | | | | |

Порядок ответа — **точная реверсия** порядка запроса (проверено: `exception_handler`
первым на выходе при последнем на входе).

### 1.3 Сверка четырёх представлений

| Представление | Что даёт |
|---|---|
| Порядок **регистрации** | возрастание `order` (`registry.py:264`) — 10 → 880 |
| `app.user_middleware` | **обратный**: `insert(0, …)` (`Starlette.add_middleware`), index 0 = 880 |
| Фактический **request order** | совпадает с `user_middleware` (замер, 37/37) |
| Фактический **response order** | реверсия request order |
| **Ожидаемый security order** | не совпадает — см. 1.4 |

**Механизм подтверждён:** `apply_to_app` сортирует по возрастанию `order` и вызывает
`add_middleware` последовательно, а Starlette делает `insert(0, …)` → **высокий
order = внешний**. Это прямо противоречило `registry.py:71` («низкий = наружный»),
исправлено (см. §3).

### 1.4 Цепочка безопасности: 7 из 8 стадий, порядок инвертирован

| Стадия | Ожидается до | Фактически idx | Статус |
|---|---|---:|---|
| authentication | — | 14 (`auth_required`) | ✅ раньше tenant |
| tenant resolution | после auth | **25** | ⚠️ |
| tenant resource isolation | после tenant | **23** | ❌ **раньше tenant** |
| authorization | после изоляции | — | ❌ **ОТСУТСТВУЕТ** |
| idempotency | после authz | 22 | ⚠️ |
| request body cache | до idempotency | **20** | ❌ **раньше idempotency** |
| response cache | — | 18 | ⚠️ |
| logging | — | 6 | ⚠️ outermost (норма для логирования) |

**F-A (P1) — стадия authorization отсутствует в стеке.** Ни один middleware не
выполняет object-level authorization. Корреляция: `TenantResourceIsolationMiddleware`
существует (order 330), но `register_ownership_checker` **не вызывается ни одним
production-сайтом** — 0 совпадений в `src/`, `extensions/`, `routes/`
(только определение `tenant_resource_isolation.py:134` и комментарий
`setup_middlewares.py`). Итог: `checker is None → pass-through`
(`tenant_resource_isolation.py:202-207`). Гейт `check_object_authorization`
сообщает об этом же: «Object ownership check coverage is low (10.7%)».

**F-B (P1) — `tenant_resource_isolation` (330) выполняется раньше `tenant` (300).**
Комментарий `setup_middlewares.py:157` утверждал «Порядок: после tenant (300) —
tenant-идентичность уже в scope/state». Фактически «после» при LIFO = **внутри**,
то есть выполняется **раньше**. Комментарий описывал порядок регистрации, а не
выполнения. Исправлен.

**F-C (P2) — `request_body_cache` (380) раньше `idempotency` (340).** Функционально
не критично: `IdempotencyMiddleware` тело запроса не читает (только `Idempotency-Key`
и Redis). Значимо другое: **`cached_body` не читает ни один production-модуль**
(0 совпадений вне самого `request_body_cache.py`) — заявленный контракт
«downstream читает через `state.get('body')» не имеет потребителей.

---

## 2. P0: подмена tenant через заголовок — воспроизведено и исправлено
> **ПОПРАВКА 2026-10-01 после независимого ре-аудита.** Заявление ниже
> сформулировано как «спуфинг исправлен», и на момент написания оно было верно
> **только для principal'ов, объявляющих `metadata['tenant_id']`**. Независимый
> reviewer воспроизвёл обход без всяких mock'ов: реальный `X-API-Key`
> (principal `global`, у `_verify_api_key` в metadata нет `tenant_id`) +
> `X-Tenant-ID: tenant-b` → **HTTP 200** и чужой tenant в `state`.
> Это был **мой** дефект, а не предсуществующий: мой фикс сливал два разных
> случая в один `None`. Исправлено добавлением `_auth_present()` и
> fail-closed ветки «аутентифицирован, но tenant не заявлен»;
> доказательство и мутация — в разделе 9k (N-1).


### F-D (P0, ИСПРАВЛЕН) — `X-Tenant-ID` переопределял аутентифицированный tenant

**Файл:** `src/backend/entrypoints/middlewares/tenant.py:82` (HEAD)

```python
state["tenant_id"] = header_value if header_value else self._default
```

**Воспроизведение ДО фикса** (реальные production-классы
`AuthRequiredMiddleware → TenantMiddleware`; артефакт
`artifacts/current_audit/tenant_spoofing.json`):

| Сценарий | HTTP | `state['tenant_id']` | `auth.metadata['tenant_id']` |
|---|---:|---|---|
| auth tenant-**a** + `X-Tenant-ID: tenant-b` | **200** | **`tenant-b`** | `tenant-a` |
| auth tenant-a, без заголовка | 200 | **`default`** | `tenant-a` |
| только заголовок, без auth | 401 | — | — |

Ожидалось: **403 `tenant_mismatch`**, tenant = `tenant-a`.

**Независимое подтверждение скептиком.** Скептик-агент не поверил ручной подстановке
`scope['state']['auth']` и воспроизвёл спуфинг **на настоящем подписанном JWT**
(HS256) через реальный 36-middleware стек production-приложения:
`AuthContext` создавался настоящим `verify_request → JwtBackend.verify()`,
`existing_auth` не срабатывал, аутентификация проходила штатно.
Результат: **200, `state_tenant_id='tenant-b'`, `corr_tenant='tenant-b'`.**
Вердикт скептика: **ПОДТВЕРЖДЕНО**.

**Цепочка распространения** (проверена по коду):
`X-Tenant-ID` → `tenant.py:82` → `set_correlation_context` (`tenant.py:86`) →
`tenant_id_var` (`core/observability/correlation.py:62`) → `get_tenant_id()` →
**9 потребителей** (`services/ai/feedback`, `services/notebooks`,
`services/workflows/hitl_service`, `infrastructure/workflow/middlewares/step_audit`,
`infrastructure/audit/event_log`, `infrastructure/logging/structlog_backend`).
Плюс `RequestContextMiddleware:133` и DSL-движок
(`dsl/engine/execution_engine.py:26-40`, `RequestContext.tenant_id` — первый источник).

**Уточнение к формулировке (самокритика):** утверждение «механизма 403 tenant_mismatch
в production-коде нет» **неточно как абсолютное**. Частные fail-closed сверки есть
в двух endpoint'ах: `entrypoints/api/v1/endpoints/hitl.py:83-92` и
`middlewares/ai_tool_whitelist.py:118-122`. Корректная формулировка: механизма
нет в **общем middleware/request-path**; спуфинг блокируется в 2 слоях из N.
Документированного контракта доверенного gateway/mesh в `docs/` не найдено (0 совпадений).

**Исправление** (5 файлов, минимальный диф):

| Файл | Изменение |
|---|---|
| `tenant.py` | Аутентифицированный tenant авторитетен; расхождение с заголовком → **403 `tenant_mismatch`** (fail-closed); `_authenticated_tenant()` через канонический `extract_tenant_id`; явная capability `metadata['tenant_impersonation']`; авторитетный резолв и в response-заголовке |
| `request_context.py` | Тот же авторитетный резолв: этот middleware (order 320) выполняется **раньше** `tenant` (300), иначе подделка доходила до DSL |
| `registry.py` | Устранено внутреннее противоречие docstring (order 71 vs 38-41) + ссылка на runtime-замер |
| `setup_middlewares.py` | Комментарий про порядок изоляции исправлен; зафиксировано, что checker'ы не подключены |
| `tenant_resource_isolation.py` | Противоречие в docstring устранено **без** смены поведения (см. ниже) |

**Узкое место, найденное мутацией и тестами.** Первая версия фикса изменила и
`_resolve_tenant_id` изоляции на `state → header`, что **ослабило fail-closed**:
`test_empty_tenant_header_deny_fail_closed` (пустой заголовок обязан дать 403)
упал. Поведение откачено, изменён только docstring с явной фиксацией риска.
Это ровно тот случай, когда «выравнивание» приоритетов тихо снимает защиту.

**Доказательство после фикса:**

| Сценарий | HTTP | `state['tenant_id']` |
|---|---:|---|
| auth tenant-a + `X-Tenant-ID: tenant-b` | **403 `tenant_mismatch`** | handler не вызван |
| auth tenant-a, без заголовка | 200 | **`tenant-a`** (было `default`) |
| capability на tenant-b → заголовок tenant-b | 200 | `tenant-a` (identity не меняется) |
| capability на tenant-b → заголовок tenant-c | 403 | handler не вызван |
| без auth, с заголовком | 200 | `tenant-b` (контракт не изменён) |

**Регресс и мутация:**
- 8 новых тестов: `tests/unit/entrypoints/middlewares/test_tenant_auth_precedence_security.py`
- мутация ядра фикса (`_authenticated_tenant → None`): **4 из 6 падают**;
  мутация `request_context` (`_authenticated_tenant or header` → `header`): **1 падает**
- кластер `tests/unit/entrypoints/middlewares/`: **583 passed, 3 skipped** (3 skip —
  предсуществующая несовместимость starlette 1.3.1 + httpx 0.28+)
- широкий регресс `tests/unit/entrypoints + tests/unit/core/security + tests/unit/core/auth`:
  **с моим fix 6 failed / 2315 passed**; **на чистом HEAD те же 6** (5 детерминированных
  + 1 order-dependent). Мои 5 тестов на чистом HEAD падают — они и должны падать.
  **Вывод: регрессий от правки 0.**

**Статус: FIXED, не закоммичено.** Коммит — только по явной команде владельца.

---

## 3. Противоречивые комментарии и docstrings (P0-5)

| # | Файл:строка | Было | Стало |
|---|---|---|---|
| 1 | `entrypoints/middlewares/registry.py:71` | «order: … **низкий = наружный**» | «**высокий order = внешний** (outermost)» + ссылка на замер + предупреждение о последствиях для auth/tenant |
| 2 | `setup_middlewares.py:154-157` | «Порядок: после tenant (300) — tenant-идентичность уже в scope/state» | Указано, что при LIFO middleware выполняется **раньше** tenant; tenant берётся из `AuthContext`; зафиксировано отсутствие checker'ов |
| 3 | `tenant_resource_isolation.py:163-168` | «Приоритет сознательно совпадает с TenantMiddleware» | Зафиксировано измеренное расхождение, **почему** оно не исправляется здесь (пустой заголовок обязан давать 403) и условие для будущего исправления |

Модульный docstring `tenant.py` переписан: прежний «Порядок приоритета: 1. Header»
уже не соответствует коду.

---

## 4. Lifecycle (агент + собственная верификация)

Артефакт: `artifacts/current_audit/lifecycle_graph.json` (19 startup-фаз извлечены из кода).

**F-E (P1, ИСПРАВЛЕН) — типа `LifecycleOperation` не существовало.** `grep` → 0 совпадений.
Исходно операции описывались двумя кортежными структурами без метаданных:

| Структура | Файл:строка | Фактические поля | Нет |
|---|---|---|---|
| `STARTUP_PHASES: tuple[Phase, …]`, `Phase = Callable[[FastAPI], Awaitable[None]]` | `startup_phases/__init__.py:27,30` | только callable | name, phase, start, stop, enabled, criticality, timeout, dependencies |
| `starting/ending_operations: list[OperationItem]`, `OperationItem = tuple[str, Callable, Callable[[],bool]｜None]` | `setup_infra/lifecycle.py:37-39,346,385` | 3 | criticality, timeout, dependencies, **stop** |
| `run_shutdown` | `lifecycle/shutdown.py:45-247` | не структура данных — 14 ручных `try/except` | всё |

**Исправление — см. §4-bis.**

**F-F (P1) — нет reverse-order rollback.** `lifecycle/lifespan.py:102-105`:
`finally: if startup_completed: await run_shutdown(...)` — при `False` блок
пропускается целиком. Runtime-замер: `start:phase1-OK, start:phase2-OK,
start:phase3-BOOM → ROLLBACK ran: False`. Startup строго последовательный
(`startup.py:224-225`), топологии нет, per-operation timeout отсутствует
(единственный `asyncio.timeout(5.0)` — на EventBus, `startup.py:69`).

**F-G (P1) — production readiness-probe fail-open.** `/health/ready`
(`app_factory.py:454-471`) не блокируется на завершении startup, и именно он
прописан в манифестах: `deploy/k8s/deployment-app.yaml:85,91`,
`deploy/helm/.../deployment-app.yaml:70,76`. Замер без lifespan:
`/health/ready → 200 {"status":"ok","message":"No health checks registered"}`,
тогда как `/readiness → 503 {"status":"initializing"}`.
Дополнительно `health_aggregator.py:212`: пустой реестр → `overall = "ok"`
(implicit success).

**F-H (P1) — два readiness-эндпоинта с противоположной политикой.** Один компонент
со `status:"degraded"` даёт `/health/ready → 503 degraded`, но
`/readiness → 200 {"degraded": false}` — coordinator ничего не знает
(`registered components: 0`). Ни один не является доверенным.

**F-I (P1, ИСПРАВЛЕН) — fail-open в AgentSecurityFramework hooks.** Исходно
зафиксировано две точки; при исправлении обнаружились ещё две в том же методе.

| # | Место | Было | Стало |
|---|---|---|---|
| 1 | `setup_infra/lifecycle.py` `_register_agent_security_workflow_hooks` | `except Exception → app_logger.debug(...)`: сбой регистрации проглатывался, старт продолжался без хуков | при `enable_workflow_hooks=True` — `raise` + `error`-лог; при `False` — мягко; `ImportError` профиля без AI-security — не фатально |
| 2 | `agent_security_framework._run_hooks` | `except Exception → continue`, то есть **allow** | явный **deny** с `threat_level=HIGH`, `matched_pattern=hook.name` |
| 3 | `validate_prompt`, ветка injection | `self._run_hooks("pre_llm", …)` — результат **отбрасывался** | deny hook'а возвращается |
| 4 | `validate_prompt`, «чистый» путь | `_run_hooks("pre_llm", …)` **вообще не вызывался** — обычный prompt не проверялся workflow-хуками | хуки выполняются всегда, deny уважается |
| 5 | `mask_output` (`post_tool`) | `self._run_hooks("post_tool", …)` — результат отбрасывался | deny hook'а возвращается |

Пункты 3–5 — отдельная находка **F-AH (P1)**: даже не падающий hook не мог
повлиять на результат. То есть fail-open был не «только при исключении», а
системный: workflow-security не имел enforcement вовсе.

**Регресс-тесты:** `tests/unit/core/ai/security/test_agent_security_hooks_failclosed.py`
(9 тестов: 5 на fail-closed, 4 на сохранение прежнего поведения при выключенных
хуках, отсутствии модуля и явном deny).

**Мутационное доказательство:**

| Мутация | Результат |
|---|---|
| `continue` вместо deny в `_run_hooks` | 2 теста падают |
| возврат `decision` вместо `hook_decision` (`pre_llm`/`post_tool`) | 2 теста падают |
| полный откат обоих файлов к HEAD | **5 из 9 падают** — ровно по одному на каждый fail-open |

**Проверка отсутствия регрессий (сравнение на одном и том же кластере
`tests/unit/core/ai + tests/unit/services/ai`):**

| Состояние | Результат |
|---|---|
| Мои правки откачены (`git stash`), тест-файл новый | 20 failed / 1576 passed |
| Мои правки применены | **15 failed / 1581 passed** |

Разница в 5 тестах объяснена полностью: это мои же 5 новых тестов, которые на
уязвимом коде обязаны падать. **Пре-существующие 15 падений идентичны в обоих
состояниях — регрессий нет.** Проверено отдельно: на HEAD-варианте кода падают
ровно `test_raising_hook_denies…`, `test_raising_hook_does_not_fall_through…`,
`test_pre_llm_hook_decision_is_not_discarded`, `test_post_tool_hook_decision_is_not_discarded`,
`test_registration_failure_is_fatal_when_hooks_enabled`.

Дополнительно: `tests/unit/core/ai/security + tests/unit/core/ai/test_workflow_hooks.py`
→ **45 passed**, регрессий нет.


**F-J (P1) — shutdown не изолирован.** `setup_infra/lifecycle.py:117-123` делает
`raise` внутри цикла: падение первой `ending_operations` пропускает остальные
(`stop_scheduler_if_leader`, `stop_config_hot_reload`,
`stop_temporal_worker_runtime` не вызваны), при этом `shutdown.py:160`
безусловно логирует «Приложение остановлено».

**F-K (P2) — `PluginLoader.shutdown_all()` не идемпотентен.**
`services/plugins/loader/__init__.py:208-218`: runtime `on_shutdown_total=1` после
первого вызова, `=2` после второго; `shutdown_one` (:233) в том же модуле
идемпотентен.

**F-L (P2 → ИСПРАВЛЕН, SECURITY-P0-005) — degradation-заглушки рапортуют HEALTHY вместо UNBOUND.**
Исходно: `core/resilience/graceful_degradation.py:112` инициализировал состояние
`HEALTHY`; `setup_infra/lifecycle.py:59-65,76-82` регистрировал 4 типовых feature
(`ai.llm_call`, `rag.retrieval`, `external.api_call`, `cache.lookup`) с
обработчиками-заглушками `_unsupported_*`, бросающими `NotImplementedError`.
Замер снимка до правки:

```
{"ai.llm_call": {"state": "healthy", "samples": 0, "error_rate": 0.0}}
```

То есть «успех» и «ноль ошибок» для того, что **ни разу не выполнялось**.
Докстринг регистрации при этом прямо признавал: «Real-handler'ы — заглушки».

**Исправление:**
1. `FeatureState.UNBOUND = "unbound"` — новое честное состояние;
2. `DegradationFeature.bound: bool = True` — по умолчанию обратная совместимость;
3. `register()` инициализирует `UNBOUND`, если `bound=False`;
4. `snapshot()` для UNBOUND отдаёт `bound: false` и `error_rate: null`
   (не `0.0`) плюс явный флаг `bound` для всех записей;
5. production-регистрация заглушек помечена `bound=False`.

Снимок после правки:

```
ai.llm_call : {"state":"unbound","bound":false,"samples":0,"error_rate":null}
real.feature: {"state":"healthy","bound":true,"samples":0,"error_rate":0.0}
```

**Проверка безопасности формы снимка.** Потребители:
`entrypoints/api/v1/endpoints/tech.py:206` → `services/core/tech.py:195` (прямая
передача) и UI `src/frontend/streamlit_app/pages/78_Плавная_деградация.py:53`.
UI рендерит карту **режимов системы** (`_MODE_COLORS: full/read_only/degraded/…`,
строка 28-38), а не состояния feature'ов, и поля `state`/`error_rate`/`samples`
не использует — изменение формы снимка для него безопасно.

**Осознанно НЕ изменено (F-AI, P3).** `record_outcome()` для **незарегистрированного**
feature возвращает `HEALTHY` — это no-op-путь, закреплённый существующим тестом
`test_record_outcome_unknown_feature_returns_healthy` («→ HEALTHY (no-op)»). Моя
первая версия правки меняла его на `UNBOUND`, что уронило этот тест. Менять
соседний контракт в рамках этой задачи — расширение scope с риском регрессий
(возвращаемое значение используется для ветвления у вызывающих), поэтому
изменение откачено и зафиксировано как отдельная находка F-AI.

**Регресс-тесты:** `tests/unit/core/resilience/test_degradation_unbound.py` (7),
включая проверку реальной production-регистрации.

**Мутация:** `bound=False` → `bound=True` в production-регистрации → тест
`test_all_production_default_features_are_unbound` падает; возврат → 7 passed.

**Отсутствие регрессий:** `tests/unit/core/resilience + tests/unit/services/core +
tests/unit/plugins` → **534 passed, 6 skipped, 8 xfailed, 0 failed**.

**F-M (P2) — манифест worker'а ссылается на несуществующий `/probe/ready`.**
`deploy/k8s/deployment-worker.yaml:103-106`; маршрута нет в `src/`.

---

## 4-bis. LIFECYCLE: типизированные операции (F-E/F-F/F-J — ИСПРАВЛЕНЫ)

### Что сделано

| Файл | Назначение |
|---|---|
| `src/backend/plugins/composition/lifecycle/operations.py` | **новый**: `Criticality`, `LifecycleOperation`, `LifecycleRunner`, `LifecycleReport`, `LifecycleStartupError`, `build_operations` |
| `src/backend/plugins/composition/setup_infra/lifecycle.py` | 11 инфраструктурных операций переведены на типизированный список с явными парами start/stop, `criticality`, `timeout`, `dependencies`; `starting()`/`ending()` работают через runner |
| `src/backend/plugins/composition/lifecycle/lifespan.py` | `run_shutdown` выполняется **и при неудачном старте** (было `if startup_completed`) |

`LifecycleOperation` несёт ровно поля из objective: `name`, `phase`, `start`, `stop`,
`enabled`, `criticality` (REQUIRED/OPTIONAL), `timeout`, `dependencies`.

`LifecycleRunner` даёт заявленную семантику:

- **топологический старт** — сортировка Кана по `dependencies`, явный отказ на цикле
  и на неизвестных зависимостях;
- **таймаут на операцию** через `asyncio.timeout`;
- **reverse-order rollback** — только реально стартовавших операций; падавшая
  REQUIRED-операция и деградировавшая OPTIONAL откату **не** подлежат;
- **отдельное состояние optional-деградации** — `LifecycleState.DEGRADED`, startup продолжается;
- **идемпотентный shutdown** — повторный вызов ничего не делает;
- **изоляция ошибок shutdown/rollback** — падение одного `stop` не мешает остальным;
- **структурированный отчёт** — `LifecycleReport.to_dict()` (JSON-совместим).

### Миграция без поломки контракта

Кортежи `OperationItem` и списки `starting_operations`/`ending_operations`
**сохранены** как backward-compatible API: на них ссылаются `setup_infra/__init__.py`
(re-export), документация конфигурации (`core/config/features/infrastructure.py:435`)
и тесты. Канонической структурой для *исполнения* стал `LifecycleOperation`.

Порядок выполнения не изменился — проверено сравнением топологического плана с
прежним списком:

```
 1. register_default_degradation_features   REQUIRED t=30  deps=-
 2. register_health_checks                  REQUIRED t=30  deps=-
 3. register_pools_in_unified_manager       REQUIRED t=30  deps=-
 4. start_mongo_client                      REQUIRED t=30  deps=-
 5. warmup_connection_pools                 REQUIRED t=30  deps=start_mongo_client
 6. start_pool_monitors                     REQUIRED t=30  deps=register_pools_in_unified_manager
 7. register_agent_security_workflow_hooks  REQUIRED t=15  deps=-                 stop=да
 8. start_config_hot_reload                 REQUIRED t=30  deps=-                 stop=да
 9. init_workflow_audit_sink                OPTIONAL t=30  deps=-                 stop=да
10. start_temporal_worker_runtime           REQUIRED t=60  deps=-                 stop=да
11. start_scheduler_with_leader_election    REQUIRED t=30  deps=register_pools_in_unified_manager  stop=да
```

Парность start/stop задана явно вместо двух независимых списков. Безопасность
`stop` при незапущенном состоянии проверена по коду: `_stop_scheduler_if_leader`
пропускает non-leader инстансы по контракту docstring
(`setup_infra/scheduler_leader.py:170-180`), `_close_workflow_audit_sink` выходит
при `sink is None` (`setup_infra/workflow_audit.py:58-60`).

### Доказательства

**Регресс-тесты:** 20 новых тестов —
`tests/unit/plugins/composition/lifecycle/test_lifecycle_operations.py` (18)
и `test_lifespan_rollback.py` (2).

**Мутации (все пойманы):**

| Мутация | Результат |
|---|---|
| откат в прямом порядке (`reversed` → `list`) | 2 теста падают |
| shutdown не изолирует (`continue` → `raise`) | 1 тест падает |
| `if startup_completed:` вокруг `run_shutdown` (исходный код) | 1 тест падает |

**Отсутствие регрессий (`tests/unit/plugins`, один и тот же кластер в двух состояниях):**

| Состояние | Результат |
|---|---|
| lifecycle-правки откачены | 1 failed / 185 passed / 2 skipped / 8 xfailed |
| lifecycle-правки применены | **0 failed / 186 passed** / 2 skipped / 8 xfailed |

Единственное падение в базовом состоянии — мой собственный
`test_shutdown_runs_when_startup_fails`, который по построению падает на уязвимом
коде. Ни один пре-существующий тест не сменил статус: **регрессий 0**.

**Осознанно НЕ сделано в этой волне:** 19 `STARTUP_PHASES` остались
вызываемыми кортежами `Callable[[FastAPI], Awaitable[None]]` — у них нет
`stop`-функций, поэтому перевод на `LifecycleOperation` не дал бы отката, зато
изменил бы публичный контракт фазы. Они выполняются строго последовательно внутри
`run_startup`; откат инфраструктурных операций при падении фазы обеспечен тем,
что `lifespan` теперь **всегда** вызывает `run_shutdown`.

---

## 5. Clean Architecture (агент, с самоопроверкой)

**F-N (High) — гейт слоёв слеп к third-party импортам.** `tools/check_layers.py`:
`_layer_of("fastapi") → None → continue`. Гейт проходит (exit 0,
«0 новых, 22 legacy»), но не видит ни fastapi/starlette, ни клиентов в `core/`.
Собственный AST-скан агента: **32 top-level нарушения** — это нижняя граница.
`--strict` → exit 1, 22 нарушения, из них **6 — запрещённое направление `core → services`**.
Allowlist **регрессировал**: 38→37→25→21→14→22, при том что коммит `ed8ab98a0`
объявлял «≤15 достигнуто».

**F-O (High) — domain-модели на SQLAlchemy.** 9 файлов в
`core/domain/models/` импортируют `sqlalchemy` на верхнем уровне
(`base.py`, `cert.py`, `dsl_snapshot.py`, `langmem_models.py`, `outbox.py`,
`rule_engine.py`, `scheduler_run_history.py`, `workflow_event.py`,
`workflow_instance.py`) — Active Record в домене, подмена persistence невозможна.

**F-P (High) — `core` тянет веб-фреймворк в рантайме.** `core/errors.py:32-33`
(`starlette.status`, `starlette.types`), `core/auth/protocols.py`,
`core/auth/admin_roles.py:21` (`class AdminAuthorizationError(HTTPException)`),
`core/net/http_utils.py:3`. Доказано runtime-загрузкой `sys.modules`.

**F-Q (Med) — DSL тянет infrastructure напрямую.**
`dsl/engine/versioning.py:21` импортирует `main_session_manager`;
`dsl/engine/execution_engine.py:20` — конкретный `TracingMiddleware`.
Уточнение агента: 9 из 11 dsl-файлов с sqlalchemy используют DI-провайдеры
(инверсия корректна) — обвинение сужено.

**F-R (Med) — стадия compile декоративна.** `PipelineCompiler` — **0 production-вызовов**
(только тесты), `CompiledPipeline.is_valid = processor_count > 0`,
`_cached_validate() -> Any`. Стадии parse/validate и execute/observe существуют
и типизированы (`ValidationResult`, `ValidationIssue`); **compile отсутствует**,
типизированного IR нет (922 `dict[str, Any]` в `dsl/`).

**F-S (PASS) — `Exchange` чист.** `dsl/engine/exchange.py:133` — Pydantic,
поля `meta/in_message/out_message/properties/status/error`, без сети/БД/брокеров.

---

## 6. Library consolidation (агент)

Проверялось **фактическое состояние venv**, а не только наличие в `pyproject.toml`:
`temporalio` **MISSING**, `openfeature` **MISSING**, `playwright` **MISSING**;
`testcontainers`, `schemathesis`, `faststream`, `nats`, `aio_pika`, `aiokafka` — установлены.

| Библиотека | Вердикт | Ключевое доказательство |
|---|---|---|
| **OpenFeature** | `DECLARED_ONLY` → самописная замена в проде | SDK не установлен; `import openfeature` — **0 строк** во всём репо; `openfeature_provider.py` (444 LOC) — самописный `Protocol`-шим; прод читает `feature_flags.*` в 289 местах / 165 файлах (5954 LOC кастомного кода) |
| **Schemathesis** | `PARTIAL` — контракт не проверяется | тестов с `import schemathesis` — **0**; `api-fuzz.yml:25` `continue-on-error: true`, `:52` `FEATURE_SCHEMATHESIS_GATE_ENABLED: "false"`, `:60` `\|\| echo "[api-fuzz] warn"` — gate проваливается намеренно |
| **Testcontainers** | `REAL_USE` | 19 файлов; `tests/integration/test_testcontainers_smoke.py:31,46` реальные `PostgresContainer`/`RedisContainer` + SQL round-trip; дефолтного deselect нет |
| **FastStream** | `REAL_USE`, но не единственный путь | реальные импорты в stream/subscribers/asyncapi; **параллельно** прямые `nats`, `aio_pika`, `aiokafka` в sources/sinks/CDC |
| **Temporal** | `PARTIAL` — молча деградирует | 40 импортов и реальные `register_activity`, но SDK отсутствует → `factory.py:79-117` уходит в `PgRunnerWorkflowBackend`, то есть **in-memory-заглушка выдаёт себя за workflow** |
| **Playwright** | `PARTIAL` — RPA-код реален, пакет нет | `browser_pool.py:117`, `browser.py:69`; тесты используют `AsyncMock` (`test_rpa_browser.py:18,104`), браузерный тест **исключён** из прогона (`pyproject.toml:1190 --ignore=…test_streamlit_via_playwright.py`); параллельно подключён `patchright` |

Оценка миграции на OpenFeature: **отклонить** как «уже сделанную».
Custom LOC до ≈ 5954; риск высокий (289 мест чтения, env-контракт `FEATURE_*`,
`runtime_overrides`, audit). Разумный путь — dual-provider за существующим флагом
`openfeature_external` (default-OFF) с метрикой расхождений; rollback = выключить флаг.

---

## 7. Dead code (агент)

Проверены все 7 каналов. Обнаружены **динамические каналы**, обнуляющие выводы
по статическим импортам: `dsl/registry/lazy_processor.py:63-77` (`importlib` по
строке `namespace:name`) и `entrypoints/middlewares/registry.py:182-195`
(`[[middleware]] module=`).

**Единственный подтверждённый кандидат в удаление:**
`core/feature_flags/redis_broadcaster.py:319` `_now_utc()` — 4 LOC, все 7 каналов чисты.

**Проверено и оставлено (ложные срабатывания):**
`desktop_pyautogui` (161 LOC) и `infra_elasticsearch` (117) — `@processor`-регистрация,
runtime-подтверждено в реестре; `web.py` (213, DEPRECATED) — живые строковые каналы
`dsl/builders/ai_rpa/rpa.py:82,237` + API-каталог; `dsl/processors/saga_lra_processor/`
(3 LOC шим) — контракт ADR-0341; `event_store/*` (5 шимов) — закреплены тестами;
`degradation.py` (246) — зарегистрирован `setup_middlewares.py:169`.

**Прежний артефакт `dead_code_candidates.md` частично ОПРОВЕРГНУТ как устаревший:**
заявленный дубликат `core/services/base_external_api.py` не существует;
`saga_lra_processor` — уже 3-строчный шим, а не «811 LOC legacy-копии».

---

## 8. Честность гейтов (собственная находка, сессионная)

Обнаружено **до** начала новой волны, воспроизводимо на этом же HEAD:

**F-T (P1) — гейт docstrings fail-open и работает не на том интерпретаторе.**
`make/quality.mk:123` вызывает `python3 tools/check_docstrings.py` — системный
**3.12.3**, тогда как проект на 3.14. Под 3.12 гейт молча пропускает **164 файла**
(6.4% корпуса) — PEP 758 `except A, B:`; все 164 проверены и валидны под 3.14.
Сам скрипт fail-open: `tools/check_docstrings.py:263-265` ловит `SyntaxError`,
печатает warning и возвращает **пустые** stats, которые считаются чистыми
(`:318 total_files = len(all_stats)` — счётчик завышен).

Мутационное доказательство: корпус с битым модулем → гейт **exit 0**, «0 missing
in 0 files», «Files scanned: 2», тогда как `compileall` на том же дереве → exit 1.

**F-U (P1) — `check-object-auth` fail-open в двух слоях.** Печатает
«❌ coverage 10.7% (<50%)» и «❌ 127 service lookups without tenant filter», но
exit 0. Причина — `tools/checks/check_object_authorization.py:219-221`:
`return 1` только при `args.strict and issues`. `--strict` существует, но не
подключён ни в `make check-object-auth` (`make/quality.mk:293`), ни в
`audit-2026-09-22` (`:319`), а в CI `.github/workflows/lint.yml:220` вызывается
без `--strict` **и** с `|| true`; в `make ci` гейта нет вовсе.

**F-V (P2) — `lint`/`format-check`/`check-docstrings` не видят `tests/`.**
`Makefile:7 SOURCE_DIR ?= ./src`. Сейчас дерево чистое
(`ruff check ./tests` → All checks passed), поэтому риск латентный.

Попутно: ложная тревога снята — «CI вызывает несуществующий `make checks`» оказалось
совпадением внутри комментария `lint.yml:148`, а не вызовом.

---

## 9a. Тесты, CI и производительность (агент QA)

Полный протокол выполнен агентом на этом же worktree. **Важная оговорка, которую
агент зафиксировал сам:** первые два прогона `-m unit` шли по изменяющемуся дереву
(параллельно работал я), поэтому как evidence не годятся; все числа ниже взяты из
6 чанков на стабильном дереве с `git diff` до == после.

| Проверка | Exit | Результат | Статус |
|---|---:|---|---|
| `compileall src extensions plugins testkit tools` | 0 | пусто | **PASS** |
| `ruff format --check .` (repo-wide) | 1 | 292 файла (docs 195, tools 71, extensions 15); **в `src/` — 0** | **FAIL** |
| `make format-check` (`./src`) | 0 | 2540 файлов | PASS (ограниченный scope) |
| `ruff check .` (repo-wide) | 1 | 34 ошибки, **0 в `src/`** | **FAIL** |
| `tools/check_layers.py` | 0 | 0 новых, 22 legacy | **PASS** (с оговоркой) |
| `pytest --collect-only -q` | 2 | 20641 collected, **3 errors**, сбор прерван | **FAIL** |
| `pytest -m unit` | 124×2 | 19758 passed / 70 failed / 16 errors / 195 skipped | **FAIL** |
| `pytest -m integration` | 1 | 229 passed / 16 failed / 32 skipped / 7 errors | **FAIL** |
| `pytest -m e2e` | 1 | 8 passed / 17 skipped / 6 errors | **FAIL** |
| `pytest -m property` | 2 | **0 тестов собрано** | **NOT_RUN** |
| `pytest -m security` | 2 | **0 тестов собрано** | **NOT_RUN** |
| `create_app()` startup | — | требует БД-env | **ENV_BLOCKED** |
| `tools/checks/startup_time.py` | 0 | 7 модулей, TOTAL 1.289s | PASS (не покрывает `create_app`) |

**F-W (P0, ИСПРАВЛЕН) — 3 collection-ошибки блокировали ВСЕ прогоны.**

**Корень (не в проекте).** `presidio_analyzer/nlp_engine/device_detector.py:62`
`_detect()` импортирует `torch` **на уровне модуля**. В venv стоит CUDA-сборка torch,
а системных `libnvrtc.so.*` / `libcudart.so.*` нет →
`ValueError: libnvrtc.so.*[0-9] not found in the system path`.
`pytest.importorskip` ловит только `ImportError`, поэтому вместо честного skip
модуль падал на collection, а collection-ошибка прерывает **весь** прогон pytest.

Воспроизведение ДО фикса:
```
$ .venv/bin/python -m pytest --collect-only -q
ERROR tests/unit/services/ai/pii/recognizers/test_inn_recognizer.py - ValueEr...
ERROR tests/unit/services/ai/pii/recognizers/test_inn_recognizer_property.py
ERROR tests/unit/services/ai/test_pii_recognizers.py - ValueError: libnvrtc.s...
!!! Interrupted: 3 errors during collection !!!
20643 tests collected, 3 errors            EXIT=2
```

**Исправление** (только тесты, зависимости не трогались):
- новый `tests/unit/services/ai/pii/recognizers/_presidio_guard.py` —
  `skip_if_presidio_unavailable(module_path)`;
- все три файла переведены с прямого `import` / `importorskip` на этот гвард.

Гвард ловит `ImportError/OSError/ValueError` и превращает в `pytest.skip` **только**
если ошибка окруженческая (в тексте `libnvrtc`/`libcudart`/`CUDA` либо в цепочке
`torch`/`onnx`/`nvidia`). Любая другая ошибка **пробрасывается** — дефекты проекта
гвард не прячет. Текст skip'а прямо фиксирует: «Статус окружения — SKIPPED, не PASS».

**После фикса:**
```
$ .venv/bin/python -m pytest --collect-only -q
20643 tests collected                    EXIT=0
$ .venv/bin/python -m pytest <3 файла> -q
3 skipped in 0.11s   (причина видна, указывает на torch/CUDA)
```

**Мутация (обязательная):** отключение ветки skip (`if False:  # MUTATION`) →
`Interrupted: 3 errors during collection`, **EXIT=2**; возврат гварда → EXIT=0.
Эффект доказан в обе стороны.

**Побочный эффект, меняющий другие статусы.** Раньше `-m property` и `-m security`
падали с exit 2 из-за прерывания сбора, и я их классифицировал как NOT_RUN.
С разблокированным collection они выполняются штатно:
```
$ .venv/bin/python -m pytest -m property -q
20 skipped, 20643 deselected            EXIT=5
$ .venv/bin/python -m pytest -m security -q
20 skipped, 20643 deselected            EXIT=5
```
Exit 5 = «тесты не выбраны». Значит **F-X подтверждён независимо от F-W**:
маркеры действительно мёртвые — это не артефакт сломанного сбора.


**F-X (P1) — маркеры `property` и `security` мёртвые.** Собирается ровно **0** тестов.
`pytest.mark.security` — **0 вхождений** в коде и маркер **даже не зарегистрирован**
(`pyproject.toml:1191-1226`); `pytest.mark.property` — 0 вхождений, хотя зарегистрирован.
Команды `-m security` / `-m property` всегда дают пустой прогон, который не выглядит
провалом. ~43 теста в `tests/unit/security` не изолированы маркером.

**F-Y (P1, ИСПРАВЛЕН) — два теста портили tracked-файлы репозитория.**
- `tests/unit/docs/test_adr_wiki_no_plan_ref.py` → `subprocess` запускает
  `tools/build_adr_wiki.py`, который пишет в tracked `docs/adr/WIKI.md`
  (`build_adr_wiki.py:25 OUT = ADR_DIR / "WIKI.md"`, абсолютный путь, `tmp_path` не используется).
  Docstring теста утверждал обратное: «Subprocess изолирует side-effects (запись WIKI.md)
  от тестов» — это было ложно.
- `tests/unit/tools/test_quality_results_aggregator.py` → пишет tracked
  `.audit/quality-results.json`.

Измеренный ущерб до фикса: diff WIKI.md меняет дату `2026-09-30 → 2026-10-01`;
`quality-results.json` — 62 insertions / 61 deletions, причём в коммите лежит
`"head": "a2bd6f294"` и путь `/home/user/dev/gd_integration_tools/.venv/...` —
то есть baseline чужой машины и чужого коммита.

**Исправление:** в обоих тестах tracked-файл снимается **побайтово** до запуска
и восстанавливается в `finally` (с удалением, если файла изначально не было).
Тест по-прежнему проверяет реальный вывод aggregator'а / builder'а, но репозиторий
не меняется.

**Доказательство изоляции — на масштабе, а не на одном файле.** После полного
прогона `-m unit` (**19696 тестов**) tracked-артефакты остались байт в байт:

```
$ sha256sum docs/adr/WIKI.md .audit/quality-results.json   # после 19696 тестов
56b9c3b0e76cc602c2f7d723cfe471ebe4428a49e89325a77427ac79ff0d5d8c  docs/adr/WIKI.md
72f2f32c901079e51b831af199ade60658d4a200d928011f4e60d06b770e0945  .audit/quality-results.json
$ git status --short .audit/ docs/adr/
(пусто)
```

До фикса те же два файла менялись при каждом прогоне.

**Моя ошибка, зафиксированная честно:** первая проверка выполнялась **параллельно**
с полным прогоном `-m unit`, и `docs/adr/WIKI.md` показал изменённый sha. Это была
**гонка двух прогонов**, а не отказ фикса: изолированный повтор (`4 passed in 0.25s`)
и последующий полный прогон без параллельных запусков показали неизменные sha.
Вывод «фикс не работает» был бы неверным — поэтому проверка переделана.



**F-Z (P1) — `release-gate.yml` гарантированно падает.** `:57` объявляет
`set -euo pipefail`, `:60` использует `${REPO}` в URL, но `REPO` нигде не определён.
Воспроизведено: `bash -c 'set -euo pipefail; echo "/repos/${REPO}/x"'` →
`REPO: не заданы границы переменной`, exit 1. Единственный агрегатор
required-checks не может стать зелёным никогда.

**F-AA (P1) — три CI-заглушки печатают «PASS» и ничего не проверяют.**
`ai-pr-review.yml:65,68,71` — `uv run python -c "print('… check: PASS')"`, весь job
`review` с `continue-on-error: true`.

**F-AB (P1) — 27 warn-only шагов из 213 (12 %).** В частности,
`lint.yml:182 check_tenant_isolation.py --strict || true` — флаг `--strict`
полностью обесценен; `lint.yml:198 check_privacy_lifecycle.py || true`;
целиком `continue-on-error`: `security.yml` job `gitleaks` и `trivy`,
`type.yml` job `pyright`, `perf-gate.yml`, `api-fuzz.yml`.

**F-AC (P1) — repo-wide линт не выполняется вообще.** `Makefile:8 SOURCE_DIR ?= ./src`,
поэтому `make format-check` и `make lint` видят только `src/`, а **295 нарушений вне
`src/`** не проверяются ни локально, ни в CI. Сама цель `make lint` warn-only
(`make/quality.mk:6-9` — `|| printf`), и vulture находит мёртвый код, который проглатывается.

**F-AD (P2) — `test.yml:55-56` `--maxfail=20 -n auto`.** Первое обрезает реальную
картину падений (в unit 86 non-passing), второе прямо противоречит предупреждению
`Makefile:36-43` про OOM-ханг на 15 ГБ / 4 ядрах.

**F-AE (P2) — startup-гейт измеряет не приложение.** `tools/checks/startup_time.py`
импортирует 7 модулей и никогда не трогает `create_app`, оставаясь зелёным при
любой регрессии реального старта.

---

## 9b. cURL-сессия против живого сервера

Артефакт: `artifacts/current_audit/curl_results.json` (27 результатов).
Сервер: `uvicorn src.backend.main:app --host 127.0.0.1 --port 8012`,
старт: «Приложение успешно запущено: **132 actions, 0 DSL-маршрутов**».
Эндпоинты взяты из **фактического** `/openapi.json` (OpenAPI 3.1.0, **414 paths**,
142 schemas), а не из README. Флаги: `curl --fail-with-body -sS`.

**Раскрытие окружения:** `MONGO_ENABLED=false` (документированный переключатель
профиля `dev_light`); MongoDB недоступен, креды PostgreSQL в профиле невалидны,
поэтому БД-зависимые сценарии дают 401/403/404, а не бизнес-ответы.

Распределение статусов: **200×8, 400×1, 401×10, 403×6, 503×2**.

| Сценарий | Ожидалось | Факт | Вердикт |
|---|---|---|---|
| `/health` | 200 alive | 200 `{"status":"alive"}` | PASS |
| `/health/ready` (проба в k8s-манифестах) | 503 при недоступной БД | 503, структурно: redis ok 5.26 ms, **database error**, s3 error | PASS (ожидаемо) |
| `/ready` | 503 | 503 | PASS |
| `/readiness` | 200/503 | **401** — под аутентификацией | наблюдение |
| `/docs`, `/redoc`, `/metrics`, `/openapi.json` | 200 | 200 | PASS |
| admin / `/mcp` без auth | 401 | 401 | PASS |
| admin с мусорным Bearer | 401 | 401 | PASS |
| `/graphql` introspection | 403 (политика) | 403 | PASS |
| `/soap/wsdl` | 200 | **401** — WSDL под аутентификацией | наблюдение |
| path traversal, SSRF `file://` | не проходит | 401 | PASS |
| невалидный JSON | 400/401 | 403 (без кредов) | наблюдение |
| `Idempotency-Key` без кредов | 401/400 | 403 | наблюдение |
| `Host: evil.example.com` | 400 | 400 | PASS |
| отражение `X-Correlation-ID` | эхо | `x-correlation-id: audit-corr-42` | PASS |

### Главное: P0-фикс подтверждён на живом HTTP

Запрос с **настоящим подписанным JWT** (`tenant_id=tenant-a`) и подделанным
`X-Tenant-ID: tenant-b`:

```
HTTP 403
{"error":"tenant_mismatch","detail":"X-Tenant-ID не совпадает с tenant
 аутентифицированного principal; impersonation capability не объявлена"}
```

Контроли: тот же JWT без заголовка → **404** (auth и tenant прошли, маршрута нет);
заголовок без токена → **401**. В ответе 403 заголовок `X-Tenant-ID` **отсутствует** —
отказ не раскрывает tenant.

### F-AF (P2) — `x-request-id` дублируется в каждом ответе

Локализовано инструментацией пути ответа (сколько копий видит каждый middleware):

```
ExceptionHandler … CircuitBreaker   [0]
RequestIDMiddleware                 [1]   ← добавляет одну
CorrelationIdMiddleware             [2]   ← добавляет вторую
```

Корень: `asgi_correlation_id.CorrelationIdMiddleware` по умолчанию
`header_name='X-Request-ID'` (`site-packages/asgi_correlation_id/middleware.py:40`),
а регистрация идёт без опций — `setup_middlewares.py:149`, обёртка
`correlation.py:13`. То есть проект дважды подключает два middleware, оба
управляющие `X-Request-ID`. Класс назван `CorrelationIdMiddleware`, но по умолчанию
управляет request-id, а реальный `X-Correlation-ID` добавляет `RequestIDMiddleware`.

**F-AG (P2) — `Referrer-Policy` отсутствует.** Присутствуют HSTS, `nosniff`,
`X-Frame-Options: DENY`, CSP, `Permissions-Policy`.

---

## 9a-bis. Перезамер после фиксов F-W и F-Y

Collection разблокирован, поэтому `-m unit` впервые за эту волну выполняется
**штатно одним прогоном** (без разбиения на чанки) и **без параллельных запусков**:

```
$ .venv/bin/python -m pytest -m unit -q -n 3 --dist loadfile
135 failed, 19696 passed, 194 skipped, 48 xfailed, 46 xpassed, 7 errors
in 433.71s (0:07:13)                              EXIT=1
```

Сверка с измерением агента (6 чанков): 19758 passed / 70 failed / 16 errors.
Числа расходятся (19696/135/7 против 19758/70/16). Расхождение ожидаемо и объясняется
методологией: один сквозной прогон с xdist даёт иной порядок исполнения и иной
профиль загрязнения между тестами, чем шесть последовательных чанков; кроме того,
после фикса F-W три модуля перешли из collection-error в честный skip. Считаю
**эталонным** именно сквозной прогон: он ближе к тому, как CI реально запускает
`pytest tests -n auto`.

**Топ файлов по падениям (один прогон):**

| Файл | Падений |
|---|---:|
| `tests/unit/infrastructure/repositories/test_base_repository.py` | 24 |
| `tests/unit/dsl/blueprints/test_python_blueprints_focused.py` | 17 |
| `tests/unit/services/ai/test_rag_ingest_service.py` | 9 |
| `tests/unit/services/ai/test_presidio_ru.py` | 5 |
| `tests/unit/services/integrations/test_dadata.py` | 4 |
| `tests/unit/entrypoints/mcp/test_http_server_auth_wrap.py` | 4 |
| `tests/unit/dsl/workflow/compiler/test_sensor_polling_caps.py` | 4 |
| `tests/unit/dsl/engine/processors/test_control_flow.py` | 4 |
| `tests/unit/core/config/test_hvac_graceful_fallback.py` | 4 |

Причина падений **не классифицирована** — это отдельная задача; здесь фиксирую
факт «135 падений на HEAD 3b509542e», а не причину.

---

## 9c. README: метрики из кода вместо ручных (F-AJ — ИСПРАВЛЕН)

### Что было не так

1. **Устаревшее inline-число.** В диаграмме архитектуры стояло
   `ActionHandlerRegistry (109 actions)`. Фактическое значение, снятое из
   рантайм-реестра после `create_app()`: **132**. Расхождение — 23 action'а.
2. **Исторические readiness-аудиты в README.** Секция
   `## Production Readiness (Sprint 203 + Cycles 25-30)` занимала строки
   641–807 (167 строк) и содержала проценты готовности прошлых сессий
   (`62% / 70% / 78% / 82% / 94%`), разборы раундов аудита и ссылки на
   конкретные коммиты. Ничего из этого не пересчитывалось, но README читался
   как актуальный документ.

### Исправление

**1. Генератор `tools/generate_current_metrics.py` (новый).** Собирает метрики
из фактического состояния кода и перезаписывает блок между маркерами
`<!-- BEGIN/END GENERATED METRICS -->`:

| Метрика | Источник |
|---|---|
| HEAD | `git rev-parse HEAD` |
| Actions (runtime) | `ActionHandlerRegistry.list_actions()` **после** `create_app()` — до стартовых фаз реестр пуст (проверено: 0) |
| DSL-маршрутов | `RouteRegistry.list_routes()` |
| Протоколов | протокольные пакеты `src/backend/entrypoints/` (17) |
| Middleware | `len(app.user_middleware)` (37) |
| OpenAPI paths/schemas | `app.openapi()` (414 / 142) |
| Тестов собрано | `pytest --collect-only -q` (20679) |
| Порог покрытия | `[tool.coverage.report] fail_under` (70) |
| Layer baseline | вывод `tools/check_layers.py` |

Режимы `--write` (пересчёт) и `--check` (только проверка). Из сравнения
исключена строка-время генерации, иначе гейт срабатывал бы на каждом запуске.

**2. Блок «Текущие метрики»** добавлен в README; inline-число `109 actions`
заменено ссылкой на таблицу.

**3. Исторические аудиты вынесены** в
`docs/audit/README_PRODUCTION_READINESS_HISTORY.md` с преамбулой: это слепки
прошлых сессий, а не текущий факт. В README остался короткий указатель.
README: 807 → 652 строки.

**4. Таргеты `make/docs.mk`:** `docs-current-metrics` (пересчёт) и
`docs-current-metrics-check` (CI-гейт).

### Доказательство, что гейт ловит устаревание

Главный риск такой правки — «сгенерировал один раз и забыл», то есть возврат
проблемы через месяц. Проверено мутацией самого README:

| Состояние README | `make docs-current-metrics-check` |
|---|---|
| актуальный блок | `Метрики README актуальны.` **EXIT=0** |
| `Actions (runtime) | 999` (подмена) | `Сгенерированный блок метрик в README устарел.` + печать обеих версий, **EXIT=1** |

README после мутации восстановлен, повторная проверка — EXIT=0.

### Побочная находка

Таблица «Протоколы» в README перечисляет 13 протоколов, тогда как фактических
протокольных пакетов entrypoints — **17** (в таблице отсутствуют `asyncapi`,
`email`, `filewatcher`, `http3`, `mqtt`, `scheduler`). Счётчик в сгенерированном
блоке теперь считается из кода; саму таблицу не переписывал — это описание
HTTP-эндпоинтов, а не реестр модулей, и её актуализация требует продуктового
решения по каждому протоколу. Зафиксировано как **F-AK**.

---

## 9d. Три новых исправления (F-Z, F-AL, F-AM)

### F-Z (P1) — `release-gate.yml` падал всегда, по двум независимым причинам

**Доказательство (эмпирическое, не чтением).** Скрипт гейта извлечён и прогнан
на bash 5.2.21:

```
bash: REPO: не заданы границы переменной     # set -u, ${REPO} нигде не объявлен
SIM_EXIT=1                                    # падение на ПЕРВОЙ итерации, до агрегации
```

Вторая причина обнаружилась при сверке списка `REQUIRED` с фактическими
workflow-файлами: `"build-and-deploy"` — это **имя job'а** из
`docs-publish.yml`, а не workflow. Контейнерный pipeline живёт в `image.yml`.
Даже после починки `REPO` `gh api` вернул бы пустой `workflow_runs` →
`conclusion: missing` → гейт продолжал бы падать.

Контракт API подтверждён по документации: `workflow_id` — «The ID of the
workflow. You can also pass the workflow file name as a string»
(https://docs.github.com/en/rest/actions/workflow-runs). Поэтому
идентификаторы переведены на имена файлов (`lint.yml` … `image.yml`), а
`REPO: ${{ github.repository }}` добавлена в `env:` шага.

**Meta-гейт против регрессии.** `tools/checks/check_release_gate.py` проверяет
четыре класса: расширение workflow-файла, существование файла, триггер
`pull_request`, необъявленные `$VAR` под `set -u`. Подключён как
`make check-release-gate` и в composite `ci` (`make/pipelines.mk`).

Три независимые мутации пойманы раздельно:

| Мутация | Реакция гейта |
|---|---|
| удалить `REPO:` из `env:` | `REPO … unbound variable` → exit 1 |
| `image.yml` → `image-missing.yml` | `файла нет … conclusion 'missing'` → exit 1 |
| убрать `pull_request` из `stubs-drift.yml` | `не триггерится на pull_request` → exit 1 |

18 тестов `tests/unit/deploy/test_release_gate_workflow.py`; на дореформенном
`release-gate.yml` падают **7 из 18**.

*Собственная ошибка в гейте (исправлена):* первая версия искала `-u` как
подстроку в `set -euo pipefail` — это кластер коротких опций, `-u` не является
подстрокой `-euo`, и проверка молча пропускала все скрипты. Переписано на
посимвольный разбор; мутация `-eu → True` в параметризованных тестах поймана.

### F-AL (CRITICAL) — MCP-инструмент читал произвольные файлы ФС

Воспроизведено на живом рантайме тем же вызовом, что делает MCP-инструмент
`documents_to_markdown` (`tools_document.py:60`):

```
[LEAK] /etc/passwd:   engine=legacy size=3360   'root:x:0:0:root:/root:/bin/bash…'
[LEAK] /etc/hostname: engine=legacy size=11
```

Причина двойная: `AIFsFacade(capability_check=None)` отключает **единственный**
барьер `fs.read` (сам класс документирует `None` как «для unit-тестов»), а
ограничения по корню не было вовсе. Второй production-сайт
(`ai_safety_setup.py:63-64`) глотал ошибку в `capability_check = None` —
тот же fail-open.

Фикс: `allowed_read_roots` в `AIFsFacade` с проверкой **после** `resolve()`
(симлинки и `..` нейтрализуются), публичный `config_loader.repo_root()`, оба
production-сайта передают корень проекта. R-V15-4 сохранён: проект читается,
система — нет.

```
[DENIED ] '/etc/passwd'            путь вне allowed_read_roots (/home/user/dev/gd_reaudit)
[DENIED ] '../../../../etc/passwd' путь вне allowed_read_roots
[READ OK] 'README.md'              size=32345   <-- проект по-прежнему читается
```

9 тестов `tests/unit/core/ai/test_fs_facade_read_roots.py`, включая симлинк
наружу и «пустой список корней = deny-all». Регресс `core/ai` + `mcp`:
4 failed / 764 passed — все 4 идентичны базовым (`fastmcp` не установлен).

### F-AM (CRITICAL) — ORM-фильтр tenant не фильтровал DML и JOIN

Воспроизведено на **реальном** SQLAlchemy 2.0.52 + SQLite (не на mock), при
активном `TenantContext(tenant_id='tenant-a')` и строке чужого tenant в БД:

| Запрос | До фикса | Ожидалось |
|---|---|---|
| `update(Order).where(id=2)` | **1 строка** | 0 |
| `delete(Order).where(id=2)` | **1 строка** | 0 |
| `select(Order, User.id).join(User, …)` | **[1, 2]** | [1] |
| `select(Order)` | [1] | [1] |

Две независимые причины: `if not orm_execute_state.is_select: return` отбрасывал
DML целиком; сущность искалась через `stmt.froms[i].entity_namespace`, а у
`_ORMJoin` это коллекция колонок, а не класс, поэтому `_is_tenant_aware()`
давал `False` и фильтр молча не добавлялся.

Фикс: резолвер `_tenant_aware_entities()` — `column_descriptions` (SELECT и
JOIN) → `entity_description` (DML, у него нет ни `froms`, ни `column_descriptions`)
→ `froms` (агрегаты). Фильтруются **все** tenant-aware сущности запроса, иначе
join двух tenant-aware таблиц оставлял вторую неограниченной. Устаревший
`Select.froms` заменён на `get_final_froms()`.

Контроль после фикса — 8/8 сценариев, включая «свой tenant по-прежнему
редактируется и удаляется». Проверка сырым SQL подтверждает, что строки
`tenant-b` не изменены и не удалены (изоляция, а не сокрытие).

**Уточнение к формулировке агента (важно для честности реестра).** Утверждение
«`select(Order)` не фильтруется» **не воспроизводится**: `froms[0]` — это
`Table`, чей `entity_namespace` проксирует `tenant_id`, фильтр добавляется.
Утечка ограничивалась join-формами. Дефект реален, но уже, чем заявлено.

10 тестов `tests/unit/core/tenancy/test_tenant_filter_orm_dml.py` на реальном
ORM; на HEAD-коде падают 3. Регресс кластера
`core/tenancy + infrastructure/database + core/security + services/workflows`:
**11 failed / 737 passed** — 11 падений идентичны базовым (order-dependent
загрязнение в `test_authorization_gateway*`, воспроизводится и на HEAD-коде).

**Осознанное изменение контракта.** `tests/unit/infrastructure/database/
test_tenant_filter.py::test_filter_by_tenant_skips_non_select` кодировал
старое поведение «DML не фильтровать». Тест переписан как
`test_filter_by_tenant_handles_dml`; причина смены контракта зафиксирована в
его docstring. Это изменение публичного поведения — требует ADR от владельца.

*Собственная ошибка в тесте (исправлена):* первый вариант патчил
`get_tenant_id`, но вызывал listener **вне** `with`-блока — реальная функция
возвращала пустой tenant, и фильтр корректно не применялся. Тест был бы
vacuous ровно так же, как старый.

---

## 9e. Findings роя (4 агента, 33 находки)

### Workflow / Temporal / Scheduler (агент)

| ID | Sev | Суть | Статус |
|---|---|---|---|
| F-AT1 | **P0** | `factory.py:109-117` — prod-профиль молча деградирует на `PgRunnerWorkflowBackend` при отсутствии SDK, лог уровня `warning` | открыт |
| F-AT2 | **P0** | `config/features/infrastructure.py:430` — `workflow_use_temporal` по умолчанию `False`; worker не стартует ни в одном профиле | открыт |
| F-AT3 | P1 | `temporal_worker_runtime.py:281` + `lifecycle.py:537` — `_build_temporal_activities()` возвращает `[]`, REQUIRED-операция при этом вакуумна (5 точек `return` после warning) | открыт |
| F-AT4 | P1 | `factory.py:84` — `except ImportError` не ловит `RuntimeError`, бросаемый внутри `connect()`; заявленный graceful fallback мёртв | открыт |
| F-AT5 | P1 | `tools/checks/temporal_replay_gate.py` написан, но не подключён ни к одному make/CI-таргету (0 совпадений) | открыт |
| F-AT6–10 | P1–P2 | fail-open Redis-lock (дублирование cron), scheduler не стартует без Redis, `versioning.patched()` → `False`, health-check читает несуществующий `settings.workflow.host` | открыт |

Проверено и **PASS**: классического «async вызов без await» в scheduler/workflow
нет (AST-скан 449 кандидатов, все обёрнуты в `TaskRegistry.create_task`);
leader election симметричен; `set_app_ref` вызывается.

### RPA / Playwright (агент)

| ID | Sev | Суть | Статус |
|---|---|---|---|
| F-AP1 | **CRITICAL** | SSRF: ни на одной из 11 точек `page.goto` нет валидации URL; 9/9 payload'ов (`169.254.169.254`, `file://`, `127.0.0.1`, `data:`, `chrome://`) дошли до браузера; достижимо из тела запроса | открыт |
| F-AP2 | HIGH | `check_waf_coverage.py` матчит только `httpx` → `page.goto` невидим; гейт отдаёт «0 violations» при реальной дыре | открыт |
| F-AP3 | HIGH | `playwright`/`patchright` отсутствуют в venv (только optional extras) → **все** browser-пункты DoD = ENV_BLOCKED, не PASS | ENV_BLOCKED |
| F-AP4–11 | HIGH–LOW | утечка driver-процесса при падении `launch()`, семафор не освобождается при ошибке `new_page()`, пул не подключён в DI, обход workspace для screenshot, единственный real-browser тест `--ignore`нут, отсутствие маскирования | открыт |

Уточнение: `_validate_url` в `scraping.py` существует и блокирует 7 сетевых
payload'ов, но пропускает `file://`, `data:`, `chrome://` и decimal-IP — при
повторном использовании его нужно дополнить allowlist схем.

### AI / RAG / MCP (агент)

| ID | Sev | Суть | Статус |
|---|---|---|---|
| F-AQ1 | **CRITICAL** | MCP читает произвольные файлы (`capability_check=None`, без root-allowlist) | **FIXED = F-AL** |
| F-AQ2 | HIGH | `output_mixin.py:111` — output-санитайзер fail-open в отличие от input; `pii_detected=False` при утечке ПДн | открыт |
| F-AQ3 | HIGH | `RagInvalidationBus.subscribe()` не вызывается нигде → `publish → 0 recipients`; кэш после ingest не инвалидируется (L1 TTL 3600 s) | открыт |
| F-AQ4–8 | MED–LOW | тихая деградация кэша неотличима от честного miss, `core.vector_store.memory` не существует, workflow-хуки пропускают всё вне префиксов `banking.*`/`rpa.*`, `guardrails` — no-op | открыт |

Проверено и **PASS** (с доказательством): AI Safety на запись (overwrite,
traversal, symlink — 4/4 заблокированы), sandbox (прямого `subprocess` в
`core/ai` нет), MCP ASGI auth-guard fail-closed, MCP action-authz по capability,
секреты в audit-события не пишутся, LLM-деградация явная (`GatewayUnavailable`).

### Services / Repositories / Tenancy (агент)

| ID | Sev | Суть | Статус |
|---|---|---|---|
| F-AS1 | **CRITICAL** | split-brain двух ContextVar: `core.tenancy._current` в production **никогда не заполняется**; 9 потребителей (ORM-фильтр, RLS) читают пустое значение | открыт — корень для F-AS2/3 |
| F-AS2 | **CRITICAL** | JOIN-запросы не фильтруются | **FIXED = F-AM** |
| F-AS3 | **CRITICAL** | UPDATE/DELETE не фильтруются | **FIXED = F-AM** |
| F-AS4 | HIGH | `api_key.py:111` хардкодит `tenant_id="default"`; `api_key` (order 110) выполняется **внутри** `tenant` (order 300) → инвариант «auth tenant авторитетен» не действует для API-key | открыт |
| F-AS5–6 | HIGH | `TenantResourceIsolationMiddleware` — production no-op (0 checker'ов); `require_object_ownership` — 0 production-caller'ов и fail-open по умолчанию | открыт |
| F-AS7 | HIGH | `hitl_service.get()` при пустом tenant снимает фильтр (`tenant_id=None`) — единственная исполняемая ветка из-за F-AS1 | открыт |
| F-AS8–14 | P1–P2 | 3 из 5 GDPR-адаптеров fail-open на пустом tenant, нет валидации формата tenant-id + Redis glob-инъекция, пустой `X-Tenant-ID` → общий `"default"`, сторы без tenant-скоупа (outbox/watermark/express/mongo), DSL `db_update`/`db_delete` без tenant-предиката | открыт |
| F-AN | P1 | Существующие тесты tenant-фильтра **вакуумны**: `MagicMock` вместо `ORMExecuteState`, listener не вызывается; `48 passed` не доказывают работоспособность | частично закрыто тестами F-AM |

Агент также **опроверг** две переданные ему гипотезы: утечки tenant между
запросами через contextvars на keep-alive соединении нет (runtime под uvicorn,
4 запроса + фоновые задачи), и указанный в задании путь
`core/domain/repositories` не существует.

---

## 9f. DoD-последовательность: полный замер на текущем HEAD

Целиком повторена последовательность из goal-контракта, канонический
интерпретатор 3.14.0, HEAD `3b509542e`. Каждая строка — фактический exit code,
а не пересказ.

| Команда | Exit | Результат | Статус |
|---|---:|---|---|
| `python -m compileall -q src` | 0 | OK | **PASS** |
| `python -m compileall -q extensions` | 0 | OK | **PASS** |
| `python -m compileall -q plugins` | 0 | OK | **PASS** |
| `python -m compileall -q testkit` | 0 | OK | **PASS** |
| `python -m compileall -q tools` | 0 | OK | **PASS** |
| `python tools/check_layers.py` | 0 | `Нарушений: 0 новых (файлов: 2549; baseline: 22 legacy)` | **PASS** (legacy-allowlist не уменьшен, но и не вырос) |
| `pytest --collect-only -q` | 0 | `20717 tests collected in 13.57s` | **PASS** — collection полностью разблокирован (было EXIT=2) |
| `pytest -m unit` | 1 | `135 failed, 19696 passed, 194 skipped, 48 xfailed, 46 xpassed, 7 errors, 433.71s` | **FAIL** — 52 из 135 = ENV (PG/torch CUDA/streamlit/temporalio), остальное требует разбора |
| `pytest -m integration` | — | 261 тест отобран | см. §9f-bis |
| `pytest -m e2e` | — | 8 тестов отобрано | см. §9f-bis |
| `pytest -m property` | 5 | `no tests collected (20717 deselected)` | **FAIL — маркер мёртв** (F-X) |
| `pytest -m security` | 5 | `no tests collected (20717 deselected)` | **FAIL — маркер мёртв** (F-X) |
| `ruff check .` | 1 | `Found 34 errors` (18 `tools/`, 13 `extensions/`, 3 `ops/`) | **FAIL** — пре-существующие; среди 34 **ноль** файлов этой сессии |
| `ruff format --check .` | 1 | `292 files would be reformatted, 5914 files already formatted` | **FAIL** — пре-существующие |

### F-AO (P1) — repo-wide линт красный, и это не в `src/`

| Поле | Значение |
|---|---|
| **Severity** | P1 |
| **file:line** | `tools/**` (18), `extensions/**` (13), `ops/**` (3) |
| **Reproduction** | `ruff check .` → `Found 34 errors`, exit 1 |
| **Expected** | exit 0 (DoD требует «ruff check .») |
| **Actual** | exit 1; `ruff format --check .` — 292 файла |
| **Impact** | goal-последовательность не воспроизводится «с нуля»; `make lint` не ловит эти каталоги, поэтому деградация не видна в CI. Уточнение к F-AC: агент оценивал в 295 нарушений, фактическое число — **34** (оценка завышена) |
| **Fix** | 23 из 34 авто-фиксятся `ruff check --fix`; остальные 11 требуют ручного разбора. Формат: распространить ruff-конфиг на `tools`/`extensions`/`ops` |
| **Regression test** | `ruff check .` в composite `ci` вместо `make lint` (warn-only) |
| **Commit SHA** | не закоммичено |

**Проверка, что это не моя регрессия:** пересечение 34 ошибок с 33 файлами,
изменёнными в этой сессии, — **пусто**. Все мои файлы проходят
`ruff check` и `ruff format --check` чисто.

### F-X (подтверждено повторно) — маркеры `property` и `security` мертвы

`pytest -m property` и `pytest -m security` возвращают **exit 5** (код «ничего не
выбрано»), а не 0. Признаки, по которым маркер считается мёртвым, выглядят
легитимно, поэтому дефект легко пропустить: маркер зарегистрирован в
конфигурации, но ни один тест его не несёт. Следствие — два обязательных пункта
goal-последовательности физически не могут быть выполнены, и «зелёный» их
статус был бы ложью.

## 9f-bis. Реальные прогоны `integration` и `e2e` (не только collect)

### `pytest -m e2e` → **PASS**

```
8 passed, 20 skipped, 20709 deselected, 11 warnings in 15.81s
PYTEST_E2E_EXIT=0
```

Пропуски честные и объяснены окружением, а не «пройдено мимо»: `temporalio`
(7 тестов), Presidio ML-стек по CUDA-причине (3), `moto` (1), secrets facade
не реализован (23 в одном модуле), демо saga удалён (1). Guard на Presidio,
написанный в F-W, отработал и сообщил `SKIPPED, не PASS` — ровно как задумано.

### `pytest -m integration` → **FAIL**

```
17 failed, 228 passed, 35 skipped, 20456 deselected, 58 warnings, 1 error in 172.07s
PYTEST_INTEGRATION_EXIT=1
```

**Моя ошибка в измерении, исправлена:** первый прогон печатал
`INTEGRATION_EXIT=0`, потому что `$?` после пайпа `pytest | tail` — это exit
кода `tail`, а не pytest. Это в точности та ловушка, которую DoD запрещает
(«Exit 0 ≠ PASS»). Перезапущено с явным захватом кода; честный результат —
**exit 1**.

**Классификация 18 падений (17 FAILED + 1 ERROR):**

| Причина | Кол-во | Детали |
|---|---:|---|
| **ENV** — CUDA `libcudart` / `libnvrtc` | 7 | `OSError: libcudart.so.13`, `ValueError: libnvrtc.so.*[0-9] not found` (Presidio/torch) |
| **ENV** — PostgreSQL `InvalidPasswordError` | 4 | `password authentication failed for user "test_user"` (обёрнуто в `DatabaseError`) |
| **ENV** — `No module named 'uuid_utils'` | 3 | `ImportError: module 'langchain_core.callbacks.manager' not found` — отсутствует транзитивная зависимость |
| **КОД** | 2 | `test_mcp_tool_authz`: ожидалось `not_in_allowlist_or_public_ns`, получено `capability_denied:mcp.gateway.invoke.credit` |
| **КОД** | 1 | `test_dsl2_legacy_aliases_wired::test_all_16_legacy_aliases_registered` |
| **КОД** | 1 | `test_s19_k3_w2_composition`: `TypeError: FeatureMixin.feature_flag() got an unexpected keyword argument 'flag'` |

Итого: **14 из 18 — окружение**, **4 из 18 — код**.

### F-AR (P1) · DSL-шаг `feature_flag:` не совместим с каноническим миксином

| Поле | Значение |
|---|---|
| **Severity** | P1 (бьёт по работающему demo-роуту) |
| **file:line** | `src/backend/dsl/yaml_loader/build.py:135`; `dsl/builders/base/feature_mixin.py:46`; `routes/composition_demo/main.dsl.yaml:15` |
| **Reproduction** | `pytest -m integration tests/integration/test_s19_k3_w2_composition.py -q` |
| **Expected** | YAML-шаг `feature_flag:` маппится на `FeatureMixin.feature_flag()` |
| **Actual** | `TypeError: FeatureMixin.feature_flag() got an unexpected keyword argument 'flag'` → обёрнуто в `ValueError: Invalid params for 'feature_flag'` |
| **Impact** | `composition_demo` не грузится при включённом флаге — то есть декларативный путь DSL для feature-flag сломан |
| **Fix** | схемы несовместимы полностью, а не по одному ключу. YAML-шаг передаёт **4** ключа (`flag`, `default`, `stop_on_disabled`, `output_field`), а `FeatureMixin.feature_flag(self, name: str)` принимает **1 позиционный** аргумент `name` (`feature_mixin.py:46-49`). Ближайший по имени `feature_flag_branch(flag, processors)` требует ещё и `processors`. Нужен выбор владельца: реализовать в миксине метод с этими 4 ключами либо сократить YAML-схему до совместимого `name` |
| **Regression test** | существующий `test_composition_demo_dsl_loads_with_flag_on` станет зелёным |
| **Commit SHA** | не закоммичено |

**Точная причина расхождения (прочитано, а не предположено):**

```yaml
# routes/composition_demo/main.dsl.yaml:15-19
- feature_flag:
    flag: demo_routes_enabled
    default: true
    stop_on_disabled: false
    output_field: demo_active
```

```python
# src/backend/dsl/builders/base/feature_mixin.py:46-49
def feature_flag(self, name: str) -> Self:
    self._feature_flag = name
    return self
```

`yaml_loader/build.py:135` вызывает `method(**params)` — то есть передаёт
`flag=`, `default=`, `stop_on_disabled=`, `output_field=` в метод, который
принимает только позиционный `name`. Пересечения имён **нет ни одного**.

Эта находка **связана с §C2 dead-code**: `feature_flag_check.py` (124 LOC)
признан DEAD именно потому, что YAML-шаг `feature_flag:` обрабатывается не этим
классом, а `FeatureMixin`. Теперь видно, что и второй путь не работает — то есть
шаг `feature_flag:` не имеет ни одной рабочей реализации. Это меняет решение с
«удалить мёртвый класс» на «починить или явно объявить шаг неподдерживаемым».

### F-AS15 (P2) · Расхождение MCP-authz между интеграционным и юнитовым ожиданием

`tests/integration/test_mcp_tool_authz.py` ожидает
`not_in_allowlist_or_public_ns`, фактический код отдаёт
`capability_denied:mcp.gateway.invoke.credit`. Это **не** регрессия волны —
юнитовые тесты MCP проходят, а расхождение касается порядка проверок
(namespace-allowlist против capability-gate). Требуется решение владельца:
какой слой должен срабатывать первым. До решения статус — расхождение
контрактов, не подтверждённый дефект.

---

## 9g. Обязательные артефакты DoD — все 9 на месте

| # | Артефакт | Размер | Состояние |
|---|---|---:|---|
| 1 | `file_inventory.csv` | 1 725 667 B | OK |
| 2 | `import_graph.json` | 978 052 B | OK |
| 3 | `middleware_actual_order.json` | 19 594 B | OK — 37/37 middleware |
| 4 | `lifecycle_graph.json` | 8 185 B | OK — 19 startup-фаз |
| 5 | `dead_code_evidence.md` | **создан в этой волне** | 9 кандидатов, 7 каналов проверки |
| 6 | `library_consolidation.md` | **создан в этой волне** | 6 библиотек, из них 2 работают |
| 7 | `curl_results.json` | 13 834 B | OK — 27 сценариев |
| 8 | `browser_results.md` | **создан в этой волне** | ENV_BLOCKED с доказательством |
| 9 | `final_report.md` | 99 290 B | этот документ |

### Два ложных утверждения предыдущих отчётов, опровергнутых перепроверкой

1. **Dead code «~1110 LOC».** `core/services/base_external_api.py` **не
   существует** — сравнивать sha256 нечего; `saga_lra_processor` — 3-строчный
   шим, а не пакет на 864 LOC. Подтверждённый безопасный объём — **4 LOC**.
2. **«Шесть библиотек подключены».** Реально работают **две**
   (`testcontainers`, `faststream`). `schemathesis` подключён, но runner падает
   с `No such option: --exitfirst`; CI-job — с `Extra 'dev' is not defined`.

Ложные утверждения нашлись и в документации репозитория:
`docs/roadmap/PROD_READINESS_GAPS.md:143`, `docs/audit/cycle-1/domain-A3-Services.md:527`,
`pyproject.toml:484`.

### Три дефекта, дающие «зелёный» CI при неработающей проверке

| Дефект | Механизм зелёного CI |
|---|---|
| `tools/api_fuzz_runner.py:145` — `--exitfirst` не существует в schemathesis 4.x | runner завершается exit 2 до выполнения кейсов; тесты мокают вывод |
| `.github/workflows/api-fuzz.yml:43` — `uv sync --extra dev` (`dev` — group, не extra) | job падает на установке, но `continue-on-error: true` |
| `api-fuzz` не входит в `make ci` / `make pr` | гейт декоративен: `pipelines.mk:22-34` его не перечисляет |

## 9h. Классификация 135 падений `-m unit` и главный ложный сигнал

Полный разбор базового прогона (`/tmp/unit_clean.log`, 135 FAILED):

| Категория | Кол-во | Метод отделения |
|---|---:|---|
| **ENV** | 60 | наличие маркеров `InvalidPasswordError` / `libcudart` / `libnvrtc` / `streamlit.emojis` / `temporalio` / `fastmcp` в теле падения |
| **КОД** | 65 | падение с `E`-строкой без ENV-маркера |
| **без `E`-строки** | 3 | разбор вручную |

### F-AN2 (P1) · 18 падений `Unknown action(s) in pipeline` — НЕ дефекты продукта

Это **самый крупный** кластер «КОД» (18 из 65) и он оказался ложным сигналом.
Доказано изоляцией:

```
$ pytest tests/unit/dsl/blueprints/test_python_blueprints_focused.py -q
29 passed in 0.65s                     <-- файл целиком зелёный
```

При этом в общем прогоне тот же файл даёт 17 падений. Механизм:

`dsl/builders/base/validation_mixin.py:66-84` сверяет имена из
`dispatch_action` с глобальным `action_handler_registry`:

```python
available = set(action_handler_registry.list_actions())
...
if not available:
    return            # <-- при пустом реестре валидация молчит
...
unknown = [name for name in action_names if name not in available]
```

В чистом контексте реестр пуст (`0 actions` — проверено), и валидация
**не срабатывает**. В общем прогоне другие тесты частично наполняют глобальный
реестр, после чего `available` становится непустым, но не содержит
`process_file` / `process` / `publish` — и DX-проверка падает на легитимных
тестах.

| Поле | Значение |
|---|---|
| **Severity** | P1 (ложные падения маскируют реальные регрессии в 18 тестах) |
| **file:line** | `src/backend/dsl/builders/base/validation_mixin.py:66-84`; тесты `tests/unit/dsl/blueprints/test_python_blueprints_focused.py:164` и ещё 4 файла |
| **Reproduction** | `pytest tests/unit/dsl/blueprints/test_python_blueprints_focused.py -q` (проходит) vs полный `pytest -m unit` (17 падений в этом файле) |
| **Expected** | результат теста не зависит от порядка выполнения |
| **Actual** | зависит от состояния глобального реестра, которое меняют другие тесты |
| **Impact** | 18 ложных падений; реальные дефекты в том же прогоне теряются в шуме. Тот же класс, что и 11 order-dependent падений `test_authorization_gateway*`, найденных ранее |
| **Fix** | autouse-фикстура сброса/изоляции `action_handler_registry` между тестами; отдельно — сделать поведение `_validate_action_names` детерминированным (валидировать только при непустом **и зарегистрированном** наборе, либо всегда требовать полный реестр) |
| **Regression test** | `test_validation_is_order_independent` — два прогона в разном порядке дают одинаковый результат |
| **Commit SHA** | не закоммичено |

### Поллитер F-AN2 найден: `tests/unit/cache/test_admin_cache_dsl_actions.py`

| Проверка | Результат |
|---|---|
| `test_python_blueprints_focused.py` в одиночку | `29 passed` |
| `+ test_lazy_action_registry_proxies.py` | `37 passed` |
| `+ test_scheduled_reports.py` | `37 passed` |
| **`+ test_admin_cache_dsl_actions.py`** | **`18 failed, 11 passed, 7 errors`** |

```python
# tests/unit/cache/test_admin_cache_dsl_actions.py:22-29
def _register_admin_actions() -> None:
    from src.backend.dsl.commands.action_registry import action_handler_registry
    from src.backend.dsl.commands.setup import register_action_handlers
    register_action_handlers()          # регистрирует ВСЕ actions в глобальный реестр
    action_handler_registry.clear()     # и сразу чистит его
```

Поллитер выполняет **процессно-глобальный цикл «регистрация → очистка»** без
изоляции. После него глобальный `action_handler_registry` не находится в
well-defined состоянии: `available` для `_validate_action_names` становится
непустым, но не содержит `process_file` / `process` / `publish`, и DX-проверка
начинает блокировать легитимные роуты в **другом** файле тестов.

Побочно: 7 `errors` в этом же прогоне — `OSError: libcudart.so.13` и
`ValueError: libnvrtc.so.*[0-9] not found` на этапе setup (ENV, Presidio/torch),
то есть этот файл даёт одновременно и ENV-ошибки, и загрязнение глобального
состояния.

**Продуктовое наблюдение внутри этой находки.** Поведение
`_validate_action_names` **недетерминировано по построению**: при пустом реестре
проверка выключается, при частично заполненном — включается. То есть одна и та же
декларация роута проходит валидацию в одном контексте и падает в другом. Это
не только тестовая проблема: DX-фича, задуманная как «ловим опечатки в именах
action», может как промолчать, так и заблокировать корректный роут в зависимости
от того, что успели зарегистрировать другие компоненты.

### Прочие кластеры «КОД» (объём оценён, глубокий разбор не завершён)

По убыванию числа падений: `hvac.__spec__` (3) и
`ModuleNotFoundError: No module named 'hvac.exceptions'; 'hvac' is not a package`
(1) — вероятно окружение, требует проверки; `assert [] == [1, 2, 3]` (2) и
`assert [] == [1]` (1) — расследовать; `MagicMock object can't be awaited` (2) и
`Expected _request to have been awaited once. Awaited 0 times` (1) — вероятно
async-дефекты в тестах или в коде; `assert 'completed_with_errors' == 'completed'`
(2) — расхождение контракта статусов; одиночные расхождения
(`WebDavProcessor.__init__() got an unexpected keyword argument 'auth'`,
`Canonical .../dist/sbom/sbom.cdx.json не найден`, `config.services cold import
should be <50ms; got 1.216s`) — каждый требует отдельного разбора и **не
классифицирован как дефект**.

Это перечисление намеренно не названо «найденными дефектами»: по правилам аудита
ненулевой exit без установленной причины — это `NOT_VERIFIED`, а не finding.

## 9i. F-AN3 · 11 order-зависимых падений: поллитер найден бисекцией

Отдельный разбор тех же 11 падений, что наблюдались в кластере
`core/tenancy + infrastructure/database + core/security`.

### Моя ошибка, исправленная контрольным прогоном

Сначала я предположил, что 11 падений ввёл **мой** новый файл
`test_tenant_filter_orm_dml.py`: при `core/security + core/tenancy` с ним
получалось 11 падений, без него — 0. Дальнейший бисект это опроверг:

```
# core/security + core/tenancy (2 каталога)
С моим файлом:        522 passed, 0 failed
Без моего файла:      512 passed, 0 failed      <-- падений нет в обоих случаях

# core/tenancy + infrastructure/database + core/security (3 каталога)
С моим файлом:        11 failed, 629 passed
БЕЗ моего файла:     11 failed, 619 passed      <-- падает и без него
```

Вывод: мой файл **не причастен**. Первоначальный вывод был поспешным —
он строился на одной паре каталогов, а не на решающем контроле.

### Бисекция до конкретного файла

```
tests/unit/core/tenancy/test_feature_flag_scope.py + authz  →  6 failed, 14 passed
tests/unit/infrastructure/database/test_tenant_filter.py + authz  →  17 passed
tests/unit/core/tenancy/test_quotas.py + authz  →  13 passed
tests/unit/core/security + tests/unit/core/tenancy  →  522 passed
```

**Поллитер — один файл `tests/unit/core/tenancy/test_feature_flag_scope.py`.**
**Жертва — `test_authorization_gateway.py` (6) + `test_authorization_gateway_steps.py` (5) = 11.**

### Симптом и механизм

```
E  AssertionError: assert ['feature_flag'] == ['capability_gateway']
E    At index 0 diff: 'feature_flag' != 'capability_gateway'
E  Right contains one more item: 'my_policy'
```

Жертва проверяет `decision.reasons[*].source` и ожидает цепочку
`capability_gateway` → `my_policy`. Фактически приходит `feature_flag` —
то есть шлюз ушёл в ветку «выключен», а не в цепочку проверок:

```python
# src/backend/core/security/authorization_gateway/__init__.py:154
source="feature_flag",
```

Флаг шлюз читает **в момент вызова**, через сервис:

```python
# src/backend/core/security/authorization_gateway/__init__.py:413
from src.backend.core.feature_flags import get_feature_flag_service
return get_feature_flag_service().is_enabled("authz_gateway_enabled")
```

а жертва патчит **объект, импортированный на этапе import**:

```python
# tests/unit/core/security/test_authorization_gateway.py:20, 35-38
from src.backend.core.config.features import feature_flags
...
@pytest.fixture(autouse=True)
def _enable_gateway(monkeypatch):
    monkeypatch.setattr(feature_flags, "authz_gateway_enabled", True)
```

**Это два разных пути разрешения одного флага.** Тест патчит атрибут на
объекте, привязанном именем при импорте; шлюз получает значение через
`get_feature_flag_service()` во время вызова. Поллитер подменяет объект
`feature_flags` в модуле на заглушку, у которой нет
`authz_gateway_enabled`, — и пути расходятся.

| Поле | Значение |
|---|---|
| **Severity** | P1 (11 ложных падений маскируют реальные регрессии; требует запуска `-n auto` в CI) |
| **file:line** | поллитер `tests/unit/core/tenancy/test_feature_flag_scope.py:62-81`; жертвы `tests/unit/core/security/test_authorization_gateway.py`, `test_authorization_gateway_steps.py`; механизм `src/backend/core/security/authorization_gateway/__init__.py:154,413` |
| **Reproduction** | `pytest tests/unit/core/tenancy/test_feature_flag_scope.py tests/unit/core/security/test_authorization_gateway.py -q` |
| **Expected** | 20 passed независимо от порядка |
| **Actual** | 6 failed при порядке «поллитер → жертва»; 20 passed при обратном порядке |
| **Impact** | 11 ложных падений в общем прогоне; ложный сигнал о состоянии authorization-шлюза |
| **Fix** | привести поллитера к изоляции: не подменять глобальный `feature_flags` синглтон, а передавать stub через явный параметр/внедрение; либо жертве — патчить тот же объект, который читает `get_feature_flag_service()` |
| **Regression test** | `test_order_independent` — прогон в обоих порядках обязан давать одинаковый результат |
| **Commit SHA** | не закоммичено |

### Топология прогона меняет набор жертв (ключевое уточнение)

Один и тот же кластер, два способа запуска, **разные падающие тесты**:

```
# последовательно (один процесс, все тесты делят глобальное состояние)
$ pytest tests/unit/core/tenancy tests/unit/infrastructure/database \
         tests/unit/core/security tests/unit/services/workflows -q -p no:randomly
11 failed, 737 passed     <-- падают test_authorization_gateway*

# параллельно (xdist, каждый воркер — свой процесс)
$ ... -n 2
12 failed, 736 passed     <-- падает ДРУГОЙ тест:
                                  test_hitl_tenant_enforcement.py::
                                  TestHitlTenantEnforcement::
                                  test_get_blocks_cross_tenant_access
```

HITL-тест проверен отдельно: **в одиночку проходит** (`1 passed`), весь файл —
`5 passed`, в последовательном кластере — 0 его падений.

**Вывод: набор жертв не просто «зависел от порядка», он недетерминирован и
меняется вместе с топологией прогона.** Это объясняет расхождение с базовым
замером: базовый `-m unit` шёл под xdist (`[gw0]` в логе) и authz-падений там
**не было** вовсе (`grep -c "^FAILED tests/unit/core/security/test_authorization_gateway" → 0`),
тогда как `Unknown action(s) in pipeline` присутствует (38 упоминаний).

Практическое следствие для CI: **падение `pytest -m unit` нельзя интерпретировать
как сигнал о регрессии**, пока существуют глобальные синглтоны без сброса.
Ложные падения и настоящие дефекты неразделимы по exit code.

### Общий вывод по трём order-зависимым классам

Это **три разных** поллитера с одним признаком — глобальное изменяемое
состояние, разделенное между тестами:

| Finding | Поллитер | Жертва | Падений |
|---|---|---|---:|
| F-AN2 | любой тест, регистрирующий actions | 5 файлов `dsl/blueprints/*` | 18 |
| F-AN3 | `core/tenancy/test_feature_flag_scope.py` | `core/security/test_authorization_gateway*` | 11 |
| F-AN (ранее) | — | `test_authorization_gateway*` в кластере | (входит в 11) |

Все три лечатся autouse-фикстурами сброса глобальных синглтонов
(`feature_flags`, `action_handler_registry`, реестр шагов DSL), а не
правкой конкретных тестов. Пока этого нет, падение `-m unit` в CI
**нельзя** трактовать как сигнал о регрессиях без ручной изоляции каждого
файла.

## 9j. F-AN4 · Локальный прогон и CI используют разную топологию xdist

Обнаружено при попытке получить эталонный замер `-m unit` после 9 волн правок.

| Поле | Значение |
|---|---|
| **Severity** | P1 (сравнимость результатов локально и в CI нарушена; плюс риск зависания CI-раннера) |
| **file:line** | `Makefile:43-55` (`UNIT_TEST_JOBS ?= 2` + предупреждение про OOM); `.github/workflows/test.yml:51-56` (`-n auto`); `make/docs.mk:39,48` (`-n auto`); `pyproject.toml:1190` (`addopts` **без** `-n`) |
| **Reproduction** | сравнить `grep -n "UNIT_TEST_JOBS" Makefile` и `grep -n "n auto" .github/workflows/test.yml` |
| **Expected** | одинаковая топология прогона в локальной разработке и в CI |
| **Actual** | локально `make unit-tests` → 2 воркера; CI → `-n auto`; `addopts` не задаёт `-n`, поэтому «голый» `pytest -m unit` идёт **полностью последовательно** |
| **Impact** | (1) набор падений недетерминирован и различается между локальным и CI-запуском — прямое продолжение F-AN3; (2) CI использует конфигурацию, которую сам проект документирует как приводящую к OOM и **зависанию** на 99% |
| **Fix** | задать `UNIT_TEST_JOBS` через `-p xdist` переопределение в CI (например `-n 2`), либо вынести значение в переменную CI; продублировать предупреждение в workflow |
| **Regression test** | проверка, что `addopts`/CI/`Makefile` используют одно значение числа воркеров |
| **Commit SHA** | не закоммичено |

**Дословное предупреждение владельцев проекта** (`Makefile:43-48`), которое CI
игнорирует:

> ВАЖНО: не ставьте `-n auto`, не проверив запас RAM. Измерено 2026-09-29 на
> машине 15 ГБ / 4 ядра: `-n auto` (4 воркера) доводит прогон до 99%, после
> чего воркеры убиваются OOM-killer'ом (14/15 ГБ занято, 247 событий OOM в
> kern.log), становятся зомби, а xdist-контроллер **БЕСКОНЕЧНО ждёт мёртвый
> воркер**. Прогон не падает — он висит.

**Практическое следствие для этого аудита.** Команда
`pytest -m unit` без `-n` идёт последовательно в одном процессе — все тесты
делят глобальное состояние, и загрязнение проявляется максимально. Именно
поэтому мой последовательный прогон показал 11 order-зависимых падений, которых
нет в базовом xdist-замере. **Сравнивать эти два числа нельзя**; эталон —
одна и та же топология.

**Фактическое наблюдение:** попытка получить эталонный замер последовательно
(`pytest -m unit -q -p no:randomly`) не уложилась в 30-минутный лимит и была
прервана на 99% — при этом в частичном логе было **0 FAILED**, что
предварительно согласуется с отсутствием регрессий, но не является доказательством
до полного завершения.

## 9k. Независимый ре-аудит: МОЁ ЗАЯВЛЕНИЕ ОКАЗАЛОСЬ НЕПОЛНЫМ

Рой по контракту требует независимого финального reviewer. Reviewer работал
read-only, получил задачу **опровергнуть** мои 6 заявлений, и это дало самый
ценный результат всего аудита: **три моих FIXED-вывода оказались неполными.**

| Утверждение | Мой вердикт | Вердикт reviewer | Что оказалось |
|---|---|---|---|
| 1. Tenant spoofing закрыт | FIXED, подтверждён на HTTP | **ЧАСТИЧНО** | спуфинг жив для principal **без** `metadata['tenant_id']` — реальный API-key |
| 2. F-AL (чтение ФС) | FIXED, 9 тестов | **ПОДТВЕРЖДЕНО** | 13 векторов обхода отбиты; hardlink не эксплуатируем |
| 3. F-AM (ORM-фильтр) | FIXED, 12 тестов | **ЧАСТИЧНО** | `UNION` и `select-from-CTE` не фильтруются |
| 4. F-Z (release-gate) | FIXED, meta-гейт | **ПОДТВЕРЖДЕНО** | 10 из 10 мутаций пойманы; `make -n ci` подтверждает вхождение |
| 5. Fail-closed ASF | FIXED (5 точек) | **ЧАСТИЧНО** | тот же баг в двух других методах |
| 6. Lifecycle | FIXED | **ЧАСТИЧНО** | частично поднятая операция не откатывается; 7 из 11 операций без `stop` |

### N-1 (HIGH) — мой P0-фикс был неполон. Исправлено

До фикса (по коду, `tenant.py:208-210`):

```python
auth_tenant = _authenticated_tenant(scope)   # None, если tenant не заявлен
if auth_tenant:
    ... # проверка несовпадения с заголовком ...
    state["tenant_id"] = auth_tenant
elif "tenant_id" not in state:               # <-- FAIL-OPEN
    header_value = _get_header(scope, _TENANT_HEADER_BYTES)
    state["tenant_id"] = header_value if header_value else self._default
```

Реальный `_verify_api_key` (`auth_selector.py:117-131`) кладёт в metadata
**только** `key_id`, `key_hash`, `admin_roles` — **без `tenant_id`**. Значит
`_authenticated_tenant()` возвращает `None` при **успешной** аутентификации,
и управление уходит в `elif`, который доверяет заголовку. `AuthRequiredMiddleware`
по умолчанию принимает `API_KEY` (`auth_required.py:143-145`), глобальный ключ
сконфигурирован в окружении — то есть путь **достижим в проде** без всяких mock'ов.

Reviewer воспроизвёл end-to-end: реальный `X-API-Key` (principal `global`) +
`X-Tenant-ID: tenant-b` → **HTTP 200**, `state['tenant_id']='tenant-b'`, и то же
значение в `RequestContext`, которое DSL-движок читает **первым**
(`dsl/engine/execution_engine.py:26-40`).

**Исправление (Fail-closed).** Разделены два случая, которые мой прежний
помощник `_authenticated_tenant()` сливал в один `None`:

```python
elif _auth_present(scope):
    # аутентифицирован, но tenant не заявлен → заголовку НЕ доверяем
    if header_value and header_value != self._default:
        ... 403 tenant_mismatch (reason=tenant_not_asserted) ...
    state["tenant_id"] = self._default
```

Платформенная учётка не принадлежит ни одному tenant — она работает в `default`,
и заголовок её не расширяет. Это fail-closed по изоляции и при этом не ломает
легитимные service-to-service вызовы.

**Доказательство после фикса:**
```
sent statuses: [403, None]
state.tenant_id: None
WARNING tenant DENY path=/x principal_without_tenant requested=tenant-b reason=tenant_not_asserted
```
Мутация (возврат ветки `elif False`) → тест падает.

### N-3 (MEDIUM) — я закрыл один экземпляр бага, а не паттерн. Исправлено

Фикс «pre_llm-хуки выполняются на чистом пути» был применён **только** к
`validate_prompt`. `validate_command` (стр. 172) и
`validate_file_modification` (стр. 242) заканчивались `return
SecurityDecision(allowed=True)` **вообще без вызова `_run_hooks`** — deny-хук
workflow'а на безопасной по шаблону команде не выполнялся вовсе. Добавлена та же
ветка чистого пути в оба метода.

### N-4 (MEDIUM) — частично поднятая операция не откатывалась. Исправлено

`self._started.append(op)` выполнялся **после** успеха, поэтому операция,
упавшая после частичного подъёма ресурсов (в т.ч. по `TimeoutError`), в откат не
попадала и её `stop()` не вызывался. Введен отдельный трек `_attempted`
(предпринятые попытки старта) — откат идёт по нему, а `_started` сохраняет
прежнюю семантику «успешно поднято», чтобы обычный shutdown не начал дёргать
`stop()` у никогда не стартовавших операций.

**Побочный эффект, измеренный контролем:** в комбинации 4 каталогов падения
lifecycle-smoke **снизились с 10 до 7** — фикс не только безопасен, но и убрал
часть order-зависимых падений.

### N-2 (MEDIUM) — НЕ закрыто, зафиксировано как открытый пробел

`UNION` и `select-from-CTE` не фильтруются: `_tenant_aware_entities` для этих
форм возвращает `[]` (нет сущности в `column_descriptions`, `entity_description`
равен `None`, `get_final_froms()` пуст или отдаёт CTE). Cross-tenant чтение
остаётся. DML, JOIN, `aliased`, eager load, подзапросы и `EXISTS` фильтруются.
Тест `test_union_is_known_unfiltered_gap` **фиксирует текущее поведение
намеренно**: если он упадёт — пробел закрыт, и finding надо обновить.

### N-5..N-9 — открыты, не чинились

| ID | Sev | Суть |
|---|---|---|
| N-5 | MEDIUM | 7 из 11 продовых инфраструктурных операций **не имеют `stop`** (`start_mongo_client`, `warmup_connection_pools`, `start_pool_monitors`, …) → не откатываются никогда; legacy `ending_operations` их тоже не закрывает |
| N-6 | LOW | возвращаемое из `rollback()` значение игнорируется: ошибки `stop` при откате теряются, в отчёте остаётся `STARTED` при неудачной остановке |
| N-7 | LOW | `start_all()` не идемпотентен: повторный вызов дублирует `_started`, rollback останавливает операции дважды |
| N-8 | LOW | hardlink внутри репозитория читается (свойство path-based изоляции); не эксплуатируемо — нужен write в корень репо |
| N-9 | INFO | триггер `post_llm` из контракта `SecurityHook` недостижим — 0 вхождений в модуле |

### Рецензент также отметил (не finding, но риск для эксплуатации)

`2>/dev/null || echo '{"workflow_runs":[]}'` в `release-gate.yml` превращает
**любую** сетевую ошибку GitHub API в `conclusion: missing` → FAIL. Это
fail-closed, но означает, что транзиентный сбой API валит гейт релизного
контура. Требует продуктового решения (retry с backoff).

### Эталонный `-m unit` после 12 волн правок: регрессий 0

| | База (до волн) | После 12 волн |
|---|---|---|
| failed | 135 | **135** |
| passed | 19696 | **19770** (+74 новых теста) |
| skipped | 194 | 194 |
| xfailed | 48 | 48 |
| xpassed | 46 | 46 |
| errors | 7 | 7 |
| exit | 1 | 1 |

Число падений **не изменилось** ни на единицу при +74 проходящих тестах —
ни один из 12 фиксов не внёс регрессию. Методология обеих точек одинакова:
`-m unit -n auto` (см. F-AN4 про расхождение топологий).

## 10. Реестр findings (дополнение)


| ID | Sev | Область | Статус |
|---|---|---|---|
| F-D | **P0** | Tenant spoofing через `X-Tenant-ID` | **FIXED** (не закоммичено), 8 тестов, мутация поймана, регрессий 0 |
| F-A | P1 | Стадия authorization отсутствует в стеке middleware | открыт |
| F-B | P1 | `tenant_resource_isolation` выполняется раньше `tenant` | задокументировано, поведение не менялось |
| F-C | P2 | `request_body_cache` раньше `idempotency`; `cached_body` без читателей | открыт |
| F-E | P1 | Нет типа `LifecycleOperation` | **FIXED** — тип + runner + миграция 11 операций, 20 тестов, 3 мутации |
| F-F | P1 | Нет reverse-order rollback | **FIXED** — rollback в runner + `run_shutdown` при неудачном старте |
| F-G | P1 | `/health/ready` fail-open и он же в k8s-манифестах | открыт |
| F-H | P1 | Два readiness-эндпоинта, противоположные политики | открыт |
| F-I | P1 | AgentSecurityFramework hooks fail-open (регистрация и enforcement) | **FIXED** (5 точек), 9 тестов, 3 мутации, регрессий 0 |
| F-AH | P1 | Решение `pre_llm`/`post_tool` hook'а отбрасывалось; на «чистом» пути hooks не выполнялись вовсе | **FIXED** вместе с F-I |
| F-J | P1 | Shutdown не изолирован: падение op пропускает остальные | **FIXED** — изоляция в runner, регресс 0 |
| F-K | P2 | `PluginLoader.shutdown_all()` не идемпотентен | открыт |
| F-L | P2 | Degradation-заглушки HEALTHY вместо UNBOUND | **FIXED** — `FeatureState.UNBOUND`, `bound=False`, `error_rate: null`; 7 тестов, мутация поймана |
| F-M | P2 | Манифест worker'а ссылается на несуществующий `/probe/ready` | открыт |
| F-N | High | Гейт слоёв слеп к third-party; allowlist регрессировал 14→22 | открыт |
| F-O | High | 9 domain-моделей на SQLAlchemy | открыт |
| F-P | High | `core` тянет fastapi/starlette в рантайме | открыт |
| F-Q | Med | DSL тянет infrastructure напрямую | открыт |
| F-R | Med | Стадия compile декоративна, типизированного IR нет | открыт |
| F-S | — | `Exchange` чист | **PASS** |
| F-T | P1 | Гейт docstrings fail-open + неверный интерпретатор | открыт |
| F-U | P1 | `check-object-auth` fail-open в двух слоях | открыт |
| F-V | P2 | Гейты не покрывают `tests/` | открыт |
| F-W | **P0** | 3 collection-ошибки (`torch` CUDA → `ValueError`) блокировали **все** прогоны | **FIXED** (гвард, только тесты), мутация поймана, collection exit 2 → 0 |
| F-X | P1 | Маркеры `property`/`security` мёртвые: 0 тестов, `security` не зарегистрирован | открыт |
| F-Y | P1 | 2 теста портят tracked-файлы (`docs/adr/WIKI.md`, `.audit/quality-results.json`) | **FIXED** (побайтовый снимок + restore), sha не меняются |
| F-Z | P1 | `release-gate.yml` падает всегда: `REPO` не определён при `set -u` **и** `build-and-deploy` не существует | **FIXED** — обе причины + meta-гейт `check_release_gate.py` в `ci`; 18 тестов, 7 падают на HEAD |
| F-AL | **CRITICAL** | MCP-инструмент `documents_to_markdown` читал произвольные файлы ФС (`/etc/passwd`, 3360 B) | **FIXED** — `allowed_read_roots` + `resolve()`-проверка + `config_loader.repo_root()`; 9 тестов, регрессий 0 |
| F-AM | **CRITICAL** | ORM-фильтр tenant не фильтровал UPDATE/DELETE и JOIN-запросы | **FIXED** — резолвер `column_descriptions`/`entity_description`/`froms`; 12 тестов на реальном ORM; контракт DML изменён осознанно (нужен ADR) |
| F-AN | P1 | Тесты tenant-фильтра вакуумны (`MagicMock`, listener не вызывается) | частично закрыто реальными ORM-тестами F-AM; старый тест переписан |
| F-AT1 | **P0** | Prod-профиль Temporal молча деградирует на `PgRunner` при отсутствии SDK | открыт |
| F-AT2 | **P0** | `workflow_use_temporal` по умолчанию `False` — worker выключен во всех профилях | открыт |
| F-AT3 | P1 | `_build_temporal_activities()` → `[]`; REQUIRED-операция worker'а вакуумна | открыт |
| F-AT4 | P1 | `except ImportError` не ловит `RuntimeError` — заявленный fallback `dev_light` мёртв | открыт |
| F-AT5 | P1 | `temporal_replay_gate.py` не подключён ни к одному make/CI-таргету | открыт |
| F-AT6 | P1 | Redis-lock fail-open → дублирование cron на всех инстансах | открыт |
| F-AP1 | **CRITICAL** | SSRF: 11 точек `page.goto` без валидации URL; 9/9 payload'ов достигают браузера | открыт (латентный: пул не подключён, F-AP6) |
| F-AP2 | HIGH | `check_waf_coverage.py` слеп к `page.goto` → «0 violations» при реальной дыре | открыт |
| F-AP3 | HIGH | `playwright`/`patchright` не установлены → все browser-пункты DoD ENV_BLOCKED | ENV_BLOCKED |
| F-AP4 | HIGH | Утечка driver-процесса при падении `launch()` | открыт |
| F-AQ2 | HIGH | Output-санитайзер PII fail-open (асимметрия с input) | открыт |
| F-AQ3 | HIGH | `RagInvalidationBus.subscribe()` не вызывается — кэш не инвалидируется после ingest | открыт |
| F-AO | P1 | Repo-wide `ruff check .` → 34 ошибки (18 `tools`, 13 `extensions`, 3 `ops`); `ruff format --check .` → 292 файла. Пре-существующие, среди них 0 файлов этой сессии | открыт — уточнение к F-AC (агент оценивал в 295) |
| F-AR | P1 | YAML-шаг `feature_flag:` → `TypeError: FeatureMixin.feature_flag() got an unexpected keyword argument 'flag'`; `composition_demo` не грузится | открыт |
| F-AQ10 | P1 | OpenFeature: 0 импортов при 117 текстовых упоминаниях; 1265 LOC самописной замены | REJECT (замена функциональнее SDK в tenant-scope) |
| F-AQ11 | P1 | `api-fuzz.yml:43` — `uv sync --extra dev`, но `dev` — dependency-group → `UV_EXIT=2` | открыт, чинится одной строкой |
| F-AQ12 | P2 | 1566 LOC параллельного брокерного слоя в обход faststream (nats-py, aiokafka) | DEFER — нужен бенчмарк |
| F-AP10 | P1 | `api_fuzz_runner.py:145` — `--exitfirst` не существует в schemathesis 4.x → ни одного fuzz-кейса, отчёт не пишется | открыт, чинится одной строкой |
| F-AP11 | P1 | playwright/patchright отсутствуют; бинарники Chromium есть; единственный browser-тест исключён `--ignore` в `pyproject.toml:1190` | ENV_BLOCKED (см. `browser_results.md`) |
| F-AT11 | P2 | `pyproject.toml:484` утверждает «temporalio уже в base deps» — он в extras; 37 импортов и 7 тестов мертвы и в CI | открыт |
| F-AN3 | P1 | 11 order-зависимых падений; поллитер — `test_feature_flag_scope.py` (подменяет синглтон `feature_flags`), жертва — `test_authorization_gateway*`; шлюз читает флаг через `get_feature_flag_service()`, тест патчит объект из import-time | открыт — autouse-сброс синглтонов |
| F-AN2 | P1 | 18 падений `Unknown action(s) in pipeline` — **ложные**: файл проходит 29/29 в одиночку. `_validate_action_names` недетерминирована: при пустом реестре молчит, при частичном — блокирует легитимные роуты | открыт — требует изоляции глобального реестра |
| F-AS15 | P2 | `test_mcp_tool_authz` ожидает `not_in_allowlist_or_public_ns`, код отдаёт `capability_denied:…` | расхождение контрактов, не подтверждённый дефект |
| N-1 | **HIGH → FIXED** | Мой P0-фикс был неполон: `_verify_api_key` не кладёт `metadata['tenant_id']`, поэтому успешная аутентификация без tenant уходила в fail-open ветку и доверяла `X-Tenant-ID`. Реальный API-key + чужой заголовок → HTTP 200 | **ИСПРАВЛЕНО** — `_auth_present()` + fail-closed ветка; 12 тестов, мутация поймана |
| N-2 | MEDIUM | `UNION` и `select-from-CTE` обходят ORM-фильтр (`_tenant_aware_entities` → `[]`) — cross-tenant чтение | **открыт** (тест фиксирует текущую картину) |
| N-3 | **MEDIUM → FIXED** | Тот же баг, что закрыт для `pre_llm`, остался в `validate_command:172` и `validate_file_modification:242` — чистый путь возвращал allow без вызова `pre_tool`-хуков | **ИСПРАВЛЕНО**, мутация поймана |
| N-4 | **MEDIUM → FIXED** | Операция, упавшая после частичного старта (в т.ч. по таймауту), не откатывалась: `_started` пополнялся только после успеха | **ИСПРАВЛЕНО** — трек `_attempted`; побочно lifecycle-падения в кластере 10 → 7 |
| N-5 | MEDIUM | 7 из 11 продовых операций без `stop` → не откатываются никогда | открыт |
| N-6 | LOW | возврат `rollback()` игнорируется, ошибки `stop` теряются | открыт |
| N-7 | LOW | `start_all()` не идемпотентен — повторный вызов дублирует `_started` | открыт |
| N-8 | LOW | hardlink внутри репо читается; не эксплуатируемо без write-доступа в корень | принято |
| N-9 | INFO | триггер `post_llm` из контракта `SecurityHook` недостижим (0 вхождений) | открыт |
| F-AN4 | P1 | Локально `UNIT_TEST_JOBS=2`, в CI `-n auto` — топологии расходятся; CI использует конфигурацию, документированную в `Makefile:43-48` как OOM-зависание | открыт |
| F-AS1 | **CRITICAL** | `core.tenancy._current` никогда не заполняется: ORM-фильтр и PG RLS читают пустой tenant | открыт (корень F-AS7/9) |
| F-AS4 | HIGH | `api_key` выполняется внутри `tenant` и хардкодит `tenant_id="default"` | открыт |
| F-AS5 | HIGH | `TenantResourceIsolationMiddleware` — production no-op (0 checker'ов) | открыт |
| F-AS6 | HIGH | `require_object_ownership` — 0 production-caller'ов + fail-open | открыт |
| F-AS7 | HIGH | `hitl_service.get()` снимает tenant-фильтр при пустом tenant | открыт |
| F-AS9 | P1 | 3 из 5 GDPR-адаптеров fail-open на пустом tenant | открыт |
| F-AA | P1 | 3 CI-заглушки печатают «PASS» и ничего не проверяют | открыт |
| F-AB | P1 | 27 warn-only шагов из 213; `check_tenant_isolation --strict \|\| true` | открыт |
| F-AC | P1 | Repo-wide линт не выполняется: 295 нарушений вне `src/`; `make lint` warn-only | открыт |
| F-AD | P2 | `test.yml` `--maxfail=20 -n auto` обрезает картину и противоречит анти-OOM | открыт |
| F-AE | P2 | Startup-гейт измеряет 7 модулей, не `create_app` | открыт |
| F-AF | P2 | `x-request-id` дублируется: `asgi_correlation_id` по умолчанию пишет тот же заголовок | открыт |
| F-AG | P2 | `Referrer-Policy` отсутствует | открыт |
| F-AI | P3 | `record_outcome` для незарегистрированного feature возвращает HEALTHY (implicit success) | сознательно не менялось — контракт закреплён тестом |
| F-AJ | P1 | README: «109 actions» против фактических 132; 167 строк исторических readiness-аудитов | **FIXED** — генератор из кода + CI-гейт, мутация поймана |
| F-AK | P2 | Таблица «Протоколы» в README: 13 строк против 17 фактических пакетов | открыт — требует продуктового решения по каждому протоколу |

---

## 10. NOT_VERIFIED / NOT_RUN (честно)

**Не выполнено в этой волне:**
- BROWSER (Playwright) — `playwright` **отсутствует в venv**, статус **ENV_BLOCKED**,
  не PASS. `trace.zip`/screenshots не получены.
- cURL-прогон выполнен (§9b), но **выборочный**: 27 сценариев из 414 путей схемы.
  `NOT_RUN` внутри него: REST CRUD на изолированном tenant, DSL dispatch с API-key,
  feature-flag OFF→503, rate-limit, timeout, unavailable-dependency,
  authenticated SOAP/GraphQL мутация, tenant-кросс через HTTP для ролей,
  idempotency-повтор (первый запрос упирается в 403 без кредов).
- Рой неполный: не запущены агенты по workflow/Temporal/scheduler, RPA,
  AI/RAG/MCP, services/repositories, protocols/contracts, docs/README.
- Независимый финальный reviewer — не проведён.
- `make ci`, `make chaos`, `make deps-check`, `make secrets-check`,
  `make check-waf-coverage`, mypy-бюджет — не прогонялись.

**Ограничения доказательств:**
- `temporalio`, `playwright`, `openfeature` отсутствуют в venv → вердикты
  `PARTIAL` по Temporal/Playwright означают «код написан, но в этом окружении
  деградирует молча», а не «сломано в проде». Окончательный вердикт требует
  CI-окружения.
- Живые S3/Qdrant/LangMem недоступны.
- Полный интеграционный набор целиком не прогонялся.

---

## 11. Артефакты

| Файл | Состояние |
|---|---|
| `artifacts/current_audit/middleware_actual_order.json` | **новый**, 37/37 middleware, 4 представления порядка |
| `artifacts/current_audit/tenant_spoofing.json` | **новый**, 4 сценария + вердикт |
| `artifacts/current_audit/lifecycle_graph.json` | **новый**, 19 фаз, 3 структуры, 4 readiness-пути |
| `artifacts/current_audit/curl_results.json` | **новый**, 27 сценариев против живого uvicorn |
| `artifacts/current_audit/final_report.md` | этот документ (дополнен §9a QA/CI, §9b cURL) |
| `file_inventory.csv`, `import_graph.json`, `dead_code_candidates.md`, `library_replacement_matrix.md` | **унаследованы от HEAD, не перепроверены** — по инструкции «не доверять артефактам без проверки текущим кодом» их содержимое нельзя считать доказательством |
| `browser_results.md`, `dead_code_evidence.md`, `library_consolidation.md` | **не созданы** (см. §10) |

---

## 12. Статус коммитов

**Ничего не закоммичено.** 10 волн правок, разложенных по независимым зонам:

| Волна | Файлы | Фикс |
|---|---|---|
| 1 | `middlewares/tenant.py`, `request_context.py`, `registry.py`, `setup_middlewares.py`, `tenant_resource_isolation.py` | P0 tenant spoofing + docstrings |
| 2 | `tests/unit/services/ai/pii/recognizers/*`, `_presidio_guard.py` | F-W collection |
| 3 | `tests/unit/docs/…`, `tests/unit/tools/…` | F-Y изоляция тестов |
| 4 | `core/ai/security/agent_security_framework.py` | F-I/F-AH fail-closed |
| 5 | `plugins/composition/lifecycle/*`, `setup_infra/lifecycle.py` | F-E/F-F/F-J |
| 6 | `core/resilience/graceful_degradation.py` | F-L |
| 7 | `README.md`, `make/docs.mk`, `tools/generate_current_metrics.py`, `docs/audit/README_PRODUCTION_READINESS_HISTORY.md` | F-AJ |
| 8 | `.github/workflows/release-gate.yml`, `make/quality.mk`, `make/pipelines.mk`, `tools/checks/check_release_gate.py` | F-Z |
| 9 | `core/ai/fs_facade.py`, `core/ai/errors.py`, `core/config/config_loader.py`, `mcp/mcp_server/tools_document.py`, `plugins/composition/ai_safety_setup.py` | F-AL |
| 10 | `core/tenancy/sqlalchemy_filter.py`, `tests/unit/infrastructure/database/test_tenant_filter.py` | F-AM |

Коммит — только по явной команде владельца. Откат каждой волны —
`git checkout -- <файлы волны>`; `git diff` самодостаточен. Патчи последних
волн сохранены в `/tmp/*.FIXED*` как safety-net.

## 13. Следующий шаг (ровно один)

F-AS1 (split-brain ContextVar) — единственный корень, из которого растут
F-AS7 (fail-open HITL) и F-AS9 (GDPR-адаптеры, стирающие данные всех tenant'ов
при совпадающем `subject_id`). Пока `core.tenancy._current` пуст, ORM-изоляция
и PG RLS не включаются ни в одном сценарии, и три адаптера erase работают
fail-open **по построению**, а не из-за отдельного бага.

Требуется решение владельца до реализации: единый ли источник tenant —
`tenant_id_var` (correlation, уже заполняется middleware) или
`core.tenancy._current` (читают 9 потребителей). Объединение в обратном
направлении затрагивает больше модулей, но не меняет публичный контракт
middleware.
