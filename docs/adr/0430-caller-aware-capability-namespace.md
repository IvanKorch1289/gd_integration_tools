# ADR-0430 — Caller-aware namespace для capability-проверок + гейт деклараций

* Статус: Accepted (2026-11-09, волна 28)
* Cycle: 187 (волна 28)
* Связан с: ADR-0416 (capability-контур, wildcard-scope), ADR-0421 (права на action-поверхностях), ADR-0284 (межслойные импорты)
* Затрагивает:
  - `src/backend/core/security/capabilities/caller.py` (новый: ContextVar namespace'а вызывающего),
  - `src/backend/core/security/capabilities/gate/declaration_mixin.py` (`has_plugin`),
  - `src/backend/dsl/engine/execution_engine.py` (привязка namespace'а маршрута),
  - `src/backend/services/storage/facade.py`, `src/backend/services/cache/facade.py`,
    `src/backend/infrastructure/database/external_database_facade.py`,
    `src/backend/core/net/outbound_http.py` (проверка под namespace'ом вызывающего),
  - `tools/check_route_capabilities.py` (новый гейт), `.security/route-capabilities-baseline.txt`,
  - `.github/workflows/lint.yml` (шаг гейта)

---

## Контекст

Фасады ядра создаются в composition root с фиксированным namespace'ом платформы
(`StorageFacade`/`UnifiedCacheFacade`/`ExternalDatabaseFacade` — `"system"`,
`OutboundHttpClient` — `"core"`). Проверка capability шла под baseline'ом
платформы, поэтому декларации роута (`route.toml` → `storage.*`/`db.*`/`cache.*`)
на неё не влияли: автор не мог ограничить свой роут (ADR-0416 §Открытое).
Фактически capability-контур для ресурсных операций был декоративным.

---

## Решение

1. **Namespace вызывающего** (`route_id`) передаётся через `ContextVar`
   (`core/security/capabilities/caller.py`): DSL-движок привязывает его на
   время исполнения маршрута, фасады используют `effective_plugin(self._plugin)`.
2. **Безопасная деградация:** привязка выставляется **только если** у роута
   есть декларации (`CapabilityGate.has_plugin`) → иначе проверка идёт под
   платформенным namespace'ом (прежнее поведение). Включение caller-aware
   проверки не ломает существующие роуты.
3. **Гейт деклараций** (`tools/check_route_capabilities.py`): роут обязан
   объявлять `net.inbound`, плагин — хотя бы одну capability. Легаси-манифесты
   вынесены в baseline `.security/route-capabilities-baseline.txt` (рэтчет:
   новые манифесты обязаны декларировать, старые мигрируются). Ресурсные
   capability (storage/db/cache/net.outbound) печатаются как WARN-отчёт:
   строгая проверка требует стабилизации формата scope у процессоров.

---

## Последствия

* Декларации роутов теперь реально влияют на проверку: роут, объявивший
  `storage.read` со scope `bucket/*`, не получает доступ к чужому scope.
* Платформенный baseline сохраняется для кода, который не идёт через DSL
  (composition root, фоновые задачи) и для роутов без деклараций.
* Гейт блокирует новые манифесты без деклараций; легаси-список виден в
  репозитории и должен сжиматься.
* Owner-задача: включить строгую проверку ресурсных capability (после
  стабилизации формата scope) и мигрировать легаси-манифесты из baseline.
