# ADR-0056 — Routes V11.1a (DSL-routes как лёгкие плагины)

* Статус: Accepted (Sprint 3, К3 W3, 2026-05-13)
* Связано с: V15 R-V15-2, R-V15-12, R-V15-16; PLAN.md V18.1 §S3 К3 W2-W3.

## Контекст

R-V15-2 фиксирует, что DSL-routes живут в ``routes/<name>/`` с
``route.toml + *.dsl.yaml`` и являются «лёгкими плагинами» — полноценные
manifests с capability-gate, semver, hot-reload, tenant_aware, feature_flag,
schedule и SLO. Legacy-каталог ``dsl_routes/`` deprecated после Sprint 7.

Открытые вопросы (зафиксированы в research для К3 W2):

* Где живёт RouteLoader — отдельный модуль или wiring в lifespan?
* Как делается hot-reload — file-watcher или admin-endpoint?
* Какой формат у ``tenant_overrides``?
* Как route манифест взаимодействует с CapabilityGate?

## Решение

1. **Routes layout** — каноническая структура:
   ```
   routes/<name>/
     ├── route.toml          # manifest
     ├── pipeline.dsl.yaml   # main pipeline
     ├── tenant_overrides.yaml  # опц. per-tenant overrides (lazy-loaded)
     └── schedule.yaml       # опц. APScheduler/cron jobs
   ```

2. **Lifecycle 5 фаз** (управляется ``services/routes/loader.py::RouteLoader``):
   * **discover** — sweep ``routes/*/route.toml``, парсинг через ``tomllib``;
   * **validate** — JSON-Schema валидация (``schemas/route.toml.schema.json``)
     + semver-check ``requires_core`` и ``requires_plugins[]``;
   * **declare** — ``CapabilityGate.declare(route, capabilities)`` ДО import_module;
     subset-check ``route.capabilities ⊆ ∪(plugin.capabilities) ∪ public``;
   * **register** — pipeline компилируется через ``DslCompiler`` в FastAPI-роутер;
     scheduler-jobs регистрируются в APScheduler через
     ``infrastructure/scheduler/route_scheduler.py``;
   * **activate** — endpoint становится доступен; feature-flag gate
     (``settings.routes.<name>.enabled``) контролирует rollout.

3. **Capability-gate enforcement** — каждый ``call_function``,
   ``dispatch_action``, ``invoke_workflow`` шаг pipeline проверяется через
   ``CapabilityGate.check(plugin=route_name, capability=..., scope=...)``.
   Decline → ``CapabilityDeniedError`` + ``capability.denied`` audit-event.

4. **Tenant_overrides** — YAML-структура:
   ```yaml
   # tenant_overrides.yaml
   per_tenant:
     tenant_a:
       feature_flag: true
       slo:
         p95_latency_ms: 100
         availability: 0.999
     tenant_b:
       feature_flag: false
       reason: "регрессия в Sprint 3 — выкл до hotfix"
   ```
   Применяются динамически на каждый запрос через ``TenantContext``;
   изменения подхватываются hot-reloader'ом.

5. **Hot-reload через watchfiles.awatch** — единый watcher в
   ``plugins/composition/lifecycle.py::_start_v11_hot_reload`` (default
   ``ROUTES_HOT_RELOAD_ENABLED=False``); на каждое изменение route.toml /
   pipeline.dsl.yaml / tenant_overrides.yaml:
   * revoke previous declaration в CapabilityGate;
   * перепарсить + повторно declare;
   * перерегистрировать FastAPI-роутер (atomic swap через ``router.routes = ...``);
   * audit-event ``route.reloaded`` с diff.

6. **Schedule + SLO декларируются в route.toml** ``[schedule]`` и ``[slo]``:
   ```toml
   [meta]
   name = "credit_check_v2"
   version = "1.0.0"
   requires_core = ">=15.0.0"
   requires_plugins = ["credit-pipeline>=2.1.0"]

   [capabilities]
   net_outbound = ["net.outbound:skb-api.internal:internal"]
   db_read      = ["db.read:credit_decisions"]

   [schedule]
   cron = "0 */4 * * *"
   timezone = "Europe/Moscow"

   [slo]
   p95_latency_ms = 200
   availability    = 0.999
   error_budget    = 0.001
   ```

## Последствия

* `+` Routes становятся первоклассными артефактами с semver + capability-gate
  — нет «мёртвых» pipelines без manifest.
* `+` Hot-reload через watchfiles унифицирован с plugins (Wave B); один
  observer-thread, не race-condition.
* `+` Tenant_overrides избавляет от копи-паста route per-tenant; per-tenant
  feature-flag первоклассный.
* `+` SLO в manifest → Prometheus rules автогенерируются из ``[slo]``.
* `−` Hot-reload off-by-default до Sprint 5 (требует staging-smoke на каждом
  route-update).
* `−` Subset-check capability требует, чтобы все plugins were declared ДО routes
  — обеспечивается lifespan ordering (plugins.startup → routes.startup).
* `−` Migration legacy ``dsl_routes/`` — Sprint 7 (после первой плагин-волны).

## Альтернативы рассмотрены и отклонены

* **Routes как entry_points в plugin.toml** — отклонено: смешивает manifest
  плагина с manifest роута; нарушает separation of concerns.
* **Routes без capability-gate** — отклонено: V15.1 явно требует enforce.
* **Hot-reload через signal SIGHUP** — отклонено: нет atomic-swap гарантии,
  возможны 500-ошибки во время reload.

## CI gates

* ``make plugin-schema`` + ``make route-schema`` — JSON-Schema валидация
  всех ``route.toml``.
* ``tools/checks/check_layers.py`` — запрещает прямой import
  ``infrastructure/`` из ``routes/``.
* ``pytest tests/services/routes/`` — unit-тесты loader/validator/hot-reload.

## Roadmap

* **Sprint 3 W2-W3 (текущий)** — Routes V11.1a manifest + JSON-Schema export.
* **Sprint 4** — Workflow DSL finale, BPMN-import, YAML round-trip + semver.
* **Sprint 5** — production hot-reload (staging-tested), tenant_overrides UI.
* **Sprint 7** — миграция legacy ``dsl_routes/*`` → ``routes/*``.
