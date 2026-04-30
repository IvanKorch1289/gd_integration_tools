# DECISIONS.md

## Устойчивые решения проекта

- Graphify — основной источник знания о связях модулей.
- Любые изменения выполняются только после точного плана.
- Для новых фич сначала AskUserQuestion, затем план, затем реализация.
- Commit только по явной команде пользователя.
- Push и release без отдельного подтверждения запрещены.
- Тесты не навязывать и не предлагать по умолчанию.
- Верификация — через Makefile-команды проекта.
- `.claude/` — служебная память Claude, не пользовательская документация.

## Wave-26 (Resilient Infrastructure, ADR-036)

- ResilienceCoordinator — singleton без ABC в `core/interfaces/`,
  единственная реализация. ABC не создаётся преждевременно (Правило 13).
- 11 канонических компонентов (db_main / redis / minio / vault /
  clickhouse / mongodb / elasticsearch / kafka / clamav / smtp /
  express) описываются YAML-секцией `resilience` в base.yml.
- Каждый компонент реализуется через `infrastructure/resilience/
  components/<x>_chain.py` с одной доминирующей операцией.
- DSL `CircuitBreakerProcessor` (pipeline) и infra `BreakerRegistry`
  (client) — два **независимых** state-machine; унификация отложена
  в W27+ (документировано в ADR-036).
- `/readiness` возвращает 200 при работающих fallback'ах (`degraded:
  true`), 503 — только при `down`. Соответствует SRE-подходу
  graceful-degradation.
- DegradationMiddleware блокирует write-методы (POST/PUT/PATCH/DELETE)
  при `db_main` в fallback-режиме (HTTP 503 + Retry-After).
- `health.py` остаётся raw HTTP — не переносится на DSL (K8s-пробы
  должны быть простыми и не зависеть от DSL-runner'а).