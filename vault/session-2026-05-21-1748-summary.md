# Сессия 2026-05-21 17:48 — Sprint 17 kickoff (7 wave landed)

## Контекст

Coordinator-self сессия, scope: wave Sprint 17 НЕ зависящие от S16 carryover
(FTP CERT_NONE, pybreaker scaffold finalize, DegradationManager circular import).

PLAN.md V22 FINAL §S17 — 24 wave + 15 DoD; в сессии закрыто 7 (1 backbone +
3 quick + 3 ADR scaffold). 16 wave перенесены на следующие сессии.

## Краткий перечень сделанного

| Wave | Commit | Зона | DoD/ADR |
|------|--------|------|---------|
| `s17/backbone` | `b08c974d` | features.py + team-ownership + KNOWN_ISSUES | backbone |
| `s17/k3-w0-routes-capability-gate` | `970b655b` | services/routes/loader.py | K-ARCH-3 |
| `s17/k1-w3-call-function-whitelist-strict` | `83ebf9f5` | dsl/processors/function_call.py | K-ARCH-5 |
| `s17/k5-w3-db-migration-init-container` | `c603b895` | compose + k8s Job | K-OPS-4 |
| `s17/k1-w2-authorization-gateway` | `bd49a53c` | core/interfaces + core/security | ADR-NEW-1+4 |
| `s17/k3-w1-unified-request-context` | `7a335d52` | core/request_context + middleware | ADR-NEW-3 |
| `s17/k2-w1-metrics-registry` | `67d37f82` | infrastructure/observability | D11 backbone |

Также: `6a35c75d [wave:s17/k9-tooling-grep-violations-gate]` — параллельная сессия (без конфликта).

## Изменённые / новые файлы

### Новые файлы (NEW)

| Путь | Назначение |
|------|------------|
| `.claude/team-ownership.toml` | 10 команд k1..k10 + 4 blockers + meta |
| `src/backend/core/interfaces/capability_gateway.py` | `CapabilityGatewayProtocol` (ADR-NEW-4) |
| `src/backend/core/security/authorization_gateway.py` | `AuthorizationGateway` (ADR-NEW-1) |
| `src/backend/core/request_context.py` | `RequestContext` frozen dataclass + ContextVar (ADR-NEW-3) |
| `src/backend/entrypoints/middlewares/request_context.py` | `RequestContextMiddleware` ASGI |
| `src/backend/infrastructure/observability/metrics_registry.py` | `MetricsRegistry` idempotent factory (D11) |
| `tools/checks/check_routes_capability_gate.py` | CI gate K-ARCH-3 |
| `deploy/k8s/jobs/migration.yaml` | K8s Job alembic upgrade head |
| `tests/unit/core/security/test_authorization_gateway.py` | 10 тестов AuthorizationGateway |
| `tests/unit/entrypoints/middlewares/test_request_context.py` | 11 тестов RequestContext MW |
| `tests/unit/infrastructure/observability/test_metrics_registry.py` | 12 тестов MetricsRegistry |
| `tests/unit/dsl/engine/processors/test_function_call.py` | 10 тестов CallFunctionProcessor |

### Модифицированные файлы (M)

| Путь | Изменение |
|------|-----------|
| `src/backend/core/config/features.py` | +12 default-OFF feature-flags Sprint 17 |
| `.claude/KNOWN_ISSUES.md` | + секция Sprint 17 (wave map + carryover + blockers + DoD) |
| `src/backend/services/routes/loader.py` | + audit_callback / strict_capabilities params; audit-event `route.capabilities.allocated`; `_is_strict()` / `_emit_audit()` helpers |
| `src/backend/core/security/capabilities/gate.py` | + `list_allocated()` метод (для Protocol conformance) |
| `src/backend/dsl/engine/processors/function_call.py` | + `_is_strict_whitelist()` / `_check_capability()` staticmethods; production strict mode |
| `extensions/example_plugin/plugin.toml` | + `call_function_modules` пример |
| `ops/compose/docker-compose.yml` | + service `migration-runner` + `depends_on::service_completed_successfully` для app/worker |
| `src/backend/entrypoints/middlewares/setup_middlewares.py` | + регистрация RequestContextMiddleware после TenantMiddleware |
| `tests/unit/services/routes/test_loader.py` | +3 теста (audit / strict / default-off) |

