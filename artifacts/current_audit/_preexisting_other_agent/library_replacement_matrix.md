# Library Replacement Matrix (Phase 5, принцип: только реальное сокращение)

| Зона | Текущий код (LOC) | Библиотека | LOC saving | Risk | Решение |
|---|---|---|---|---|---|
| Plugin discovery | core/plugin_runtime + PluginLoader (~600) | pluggy + importlib.metadata | ~200-300 | MEDIUM: hook-контракты, миграция плагинов | DEFER — работает, K5-сертификация завязана |
| DI | core/di providers (~1500, 5 модулей) + svcs_registry | Dishka / явный composition root | ~300 | HIGH: циклы провайдеров, capability-gate | PARTIAL: оставить явный composition root (уже есть app_factory), Dishka НЕ вводить (YAGNI, дублирует) |
| Архитектурные границы | check_layers (grep-based, 22 legacy) | import-linter | ~100 (tool) | LOW | ADOPT для контрактов слоёв (контракт = файл контрактов) — следующий спринт |
| Feature flags | core/feature_flags (broadcaster+cache, ~500) | OpenFeature | ~0 | MEDIUM: API другой, env-providers свои | REJECT: свой механизм уже с tenant-контекстом; OpenFeature добавит слой без сокращения |
| OpenAPI contract | schemathesis уже в deps (не подключён) | Schemathesis | +tests, -0 | LOW | ADOPT: property-тесты на /api/v1 — плановая задача |
| Infra integration | testcontainers уже в deps (smoke 5/5 PASS) | Testcontainers | уже используется | — | DONE (evidence: test_testcontainers_smoke) |
| HTTP tests | respx уже в deps | RESPX | дубликат | — | REJECT: respx уже каноничен |
| Codemods | ad-hoc scripts (tools/*codemod*) | LibCST | ~50/tool | LOW | ADOPT для следующих массовых правок (except-скобки PEP 758) |
| Structured concurrency | asyncio.gather/to_thread | AnyIO task groups | ~0 | MEDIUM: anyio уже транзитивно | DEFER: точечных мест мало; не вводить слой |
| Scheduling | APScheduler + TemporalSchedulerBackend + facade | consolidation (Temporal=canon) | -300-400 LOC | HIGH: deferred-путь на APScheduler | PLAN Phase 6: deferred → SchedulerBackend Protocol; APScheduler остаётся dev-only |
| Agent graph | AI agent runtime (core/ai) | — | — | — | BLOCKED: сравнение не проведено (нужен доменный спринт) |

## Вывод
ADOPT: import-linter (границы), Schemathesis (контракты), LibCST (codemods) — без нового runtime.
REJECT: Dishka, OpenFeature, RESPX, AnyIO-слой — дублируют работающее.
PLAN: scheduling consolidation (Temporal canonical, APScheduler dev-only) — самый крупный LOC-win.
