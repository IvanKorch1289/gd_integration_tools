"""Sprint 101 closure — DEEP-RESEARCH follow-up execution.

**Sprint goal:** закрыть оставшиеся 4 🔴 P0 + 6 ⚠️ P1 gap'а из
``gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md``
(S92 state, 2026-06-12).

**Sprint window:** S100 closure (2026-06-13) → S101 W5 (2026-06-13).
**Wave pattern:** 5 waves = 5 atomic commits.

---

## W1 — D15 CDC consolidation (commit 354befee)

**Item:** DEEP-RESEARCH D15 (🔴 High) — CDC split-brain: R2.1 scaffold
(``infrastructure/cdc/``) vs legacy (``infrastructure/clients/external/cdc/``).
DSL импортировал concrete ``infrastructure.sources.cdc.CDCSource``, bypass'ило
Protocol-контракт.

**Solution:** ``core/cdc/registry.py`` (NEW) — ``get_cdc_source()`` factory
для всех 5 backends: ``poll`` / ``listen_notify`` / ``debezium`` / ``adapter`` /
``fake``. Возвращает ``CDCSource`` Protocol (canonical в ``core/cdc/source.py``).
Lazy import: optional deps (asyncpg/aiokafka) не required.

**DSL integration:** ``RouteBuilder.from_cdc_registry()`` (NEW) — preferred
path через factory. Legacy ``from_cdc`` / ``from_cdc_logical`` оставлены
для backward compat (split-brain consolidation, NOT deprecation).

**Files:**
- `src/backend/core/cdc/registry.py` (NEW, 175 LOC)
- `src/backend/core/cdc/__init__.py` (re-export factory)
- `src/backend/dsl/builders/sources_mixin/cdc_sources_mixin.py` (+50 LOC)
- `tests/unit/core/cdc/test_registry.py` (NEW, 10 tests + 1 SKIP)

**Pre-existing bug обнаружен:** legacy ``CDCClient.get_cdc_client()`` has
``_cdc_instance`` NameError (client.py:181). SKIP зафиксирован, real fix —
S102+ W1 backlog (1 item).

**Score impact:** 9.1 → 9.2 (D15 partial closure, registry).

---

## W2 — CDC integration tests (commit b51a7eab)

**Item:** coverage gap для ``from_cdc_registry`` DSL builder.

**Solution:** 8 integration tests в ``tests/unit/dsl/builders/test_cdc_registry_integration.py``
— construction для всех backends, ValueError propagation, end-to-end chain
с ``.dispatch_action()``, backward compat для legacy ``from_cdc`` /
``from_cdc_logical``.

**Regression:** 0 — 24 pre-existing CDC tests (cdc_capture /
cdc_postgres_logical) still pass.

---

## W3 — Docstring gate extension (commit 3918ad65)

**Item:** DEEP-RESEARCH D14 (🔴 High) — gate покрывал только 3 dirs.
services/entrypoints/infrastructure/ai были UNCOVERED.

**Solution:**
- ``.pre-commit-config.yaml`` — hook paths extended 3 → 8 dirs.
- ``tools/check_docstrings_allowlist.txt`` — 1658 → 1649 (net -9 entries
  from amnestied baseline + 8 NEW docstrings).
- 8 NEW docstrings distributed: core/tenancy, core/utils,
  entrypoints/webhook, services/workflows.

**Penalty:** pre-push hook теперь сканирует ~50% больше файлов (~8-12s
vs ~5s). Acceptable trade-off.

**CI lint.yml out of scope:** ``--strict`` без paths = exit 2 (typer
bug). Separate fix in S102+.

---

## W4 — V2 P0 #6 TenantMixin continuation (commit c631450d)

**Item:** DEEP-RESEARCH V2 P0 #6 (4/7 моделей tenant-isolated) — закрыть
оставшиеся 3 (OrderKind/DslSnapshot/WorkflowEvent).

**Solution:**
- Alembic migration ``a1b2c3d4e5f6`` (NEW): ADD COLUMN tenant_id +
  INDEX для ``dsl_snapshots`` + ``workflow_events``. Idempotent guards,
  online migration в PG 11+.
- ``DslSnapshot`` + ``WorkflowEvent`` — TenantMixin в MRO.

**Score:** 4/7 → 5/7 моделей tenant-isolated.

**Pre-existing failures (11 tests in test_pg_runner_backend.py /
test_versioning.py) НЕ regression** — verified на stashed WIP.

**Осталось:** 2/7 (OrderKind — lookup table, low risk; WorkflowInstance —
UUID PK, separate from DslSnapshot/WorkflowEvent).

---

## W5 — Closure (this ADR + CHANGELOG)

Final score:

| Domain | S100 | S101 |
|--------|------|------|
| D14 Docstrings | 7.5 | 8.0 (gate extended) |
| D15 CDC | 5.0 | 7.0 (registry, 1/3 split-brain) |
| V2 P0 #6 | 5.7 | 7.1 (5/7 моделей) |
| Overall | 9.1 | **9.2** |

**Real TODO backlog (post-S101):**
- 1 item: legacy ``CDCClient.get_cdc_client()`` bug fix
- 1 item: ``--strict`` exit 2 bug в CI
- 2/7 models remaining: OrderKind + WorkflowInstance (V2 P0 #6)
- 1 backlog: 1649 docstrings ratchet target -200/sprint (S102+)

5 commits, 4 closure items, score 9.1 → 9.2.
"""
