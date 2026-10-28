# ADR-0366 — Runtime-enforcement capability-гейта DSL-процессоров

* Статус: Accepted (2026-10-28, cycle 172)
* **Cycle**: 172 (Wave 14, RPA-ревью → решение D1 владельца)
* **Решение владельца**: `artifacts/current_audit/RPA_REVIEW_DECISIONS_2026-10-28.md`,
  раунд 1, D1 — «починить сейчас, безопасное включение»
* **Затрагивает**:
  - `src/backend/core/security/capabilities/runtime_resolver.py` (новый)
  - `src/backend/core/security/capabilities/gate/declaration_mixin.py`
  - `src/backend/dsl/engine/processors/base.py`
  - `src/backend/dsl/engine/processors/agent_dsl/_base.py`
  - `src/backend/dsl/engine/exchange.py`
  - `src/backend/core/config/features/dsl.py`
  - `config_profiles/dev.yml`, `config_profiles/dev_light.yml`
* **Связан с**:
  - ADR-0361 — фактический deny-all в `BaseProcessor.auth_check` (этот ADR —
    его реализация, вариант «(а)» решения D1);
  - ADR-044 — `CapabilityGate` (runtime capability-контроль);
  - ADR-0354 — слоистость (core не импортирует dsl);
  - ADR-0284 §1.1 — изменение семантики авторизации требует отдельного ADR.

## Контекст

`BaseProcessor.auth_check` (`dsl/engine/processors/base.py`) — единая точка
runtime-контроля `required_capability` у **72 RPA-процессоров** и ~40 прочих.
До этого цикла проверка шла в sync `AuthorizationGateway.check`, где allow
возможен только из пустых in-memory policies; sync-хуки Casbin/OPA мертвы,
а `CapabilityGate.check` в этом пути **не вызывался** вовсе. Факт —
**deny для любой** `required_capability` (ADR-0361, §«Фактический путь
проверки»): RPA-подсистема функционально мертва в рантайме. Async-ветка
`authorize()` capability-гейт использовала — пути расходятся.

Дополнительно в той же точке:

* `principal="anonymous"` был **захардкожен** (`base.py:79`) — вызывающий
  не мог быть атрибутирован;
* tenant брался из `exchange.meta.tenant_id`, но в запрос авторизации не
  попадал осмысленно (использовался только как `extra_ctx`);
* namespace для capability не был определён вовсе: ни `route_id`, ни plugin.

Попытка «просто добавить `CapabilityGate.check` в sync-путь» отклонена
владельцем ещё в ADR-0361: без явного маппинга это открыло бы 77
core-capability анонимному вызывающему (риск ADR-0361).

## Решение

### 1. Runtime-резолвер в `core`

Новый модуль `src/backend/core/security/capabilities/runtime_resolver.py`
(слой `core` не импортирует `dsl` — ADR-0354):

* `CapabilityRequest(capability, action, plugin, scope, tenant)` — запрос;
* `resolve_plugin(request, *, gate=None) -> str | None` — выбор namespace;
* `check(request, *, principal=None, gate=None) -> CapabilityDecision` —
  проверка с fail-closed поведением.

### 2. Правило namespace

```
1) plugin = route_id роута; если capability им объявлена → namespace = route_id
2) иначе namespace = "core", но ТОЛЬКО если:
      feature_flags.dsl_capability_core_baseline_enabled is True
      И capability ∈ CORE_CAPABILITIES
3) иначе → DENY (fail-closed), причина в audit-событии и в логе
```

`principal` **никогда** не используется как namespace: он передаётся в
резолвер отдельным аргументом и используется только для аудита и логов
(ADR-0361: иначе анонимный caller открыл бы capability ядра).

### 3. Tenant-атрибуция

Решение capability-гейта обязано быть отнесено к тенанту, поэтому запрос
без tenant → DENY (`tenant_missing`). Вызывающий (DSL-процессор) передаёт
`exchange.meta.tenant_id`, а для pipeline'ов без tenant-контекста —
системный tenant `_system` (`SYSTEM_TENANT_ID`), как это уже делает сам
`CapabilityGate` (ADR-044, «Default tenant = SYSTEM_TENANT_ID»).

