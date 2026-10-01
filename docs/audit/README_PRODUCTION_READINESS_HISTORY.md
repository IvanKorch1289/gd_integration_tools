# Исторические production-readiness аудиты (вынесено из README)

> **Дата выноса:** 2026-10-01 (аудит `3b509542e`).
> **Почему вынесено:** раздел содержал проценты готовности, снятые в
> прошлых сессиях (62% / 70% / 78% / 82% / 94%), ссылки на конкретные
> коммиты и заявления о состоянии, которые не пересчитываются. Из-за
> этого README выглядел актуальным, но описывал состояние месячной
> давности. Текущие метрики генерируются из кода — см. секцию
> «Текущие метрики» в README и `tools/generate_current_metrics.py`.

> **Воспроизведение.** Каждое утверждение ниже — исторический слепок,
> а не текущий факт. Чтобы проверить состояние сейчас, сверяйтесь с
> рантайм-реестрами и гейтами, а не с этим файлом.

---

## Production Readiness (Sprint 203 + Cycles 25-30)

**Overall: PARTIAL READINESS — 7 critical P0 fixes applied in audit cycle (2026-08-18)**

### Сессия 2026-08-18 — auditor swarm re-audit (commit 30958c3e)

После полного аудита (8 параллельных агентов) зафиксировано:
**7 FALSE_CLAIMs detected в предыдущих версиях README** — части исправлены в этом цикле.

| Priority | Items | Статус | Доказательство |
|---|---|---|---|
| **P0 (security)** | 5 fixes | VERIFIED | IP regex (matches nested paths), Lakak fail-closed (no silent no-op), nemo guards fail-closed, capability gate fail-closed, PII sanitizers fail-closed |
| **P1 (workflow)** | 2 fixes | VERIFIED | ContinueAsNew handler wired (был dead code), WorkflowSubprocess реально стартует child workflow (был stub) |
| **P2 (cleanup)** | 1 fix | DONE | Empty `_legacy.py` stubs удалены (3e/flow_control, patterns) |
| **P0-D2 (facade)** | 1 fix | VERIFIED | `feature_flags` добавлен в `core.api.__getattr__` (для 6+ frontend pages) |

### Текущие OPEN items / циклы Sprint 203

| Sprint 203 original claim | Реальный статус (2026-08-18) |
|---|---|
| `core/api facade` — extensions используют | **PARTIALLY VERIFIED** — extensions 0..42 uses (Sprint 19 audit), 0 frontend files используют (use `core.frontend_facade` legacy wrapper, 98 files) |
| `pg_runner replay()` | **DEPRECATED** (raises `NotImplementedError` since Sprint 217) |
| `EnvelopeEncryptionService` | **REMOVED** (PII-токенизация через Presidio) |
| `core.facades.py` | **DOES NOT EXIST** (consolidated в `core/api/__init__.py`) |
| `212 legacy layer violations` | **STALE** — actual: 136 active (`tools/check_layers_allowlist.txt`) |
| `94/100 final review` | **OVERCONFIDENT** — bandit-strict FAILING (4 HIGH), coverage 51% < 75% |
| `_validate_module_whitelist deduped` | **MISLEADING** — 2 разных реализации (plugin-runtime + skill registry) |

### Архитектурные ADR (новые в сессии)

- **ADR-0249**: DSL → upper-layer import debt (136 active entries в `tools/check_layers_allowlist.txt`,
  старые claim о 214 stale)
- **core/api facade**: canonical extensions public API (re-exports from SDK + 4 lazy categories)
- **Saga compensate_map**: explicit forward→compensate name mapping (Phase 6, cycle 28)

### Метрики (на 2026-08-18)

| Metric | Value |
|---|---|
| Atomic commits (2026-08-18 audit fixes) | 1 (30958c3e) |
| Files changed | 22 (+1299/-140 LOC) |
| New tests added | 67 (58 unit + 9 functional integration) |
| P0 sites closed (audit-verified) | 5 (security), 1 (facade) |
| D-rules minted | D-AUDIT-17601, D-AUDIT-20601 |
| FALSE_CLAIMs detected | 5 (legacy) + 7 (audit 2026-08-18, части исправлены) |
| Domain readiness | ~75% (security проверено, workflow проверено, docs drift остаётся) |
| **Final codebase review** | **OVERCONFIDENT** — реальная оценка ~70% (bandit-strict FAILING, layer drift) |

### Финальное ревью (audit 2026-08-18, post-fix)

