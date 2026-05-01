# DECISIONS.md

## Устойчивые решения проекта

### Базовые правила работы (наследуются)

- Graphify — основной источник знания о связях модулей.
- Любые изменения выполняются только после точного плана.
- Для новых фич сначала AskUserQuestion, затем план, затем реализация.
- Commit только по явной команде пользователя.
- Push и release без отдельного подтверждения запрещены.
- Тесты не навязывать и не предлагать по умолчанию (исключение — Wave 13 production gate).
- Верификация — через Makefile-команды проекта.
- `.claude/` — служебная память Claude, не пользовательская документация.

### Roadmap V10 (принят 2026-05-01)

1. **3-tier protocol registration**: Tier 1 (CRUD) автоматически в 6 протоколах; Tier 2 (Custom) — REST+gRPC+GraphQL авто; Tier 3 — manual через DSL invoke.
2. **gRPC через compile-time .proto codegen** (`tools/codegen_proto.py`), НЕ runtime reflection.
3. **Plugin-система = hooks-декораторы** (`@before_create`, `@after_query`, `@override_method`) + `entry_points` discovery. НЕ monkey-patch.
4. **Codegen = Jinja2 шаблоны**, НЕ AI.
5. **Нативные DB-драйверы**: `oracledb` (Oracle thin-mode) / `aioodbc` (MSSQL) / `asyncmy` (MySQL) / `ibm_db` (DB2). **JDBC-моста (`JayDeBeApi`) НЕТ**.
6. **Logging = structlog** (выбрано после анализа альтернатив 2026-05-01) + `LogSink` ABC + Graylog GELF / disk-rotating / console-json + circuit-breaker fallback. См. `memory/project_logging_choice.md`.
7. **Auth methods**: JWT (HS256/RS256) + API key + mTLS + SAML. **БЕЗ OAuth2/OIDC** (банковский стек).
8. **Multi-tenancy**: full + per-tenant DSL routes / actions / secrets / quotas / billing.
9. **Audit storage**: ClickHouse + SQLite fallback (W5 / ADR-007). НЕ менять.
10. **Compatibility strategy**: жёсткий rewrite роутов на `/api/v1` в новой парадигме (3-tier auto-registration). Без `/api/v2` параллельно.
11. **Embeddings**: `sentence-transformers` default (PyTorch, 3.14 OK); `Ollama` / `OpenAI-compat API` альтернативы. **`fastembed` выкинут**, переведён в opt-in legacy. Подтверждено внешне 2026-05-01: onnxruntime issue #26473 — нет Python 3.14 wheels.
12. **Docstring policy**: каждая публичная функция / класс / метод в `core/`, `dsl/engine/`, `core/interfaces/`, `core/protocols.py` обязана иметь русский docstring. `tools/check_docstrings.py` через `.pre-commit-config.yaml` `stages: [pre-push]`. Запрет пустых/TODO docstrings.
13. **Post-wave memory update** — обязательный шаг DoD каждой Wave: записать `feedback_*.md` или `project_*.md` + строка в `MEMORY.md` о том, чему научился и как лучше дорабатывать. См. `memory/feedback_post_wave_learning.md`.
14. **Performance budget**: p95 < 200ms, RPS > 1000 (Wave 7 + Wave 13 perf gate).

### Wave-26 (Resilient Infrastructure, ADR-036)

- ResilienceCoordinator — singleton без ABC в `core/interfaces/`, единственная реализация. ABC не создаётся преждевременно (Правило 13).
- 11 канонических компонентов (db_main / redis / minio / vault / clickhouse / mongodb / elasticsearch / kafka / clamav / smtp / express) описываются YAML-секцией `resilience` в base.yml.
- Каждый компонент реализуется через `infrastructure/resilience/components/<x>_chain.py` с одной доминирующей операцией.
- DSL `CircuitBreakerProcessor` (pipeline) и infra `BreakerRegistry` (client) — два **независимых** state-machine; унификация выполнена W26.7 (DSL делегирует в общий `breaker_registry`, namespace `dsl.pipeline.<id>`, host=`dsl`).
- `/readiness` возвращает 200 при работающих fallback'ах (`degraded: true`), 503 — только при `down`. Соответствует SRE-подходу graceful-degradation.
- DegradationMiddleware блокирует write-методы (POST/PUT/PATCH/DELETE) при `db_main` в fallback-режиме (HTTP 503 + Retry-After).
- `health.py` остаётся raw HTTP — не переносится на DSL (K8s-пробы должны быть простыми и не зависеть от DSL-runner'а).

### Wave-14.1 (ActionDispatcher Gateway, ADR-038)

- `ActionMetadata` параллельно с `ActionSpec` в `ActionHandlerRegistry` — single source of truth для middleware-цепочки.
- `DispatchContext` несёт `correlation_id / tenant_id / user / transport / timeout_ms`.
- `ActionGatewayDispatcher` Protocol — отдельно от legacy `ActionDispatcher` Protocol.
- Feature flag `USE_ACTION_DISPATCHER_FOR_HTTP` (default OFF) для безопасной миграции.
- `ActionSpec.action_id` — явный связник HTTP-route и handler в `action_handler_registry` (исторически namespace разные).
- Per-spec override `use_dispatcher: bool | None` (None|True|False) с приоритетом над глобальным флагом.
- REST-инференция `side_effect` / `idempotent` из `spec.method` — убирает boilerplate.

### Wave-22 (Invoker Gateway, частично закрыт)

- `Invoker` — главный Gateway проекта; **6 режимов**: SYNC / ASYNC_API / ASYNC_QUEUE / DEFERRED / BACKGROUND / STREAMING.
- Реализован SYNC; остальные 5 — `NotImplementedError` (закрытие в Wave F.2).
- `InvocationReplyChannel` Registry: Memory / Email / Express / Queue.
- Обнаружено в pre-Wave 22 ритуале: 70-80% реализовано, требуется консолидация (15 issues, Wave F.2).

## Технические особенности

- `ResilienceCoordinator` — singleton, не пере-init'ится в тестах. Используй `set_resilience_coordinator(None)` для очистки между тестами.
- `DegradationMiddleware` блокирует только writes к `db_main`. Если потребуется блокировать writes для других компонентов — расширить `_check_blocked_components`.
- `tools/check_fallback_matrix.py` запускается в `make readiness-check` и проверяет консистентность `RESILIENCE_COMPONENTS` ↔ `base.yml`.
- `_app_ref` имеет `require_app_ref()` (strict), `reset_app_state()` (для тестов), warning при двойном `set_app_ref()` без сброса.
- 31 module-level eager singleton переведён на lazy (Wave 6.1): 13 services через `app_state_singleton`, 16 infrastructure через `lru_cache(maxsize=1)` + module `__getattr__` shim.
- `core/di/module_registry.py` — единый реестр 45 infra-модулей с namespace-prefix, `resolve_module(key)` + `validate_modules()`.

## Что проверять вручную

- При добавлении нового компонента в `RESILIENCE_COMPONENTS`:
  1. обновить `config_profiles/base.yml` (breakers + fallbacks);
  2. создать `infrastructure/resilience/components/<x>_chain.py`;
  3. зарегистрировать в `_REGISTRARS` в `registration.py`;
  4. прогнать `tools/check_fallback_matrix.py`.
- При деплое в prod: убедиться, что Prometheus собирает метрику `app_degradation_mode{component=...}` и в Grafana есть alert по `> 0`.
- **После каждой завершённой Wave**: запись `feedback_*.md` / `project_*.md` в `~/.claude/projects/-home-user-dev-gd-integration-tools/memory/` + строка в `MEMORY.md` (по правилу V10 #13).
