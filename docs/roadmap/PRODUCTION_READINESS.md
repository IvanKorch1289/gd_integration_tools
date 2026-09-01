# Production Readiness Roadmap — gd_integration_tools

> **Generated**: 2026-08-31 (Sprint 48 W11), updated 2026-09-01 (Sprint 50 A — verified baseline)
> **Source**: S48 swarm audit (10 доменных агентов, 29 atomic commits W1-W11) + S49 W1-W11 + Sprint 50 A reverification
> **Owner**: координатор роя
> **Baseline**: `docs/roadmap/BASELINE_2026-09-01.md` (verified raw output)

## Текущее состояние (baseline S50 W1, reverified 2026-09-01)

| Метрика | Значение | Verification |
|---|---|---|
| Production readiness (claimed) | ~96% | STATUS.md (R12) |
| **P0 open (per STATUS)** | **0** | **FALSE CLAIM retracted (Sprint A)** |
| **P0 фактический (S48 audit + S49 close-outs)** | **4-7 OPEN** | `git log --grep="swarm-48"` + manual diff |
| **Ruff errors** | **10** (7 auto-fixable) | `ruff check src/` |
| **Bandit HIGH (severity / confidence)** | **0 / 43** | `bandit -r src/ -lll` |
| **Vulture @≥90%** | **1 finding** | `vulture src/` |
| **Layer allowlist** | **37 legacy** | `python3 tools/check_layers.py` |
| **Tests collected** | **15862** | `pytest tests/unit/ --collect-only -q` |
| Coverage gate | 60% (target 70%) | `pyproject.toml:1080` |
| Pre-prod-check gates | 38 | `tools/checks/pre_prod_check.py` |
| **Outdated deps** | **138** | `pip list --outdated` |
| Atomic commits S48-S49 | ~160 | `git log --oneline` |

**FALSE CLAIMs retracted (Sprint A)**:
- `STATUS.md P0 open = 0` — реально 4-7 OPEN (см. S48 W1 audit backlog)
- `STATUS.md Ruff = 0` — реально 10 (7 auto-fixable)
- `STATUS.md Vulture @≥90% = 0` — реально 1 finding (`mobile_jwt_revocation.py:202`)
- `STATUS.md Layer allowlist = 38` — реально 37 (S49 W3 removed 1 stale)
- `STATUS.md Bandit HIGH = 0` — partial: severity=0 OK, confidence=43 NE disclosed

Detailed raw output — `docs/roadmap/BASELINE_2026-09-01.md`.

## Milestones (M1 → M4 = production-ready)

### M1: Close All P0 (security-critical)

**Goal**: 0 P0 в backlog. **Estimate**: 18 задач × медиана 1h = 18h (2-3 рабочих дня).

**Tasks (subset backlog)**:

| ID | Домен | Задача | LOC | Hours |
|---|---|---|---|---|
| W12-P0-#6 | Core | `build_default_vocabulary` god-function split | 388 | 4h |
| W13-P0-#19 | Entrypoints | McpAuthMiddleware wrap REMOVED | 1d | 8h |
| W14-P0-#20 | Entrypoints | WebSocket CSWSH Origin header | 0.5d | 4h |
| W15-P0-#21 | Entrypoints | imports.py no inline auth (4 endpoints) | 0.5d | 4h |
| W16-P0-#17 | Services | notification_hub deprecation | 4h | 4h |
| W17-P0-#18 | DSL | storage/s3.py layer violation | 4h | 4h |
| W18-P0-#31 | Security | mobile_jwt_revocation no-op stores (full impl) | 6h | 6h |
| W19-P0-#22 | Frontend | frontend_aclade layer violation | 12h | 12h |

**Done criteria**: `grep -rn 'P0 open' docs/STATUS.md` → пусто (все P0 закрыты).

### M2: P1 Cleanup (god-objects + layer violations)

**Goal**: 0 P1 в backlog. **Estimate**: 60 задач × медиана 2h = 120h (15 дней).

**Top-10 tasks**:

| ID | Задача | Hours |
|---|---|---|
| M2-#1 | god-object capabilities/defaults.py split (522 LOC → 4 файла) | 4h |
| M2-#2 | god-object orchestrator_mixin.py → PipelineStep (466 LOC) | 4h |
| M2-#3 | core → services audit/facade audit_service DI provider | 4h |
| M2-#4 | extensions → infrastructure inline-imports cleanup | 4h |
| M2-#5 | reverse violation infrastructure/worker.py → plugins | 3h |
| M2-#6 | services → dsl layer violations (×18) | 4h |
| M2-#7 | webhook inbound verification missing | 2h |
| M2-#8 | DSL dead-code _S3_MOD const (DONE S48 W3) | 5m |
| M2-#9 | deprecation warnings on module import → __init__ | 30m |
| M2-#10 | 22 raw httpx → BaseAPIClient migration (Frontend) | 16h |

### M3: Coverage 60% → 75%

**Goal**: coverage gate = 75%. **Estimate**: 4-6 недель.

**Tasks**:

| ID | Задача | Hours |
|---|---|---|
| M3-#1 | Coverage profile (layer breakdown) — sync with .baselines/coverage.json | 2h |
| M3-#2 | Per-layer coverage thresholds (ADR-0285 impl — committed S39 W1) | — |
| M3-#3 | Workflow infrastructure coverage ratchet (current 47%) → 70% | 8h |
| M3-#4 | Entrypoints coverage ratchet (current 29%) → 60% | 8h |
| M3-#5 | DSL processors coverage ratchet (current ~60%) → 80% | 16h |
| M3-#6 | update pyproject.toml fail_under 60 → 75 | 0.1h |

### M4: Full pre-prod-check + functional verification

**Goal**: `make pre-prod-check` exit 0. **Estimate**: 1 неделя.

**Tasks**:

| ID | Задача | Hours |
|---|---|---|
| M4-#1 | Run all 38 pre-prod-check gates | 1h |
| M4-#2 | `make lint-strict && make type-check-strict && make test` | 4h |
| M4-#3 | `make dev-light` + cURL verification of REST/GraphQL/SSE | 4h |
| M4-#4 | Browser verification (Swagger UI, Streamlit portal) | 4h |
| M4-#5 | Load test (locust perf-gate) | 4h |
| M4-#6 | OWASP ZAP baseline scan | 2h |
| M4-#7 | Final STATUS.md sync with verified metrics | 1h |

## Implementation Plan (this session)

Given resources, I'll start M1:

1. **W12**: god-function split (`build_default_vocabulary`)
2. **W13**: McpAuthMiddleware wrap restoration
3. **W14**: WebSocket Origin header validation
4. **W15**: imports.py inline auth (4 endpoints)

Если M1 subset (4/8 P0) closes, M1 marked partial. Полный M1 требует 2-3 рабочих дня, не сессию.

## Verification Strategy

Per phase:
1. `python3 -m ast.parse` для каждого изменённого .py файла
2. `python3 -c "yaml.safe_load(...)"` для .yml
3. `git diff --stat` для подтверждения минимальности диффов
4. Retro обновление в `docs/retros/SPRINT_48_W1_SWARM_AUDIT.md`
5. STATUS.md sync
6. **0 push** (правило AGENTS.md)

## Cross-references

- S48 retro: `docs/retros/SPRINT_48_W1_SWARM_AUDIT.md` (455+ строк)
- STATUS.md: `docs/STATUS.md` (sync каждую итерацию)
- Pre-prod check: `tools/checks/pre_prod_check.py` (38 gates)
- Backlog: S48 W1 retro §Следующая итерация (18 P0 / 60 P1 / 50 P2)