### Memory (вне репо)

| Путь | Назначение |
|------|------------|
| `~/.claude/projects/.../memory/feedback_sprint17_kickoff_independent_wave.md` | Lessons + carryover + ссылки на ADR |
| `~/.claude/projects/.../memory/MEMORY.md` | +строка ссылки на новый feedback |

## Выполненные команды проверки

### Smoke imports
```bash
python -c "from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol"
python -c "from src.backend.core.security.authorization_gateway import AuthorizationGateway"
python -c "from src.backend.core.request_context import RequestContext"
python -c "from src.backend.infrastructure.observability.metrics_registry import MetricsRegistry"
python -c "from src.backend.core.config.features import FeatureFlags; FeatureFlags()"
python -c "from src.backend.entrypoints.middlewares.request_context import RequestContextMiddleware"
python -c "from src.backend.services.routes.loader import RouteLoader, AuditCallback"
```
✅ Все 6 модулей импортируются без ошибок (Vault unavailable — ожидаемо в dev).

### Unit-тесты (изолированно)
```bash
pytest tests/unit/core/security/test_authorization_gateway.py    # 10 passed
pytest tests/unit/entrypoints/middlewares/test_request_context.py # 11 passed
pytest tests/unit/infrastructure/observability/test_metrics_registry.py # 12 passed
pytest tests/unit/services/routes/test_loader.py                  # 28 passed (25 prior + 3 new)
pytest tests/unit/dsl/engine/processors/test_function_call.py     # 10 passed
pytest tests/unit/dsl/round_trip/test_new_fluent_methods.py       # 15 passed (regression)
```
✅ **71 пасса**, 0 регрессий в существующих тестах.

### CI-gates
```bash
python tools/check_team_ownership.py
# ✓ team-ownership.toml OK: 10 команд (k1..k10), 4 блокеров

python tools/checks/check_routes_capability_gate.py --strict
# ✓ routes capability-gate OK: declare() ДО registrar() +
#   audit-event 'route.capabilities.allocated' эмитится
```

### Lint / type
```bash
ruff check src/backend/core/interfaces/capability_gateway.py \
           src/backend/core/security/authorization_gateway.py \
           src/backend/core/request_context.py \
           src/backend/infrastructure/observability/metrics_registry.py \
           src/backend/entrypoints/middlewares/request_context.py \
           src/backend/services/routes/loader.py \
           tools/checks/check_routes_capability_gate.py
# All checks passed (после auto-fix I001 и noqa S110 на pre-existing блок)

python -c "import yaml; yaml.safe_load(open('ops/compose/docker-compose.yml'))"
# OK
python -c "import yaml; yaml.safe_load(open('deploy/k8s/jobs/migration.yaml'))"
# OK
```

## Открытые риски

1. **Pre-existing failing test** `tests/unit/core/security/capabilities/test_vocabulary.py::test_default_catalog_full` — `assert len(v.all()) == 16` vs реально 26 (vocabulary расширен `8114b14a [wave:s1/capability-fs-create-new]`). Не моя регрессия, но требует apdate теста.

2. **AuthorizationGateway carryover**: миграция 30+ non-public endpoint-guard'ов на `await gateway.authorize(...)` НЕ в этой сессии. Scaffold + Protocol готовы; migration — отдельная wave.

3. **RequestContext carryover**: миграция 30+ callsites `request.state.correlation_id → RequestContext.current()` НЕ в этой сессии. `tools/migrate_request_context.py` будет создан в `[wave:s17/k3-w1-migrate-callsites]`.

4. **MetricsRegistry carryover**: миграция 42–52 inline `Counter()/Histogram()/Gauge()` callsites — `[wave:s17/k2-w2-metrics-migrate]` следующей сессии.

5. **TaskRegistry coverage Phase 4 skipped**: 2 orphan `asyncio.create_task` в `infrastructure/secrets/{rotation.py, vault_rotator.py}` под path-policy denial. Отдельная K1 Security сессия требуется.

6. **Параллельная сессия в working tree**: модифицированы CONTEXT.md / DECISIONS.md / KNOWN_ISSUES.md / PLAN.md (post-production gap-backlog S21-S23 + ADR-NEW-12..15). НЕ моя зона; ждёт коммита параллельной сессии.