### 4. Feature-флаги (rollout-рычаги)

| Флаг | Default | Смысл |
|---|---|---|
| `dsl_capability_gate_enabled` | `False` | Включает runtime-резолвер. `False` → legacy-путь (`check_source_capability`), поведение до ADR-0366 не меняется. |
| `dsl_capability_core_baseline_enabled` | `False` | Открывает fallback-namespace `"core"`. Baseline открывается **явно**. |

Rollout: `dev.yml` / `dev_light.yml` → `dsl_capability_gate_enabled: true`;
далее staging (после миграции `route.toml` под новый namespace) → prod.

### 5. Точки подключения

* `BaseProcessor.auth_check` — флаг-развилка: legacy-путь или резолвер;
  `principal` берётся из `exchange.meta.principal` (новое поле `ExchangeMeta`),
  tenant — из `exchange.meta.tenant_id`; namespace — `route_id` роута
  (`_capability_namespace`), scope — `_capability_scope` (хук для наследников).
* `agent_dsl/_base.py` — переведён на общий резолвер с namespace `"core"`
  (`_plugin_name()`), иначе 12 AI-процессоров получили бы deny.
* `CapabilityGate.has_declaration(plugin, capability)` — публичный хелпер
  для выбора namespace'а (без него резолвер не знает, объявил ли роут
  capability).

## Альтернативы (отклонённые)

* **(а) Единый gateway** — использовать app-level `AuthorizationGateway`
  (`plugins/composition/di.py`) в processor-пути. *Отклонено*: это
  composition-root-объект, недоступный из `core`/`dsl` без цикла и
  инверсии слоёв; перенос авторизации целиком — отдельный ADR (ADR-0361,
  followup 2).
* **(б) Sync-Casbin/OPA-хуки** — реализовать `_casbin_check`/`_opa_check`
  в sync-`check()`. *Отклонено*: policy-движки в проекте не настроены
  (0 production-callers `add_policy`), поэтому результат не изменился бы, а
  объём (policy-цепочка Casbin/OPA) кратно превышает задачу «починить
  capability-контроль».
* **(в) `principal` → plugin** (маппинг principal в namespace). *Отклонено
  владельцем*: риск ADR-0361 — анонимный/произвольный principal получил бы
  все объявленные capability (в т.ч. RPA и `secret.read`).
* **(г) Fail-open при отсутствии декларации** (пропускать проверку, если
  capability не объявлена). *Отклонено*: противоречит fail-closed политике
  проекта и базовой декларации (`core_declarations.py`).
* **(д) Перенести резолвер в `services/`** — *отклонено*: `dsl` не должен
  зависеть от `services` напрямую (ADR-0354), а `core` — общий доступный
  уровень.

## Последствия

### Позитивные

* `required_capability` перестал быть декоративной декларацией: при
  включённом флаге проверка реально исполняется и даёт **allow** для
  capability, объявленной роутом.
* Namespace определён однозначно и безопасно: `route_id` → `"core"` →
  DENY; `principal` в namespace не участвует.
* Отказ fail-closed и объясним: причина (`no_declaration`,
  `tenant_missing`, `capability_denied`, `unknown_capability`) — в
  audit-событии `capability.check` и в логе.
* Включение — безопасное: оба флага default-OFF, baseline открывается
  явно, legacy-путь сохранён и является поведением по умолчанию.

### Негативные

* **Включение флага в окружении, где `route.toml` не мигрирован, даёт
  deny** для capability, которые раньше (по ошибке) тоже denied — но теперь
  причина видна в логах и audit. Это и есть сигнал к миграции.
* Capability с `scope_required=True` и конкретным scope в `route.toml`
  требует от процессора `_capability_scope`; процессоры без scope-hука
  проходят только при wildcard-scope (`**`).