| Check | Result | Notes |
|---|---|---|
| `compileall src/backend/` | exit 0 | W0 (cycle 152) мигрировал 234 строки `except A, B:` → `except (A, B):` в 177 файлах (Py2-архаизм, явный tuple form); guard `tests/unit/test_py2_except_syntax_lint.py` обновлён (source-line detection вместо AST-`name`-attr, который молчит на Py3.10+). |
| Layer violations | 7 NEW + 136 baseline | После P0/P1 фиксов net debt может быть больше из-за lazy proxies |
| Tests (P0/P1 fix scope) | 67/67 PASS | ip_restriction_store, input_guard, sanitize_mixin, capability_gate, compile_continue_as_new, workflow_subprocess |
| Architecture (P1-#1 facade) | PARTIAL | Extensions не мигрированы на `core.api` (P1-L1 OPEN) |
| Security (5 P0 semantic fixes) | 5/5 PASS | IP bypass, Lakera, nemo, capability, PII — все fail-closed |
| Workflow (ContinueAsNew, WorkflowSubprocess) | 2/2 VERIFIED | handlers wired, реальный child workflow execution |
| Functional smoke | 8/8 PASS | `tests/integration/test_p0_fixes_functional.py` |
| bandit-strict | FAILING (4 HIGH, 56 MED) | **NOT в CI** — требует S182 cleanup |
| coverage | 51.04% / 75% target | gap 24% — требует S182 cycle |
| DSL processors | 317 modules, 13 step types (all documented; Sprint 19 audit) |
| TODO/FIXME/HACK in critical paths | 0 in d8af74e8-tracked files (Sprint 19 audit; pre-existing uncommitted may differ) |

### Канонические точки входа

```
Extensions:
  from src.backend.core.api import Exchange, Pipeline, get_service, AIGateway, ...
  from src.backend.sdk import ...  # legacy (still works)

Frontend:
  from src.frontend.streamlit_app.api_clients import ...  # 21 domain clients
  from src.backend.core.frontend_facade import ...  # legacy (still works)

DSL:
  from src.backend.dsl.engine.processors.db import DbCrudProcessor, ...
  from src.backend.dsl.engine.processors.infra_elasticsearch import ...
```

### Что осталось (next sprint)

1. **DSL processors full split** — 96 flat files → subdirs (additive pattern established)
2. **RouteBuilder composition refactor** — Protocol definitions ready, gradual migration
3. **Coverage 51% → 75%** — Sprint 40+ closure
4. **214 layer violations refactor** — ADR-0249 exit criteria
5. **Browser RPA integration tests** — Playwright E2E for new builder methods

### Re-audit 2026-08-21 (sync with `docs/audit/RE_AUDIT_2026-08-20.md` + `RE_AUDIT_2026-08-21.md`)

**Production readiness**: 78% (re-audit) vs 62% (audit 2026-08-19) vs 70% (audit 2026-08-18) vs 82% (CLAUDE claim) vs 94/100 (older sprint claim).

**Что изменилось за 1 день**:

| Metric (2026-08-18 audit) | Re-audit (2026-08-21) | Source |
|---|---|---|
| 4 of 6 P0 production blockers OPEN | **1 OPEN** (MCP design decision, documented) | commit cfa5f71c, 191b4167, 84c422f9 |
| `0/117 extensions use core.api` (claim) | **42/45 = 93%** use `core.api` (audit path was wrong: `extensions/` not `src/backend/extensions/`) | `extensions/` grep |
| Frontend uses `core.api` (claim 0 uses) | **39 files use `core.frontend_facade`** (canonical for frontend, NOT `core.api`) | `src/frontend/` grep |
| `136 legacy layer violations` (claim) | **138** (round 1) → **141** (round 2 after +3 facade entries) → **112** (now, after Sprint D.3-D.4 refactor removed 22 + 7 more migrations) | `grep -c -v "^#" tools/check_layers_allowlist.txt` |
| `bandit-strict FAILING (4 HIGH, 56 MED)` (claim) | **0H / 0M / 52L** + CI HIGH-blocking since 2026-08-18 | `.github/workflows/security.yml` |
| `coverage 51.04% / 75% target` (claim) | **.coverage is CORRUPT** (mixed branch+statement data); fail_under = **60%** per S34 W4 (was 75% в S19 K2 W4); full pytest run blocked by opentelemetry-instrumentation-aio-pika pre-release conflict | `pyproject.toml:1080` |
| `12 протоколов` (claim) | **17 actual protocol dirs** in `src/backend/entrypoints/` | `ls src/backend/entrypoints/` |
| `core/facades.py` (claim "новый модуль") | **DOES NOT EXIST** — false claim (verified grep) | grep |
| `EnvelopeEncryptionService` (claim "новая security-фича") | **REMOVED** в Sprint 226 (Presidio PII) — doc updated | `docs/security/envelope_encryption.md` |
| `ClamAV не поднят в docker-compose` (claim) | **REAL service** (`clamav/clamav:stable`) | docker-compose.yml |
| `Memcached cache backend = stub` (claim) | **REAL backend** (aiomcache-based) | `infrastructure/cache/backends/memcached.py` |
| `CertStore vault backend = stub` (claim) | **REAL** (`CertStoreSettings` + `from_settings`) | cert_store.py |
| `CSRF /mcp нуждается в exempt` (claim) | **ALREADY EXEMPT** — `_is_token_auth(scope)` checks `X-API-Key` + `Authorization: Bearer/ApiKey/Token` | csrf.py |

**Round 2 NEW-FOUND + FIXED (Sprint 33 cycle 1)**:

| Item | Status | Commit |
|---|---|---|
| 16 files with Py2 `except X, Y:` (semantically broken in Py3.14) | **FIXED** | b596e750 |
| `tests/unit/test_py2_except_syntax_lint.py` (AST-based regression test) | **ADDED** (2/2 pass) | 3853ef55 |
| `src/backend/core/api/extensions.py` (73 LOC, untracked layer facade) | **COMMITTED** | 3853ef55 |
| `tools/check_layers.py` allowlist + self-skip for extensions facade | **FIXED** | 3853ef55, 8f377cfd |

**Round 2 NEW-FOUND + REJECTED (not real bugs)**:

| Item | Verdict |
|---|---|
| `enforced_invoke.py:201` "fail-open" on `except Exception: pass` | REJECT — wraps only `emit_audit_safe`, not budget_enforcer. |
| 3 falsy-check patterns (search_mixin, hybrid_rag, workflow_activities) | REJECT — correct `and` short-circuit. |
| `ActionHandlerRegistry` no Lock | REJECT — sync startup, cycle 133 atomic check sufficient. |

**Round 3 NEW-FOUND + FIXED (2026-08-22)**:

| Item | Status | Commit |
|---|---|---|
| 4 sites MOCK-fallback pattern systemic (admin_actions:286 _mock_spec, admin_plugins:190/207/233 _mock_plugins/_mock_manifest) | **FIXED** (4/4 → 503) | 54765f71 |
| 2 datetime deprecations: `datetime.utcnow()` (cert_store/backend_consul.py:175) + naive `datetime.now()` (model_registry/local_fs_backend.py:206) | **FIXED** | 54765f71 |

**Round 3 NEW-FOUND + VERIFIED-EXTENDED**:

| Item | Verdict |
|---|---|
| Pydantic V1 patterns (0) — V2 migration COMPLETE | 288 ConfigDict, 117 model_dump, 43 model_validate, 19 @field_validator |
| `typing.List/Dict/Optional` legacy | 0 (only TypedDict/Any/NamedTuple) |
| `subprocess shell=True` | 0 (only in security docstrings) |
| Saga compensation tests | 5 files (test_saga_history, test_saga_lra, test_saga_lra_mixin, test_saga_step, test_saga_lra_processor) |
| HITL tests | 5 files (test_hitl_service, test_hitl_signal_store_redis, test_hitl_watch_cap, test_hitl_history, test_hitl_approval) |
| Watchfiles atomic snapshot/restore | wired in `yaml_watcher.py:148,158,225,255` (snapshot_state before + restore_state in except) |
| RouteBuilder Protocol migration | 2/41 mixins (~5%) — claim "ready, not done" honest |
| `.pyi` stub drift | 153 methods missing from base.pyi vs runtime (P2 backlog) |
| 3 high-risk `__init__.py` hubs | dsl/engine/processors (46 imports), dsl/builders/base (43 imports + 41-mixin MRO), core/config/features (29 imports) |
| 2 pickle deserialization sites | documented + `# nosec B301` (acceptable, but rely on comment-level containment) |

**Round 3 NEW-FOUND FALSE CLAIMs (in pre-audits)**:

| Claim (pre-audit) | Reality | Source |
|---|---|---|
| `Exchange god-node (1071 edges)` | **FALSE CLAIM** — `dsl/engine/exchange.py` is 246 LOC, 14 defs, 4 classes. "1071 edges" is fan-in from callers, NOT file complexity. | `wc -l` + `grep -c "^def "` |
| `pydantic_ai_client.py 68 funcs` | **FALSE CLAIM** — actual 34 funcs | `grep -c "^def \|^    def "` |
| `MOCK fix complete (round 1)` | **PARTIAL** — only `list_actions` fixed. `get_action_spec` + 3 admin_plugins sites still served fabricated data on registry=None. | round 1 audit scope too narrow |
| `138 / 141 layer violations` | **STALE** — actual 112 (Sprint D.3-D.4 refactor removed 22 entrypoints→dsl.* + 7 more migrations) | `grep -c -v "^#"` after refactor |
| `75% coverage target` | **STALE** — pyproject fail_under = 60% (S34 W4) | `pyproject.toml:1080` |
| `.coverage 1%` | **MEASUREMENT ERROR** — file is CORRUPT (mixed branch+statement), can't read 1%. Real state unmeasurable in this session. | `coverage report` errors |

**Remaining OPEN (post round 3)**:
- 5 god-objects (graphql/schema 825/41, pydantic_ai_client 667/34, skill_registry 658/13, agent_security 652/21, vector_store 599/29) — Protocol refactor готов, миграция 2/41 = 5% (P1, 8-16h)
- RouteBuilder `.pyi` stub drift (153 methods) — IDE/mypy see incomplete surface (P2, 1h)
- Coverage: corrupt `.coverage` file → unmeasurable; full pytest blocked by opentelemetry-instrumentation-aio-pika pre-release conflict
- Live HTTP re-verification blocked by stale container (different user namespace, unkillable from current user)
- MCP HTTP mount default=False in dev_light: design decision (documented)
- `.mimocode/` gitignored but 58MB on disk (minor, not in git)
