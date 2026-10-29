# Capability runtime

Runtime-контроль capabilities: плагин получает только то, что
задекларировал, и не больше.

Документ покрывает три слоя:

1. **ADR-044** — открытый registry capabilities (декларация + гейт).
2. **ADR-0366** — runtime-резолвер namespace для DSL-процессоров.
3. **ADR-0393** — БД-гейт `db.read` / `db.write` и авторизация RPA.

## Зачем

* **Sandbox-gate**: плагин получает только то, что задекларировал.
* **Audit trail**: denied-попытки попадают в audit-канал.
* **Least privilege в prod**: core-baseline по умолчанию выключен —
  доступ определяется только декларациями роутов/плагинов.
* **Marketplace UX**: Streamlit page 71 рисует heatmap
  `plugin × capability` для admin.

## Архитектура

```
plugin.toml / route.toml
  └── [[capabilities]]
        name = "net.outbound"
        scope = "credit.events.*"
              │
              ▼
     CapabilityVocabulary (ADR-044)
              │
              ▼
   CapabilityGate.check(name, scope)
              │
   ┌──────────┴──────────┐
   │                     │
   ▼                     ▼
 granted             denied
                      │
                      ▼
            emit_audit_event(
              event_type="capability_denied",
              ...
            )
```

## ADR-044 — vocabulary и гейт

* Capability-каталог — `src/backend/core/security/capabilities/`;
  сгенерированный список — [Capability catalog](../reference/capabilities.md).
* Плагин объявляет capability в `plugin.toml`, роут — в `route.toml`
  (`[[route.capabilities]] name=... scope=...`).
* Инвариант: `route.capabilities ⊆ plugins ∪ public` — роут не может
  объявить capability, которую не объявил ни один плагин-владелец
  (иначе `CapabilitySupersetError`, роут не загрузится).

## ADR-0366 — runtime-резолвер namespace

`src/backend/core/security/capabilities/runtime_resolver.py` решает, в
каком namespace'е проверяется capability:

1. `route_id` роута — если capability им объявлена → namespace = `route_id`;
2. иначе — fallback-namespace `"core"`, но **только** если capability
   входит в `CORE_CAPABILITIES` **и** включён
   `dsl_capability_core_baseline_enabled`;
3. иначе — fail-closed DENY с machine-readable причиной.

`principal` **никогда** не используется как namespace (риск ADR-0361).

Тенант-атрибуция: tenant берётся из `exchange.meta.tenant_id`
(`TenantContext`).

Feature-флаги (рычаги rollout):

| Флаг | Дефолт | Смысл |
|---|---|---|
| `dsl_capability_gate_enabled` | `False` | Включает runtime-проверку `required_capability` у DSL-процессоров. |
| `dsl_capability_core_baseline_enabled` | `False` | Открывает fallback-namespace `"core"` (baseline). |

## ADR-0393 — БД-гейт `db.read` / `db.write`

Для обращений к БД используются две отдельные capability:

| Capability | Когда требуется |
|---|---|
| `db.read` | Читающие запросы (SELECT) через `DatabaseFacade` / `ExternalDatabaseFacade`. |
| `db.write` | DML и любые операции записи (INSERT/UPDATE/DELETE). |

* `scope` = алиас ресурса: имя таблицы (внутренняя БД) либо имя профиля
  внешней БД.
* Проверка `auth_check` выполняется **до** любого обращения к БД.
* Каждый доступ порождает audit-событие (`db.read` / `db.write`) с
  capability, алиасом ресурса, action, route и tenant — без значений
  данных.
* Рабочая схема объявления в `route.toml`:

```toml
[[route.capabilities]]
name = "db.read"
scope = "orders"
```

Роут при этом обязан ссылаться на плагина-владельца ресурса
(`requires_plugins`), иначе subset-инвариант не пройдёт.

## Политика prod / staging

В `config_profiles/prod.yml` и `config_profiles/staging.yml`:

```yaml
features:
  dsl_capability_gate_enabled: true
  dsl_capability_core_baseline_enabled: false
```

Следствия (осознанная политика, ADR-0393):

* **Least privilege** — core-baseline выключен: доступ определяется
  только декларациями роутов/плагинов;
* capability `rpa.*` не публична и не принадлежит ни одному плагину →
  **RPA-шаги в prod/staging отклоняются fail-closed**, пока роут не
  объявит их через плагина-владельца (см.
  [RPA Guide](../rpa/RPA_GUIDE.md));
* проверка профиля (`core/config/validator/profile_merge.py`) поднимает
  CRITICAL, если в prod/staging capability-гейт выключен, и WARNING,
  если включён core-baseline.

В dev/dev_light оба флага остаются `False` — legacy-путь.

## Capability-гейт workflow-активити

Шаг `activity` workflow'а может объявить требуемые capability в поле
`required_capabilities` (`ActivityDeclaration`):

```yaml
steps:
  - type: activity
    name: extensions.credit_pipeline.services.clients.skb:fetch_result
    required_capabilities: ["net.outbound"]
```

* Проверка выполняется в
  `src/backend/dsl/workflow/compiler/activity_bridge.py`: активность
  оборачивается в `capability_guarded_activity(...)` **до** регистрации
  в Temporal — отказ fail-closed с `CapabilityDeniedError` до вызова
  activity.
* Если runtime-контекст плагина недоступен — тоже deny (fail-closed).
* Сам гейт включается флагом
  `feature_flags.activity_capability_gate_enabled`; при выключенном
  флаге обёртка — no-op.

## Связанные документы

* Plugin TOML schema (см. `src/backend/plugins/composition/`).
* Capability vocabulary (см. `src/backend/core/security/capabilities/`).
* Capability catalog — [reference/capabilities.md](../reference/capabilities.md).
* Streamlit page **71_Capabilities** — live heatmap.
* ADR-0366, ADR-0393 — в `docs/adr/`.