7. **К1 Security carryover S16**: DoD-3 (FTP CERT_NONE 6 файлов) + DoD-9 (pybreaker integration) + DoD-12 (S16 closure) — блокируют некоторые S17 wave (k1-w1, k2-w5).

8. **Circular import** `DegradationManager` в `core/resilience/__init__.py` (риск #1 из CONTEXT.md) — блокирует `[wave:s17/k2-w5-resilience-coordinator-class]`.

## Следующий шаг

**Не в этой сессии (16 wave + closure)**:

1. **`[wave:s17/k1-w0-python3-except-clause-sweep]`** — codemod 70+ файлов с `except E1, E2:` (F-A-4 pre-test gate: ручной diff-review 5+ callsites ДО batch). Большая wave, отдельная сессия.
2. **`[wave:s17/k1-w1-tls-cert-required]`** — после S16 DoD-3 closure.
3. **`[wave:s17/k3-w0-routes-tenant-aware]`** — K-ARCH-4 (после backbone готова).
4. **`[wave:s17/k3-w2-middleware-registry]`** — ADR-NEW-2.
5. **`[wave:s17/k1-w4-config-validator]`** — D14.
6. **`[wave:s17/k2-w2-metrics-migrate]`** — sweep 52 callsites после k2-w1.
7. **`[wave:s17/k2-w3-task-registry-coverage]`** — secrets/ orphan + другие.
8. **`[wave:s17/k2-w4-apscheduler-observability]`** — D13b.
9. **`[wave:s17/k2-w5-resilience-coordinator-class]`** — требует fix circular import.
10. **`[wave:s17/k3-w3-correlation-id-end-to-end]`** — D12 после RequestContext.
11. **`[wave:s17/k3-w4-saga-state-store]`** — K-OPS-1.
12. **`[wave:s17/k5-w1-tenant-feature-toggle-ui]`** — D9.
13. **`[wave:s17/k5-w2-k8s-manifests]`** — K-OPS-2.
14. **`[wave:s17/k9-w1-pre-prod-check-v2-scaffold]`** — K-OPS-3.
15. **`[wave:s17/k1-w5-backup-dr-scaffold]`** — K-OPS-5.
16. **`[wave:s17/k7-w1-observability-fixes]`** — S-L7-1..3.
17. **`[wave:s17/closure]`** — финал DoD verify + memory + CONTEXT/ARCHITECTURE update.

## Метрики сессии

- 7 commits / ~1100 LOC новый код / 46 новых unit-тестов
- 12 default-OFF feature-flags
- 2 CI-gates зелёные
- 0 регрессий
- Длительность: ~3.5 часа

## Архитектурные эффекты

- **K-ARCH-3** закрыт: routes без declared capabilities блокируются в strict-режиме; audit-event на каждое allocation.
- **K-ARCH-5** закрыт: RCE prevention — production / strict-mode требует whitelist для call_function.
- **K-OPS-4** закрыт: миграции выполняются перед app в compose + k8s.
- **ADR-NEW-1+4** scaffold: AuthorizationGateway фасад + Protocol готовы; миграция callsites — carryover.
- **ADR-NEW-3** scaffold: RequestContext + ContextVar + MW зарегистрированы; миграция callsites — carryover.
- **D11** backbone: MetricsRegistry — миграция inline-metric callsites следующей wave.

## Cross-references

- `PLAN.md` V22 FINAL §S17 (197–256) — 24 wave + 15 DoD исходный список.
- `.claude/DECISIONS.md` ADR-NEW-1..4 — backbone-ADR scaffold-ы текущей сессии.
- `.claude/KNOWN_ISSUES.md::## Sprint 17` — открытая S17 секция + carryover карта.
- `.claude/team-ownership.toml` — 10 команд + 4 blockers (b1..b4).
- `vault/s17-backbone-draft-2026-05-21.md` — draft, использован частично (формат `[team_s17.k1]` отвергнут validation tool'ом — переписан на `[team.k1..k10]`).
- `~/.claude/projects/.../memory/feedback_sprint17_kickoff_independent_wave.md` — lessons.