* Legacy-путь (`check_source_capability`) остаётся в коде до завершения
  rollout'а — это технический долг, который будет удалён отдельным шагом.

### Нейтрально

* Async-ветка `authorize()` и sync-ветка процессоров по-прежнему
  используют разные источники решений (ADR-0361, followup 2) — этот ADR
  чинит только processor-путь.
* Tenant-аллокации (`declare_tenant`) по-прежнему не заполняются: резолвер
  атрибутирует решение к тенанту, но per-tenant capability-гранты не
  проверяет (это отдельный followup).

## Проверка

```bash
.venv/bin/python -m pytest \
  tests/unit/core/security/capabilities/test_runtime_resolver.py \
  tests/unit/dsl/engine/processors/test_base_processor_capability_gate.py \
  -q -p no:randomly
# ожидаемо: 21 passed

.venv/bin/python -m ruff check \
  src/backend/core/security/capabilities/runtime_resolver.py \
  src/backend/core/security/capabilities/gate/declaration_mixin.py \
  src/backend/dsl/engine/processors/base.py \
  src/backend/dsl/engine/processors/agent_dsl/_base.py \
  src/backend/dsl/engine/exchange.py \
  src/backend/core/config/features/dsl.py

.venv/bin/python tools/check_layers.py --strict          # baseline 41 — новых нет
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
.venv/bin/python tools/config_audit.py --scope orphans   # 0
.venv/bin/python tools/check_decorative_capabilities.py --ci  # 0 новых
```

### Известный долг, требующий миграции тестов (вне зоны C1)

Включение `dsl_capability_gate_enabled` переключает
`BaseProcessor.auth_check` с legacy-пути (`check_source_capability`) на
резолвер. Тесты, которые мокают **legacy-путь**, требуют миграции на
мок резолвера:

* `tests/unit/dsl/engine/processors/eip/test_transformation.py` — 10 тестов
  (`test_claim_check_*`, autouse-фикстура `_allow_claim_check_capability`);
* `tests/unit/dsl/engine/processors/workflow/best_practices/test_workflow_best_practices.py`
  — 4 теста (claim-check / continue-as-new).

Оба файла **вне зоны C1** — правка не выполнялась. Пока флаг включён в
`dev.yml`/`dev_light.yml`, эти 14 тестов падают с
`capability ... denied (no_declaration)`: exchange в них не имеет
`route_id`, capability не объявлена роутом, а baseline-флаг выключен.

Дополнительно: `tests/unit/core/config/test_features_dsl.py::test_dsl_field_count`
(ratchet на число полей `DSLFlags`) ожидает 13 полей — после добавления двух
флагов их 15; счётчик требуется обновить (файл вне зоны C1).

## Followup (G12.2–G12.5)

* **G12.2** — 13 классов с `required_capability`, но без вызова
  `auth_check`: декларация без эффекта (вне зоны этого ADR).
* **G12.3** — `FacadeCapabilityAdapter` глотает deny в `authorize()`.
* **G12.4** — миграция `route.toml` под новый namespace: роут объявляет
  используемые capability; после миграции baseline можно выключить.
* **G12.5** — удаление legacy-пути `check_source_capability` из
  `BaseProcessor.auth_check` после завершения rollout'а + миграция
  14 тестов, мокающих legacy-путь (см. «Известный долг» выше).
* **G12.6** — wiring `browser_pool`/`desktop_rpa_client` в `ExecutionContext`.

## Связи с другими ADR

- ADR-0361 — фактический deny-all и три отклонённых кандидата починки;
  этот ADR реализует вариант «namespace-резолвер + feature-флаги».
- ADR-044 — `CapabilityGate`, `CapabilityRef`, `SYSTEM_TENANT_ID`,
  baseline-декларации ядра.
- ADR-0354 — DSL не импортирует `services` напрямую: резолвер живёт в
  `core`, DSL обращается к нему через core-API.
- ADR-0284 §1.1 — изменение семантики авторизации оформлено отдельным ADR.
