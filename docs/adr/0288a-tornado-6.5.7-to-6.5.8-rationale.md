# ADR-0288: tornado 6.5.7 → 6.5.8 (CVE patch)

## Status
Accepted (2026-09-01)

## Context
`pip-audit` (S52 M3-#1) reveals:

| CVE | Title | Severity |
|---|---|---|
| GHSA-wwv5-g3v4-889x | `RequestHandler.set_cookie` mixed-case kwargs bypass | Medium |
| GHSA-8423-8fgw-73vq | `RequestHandler` form-encoded/multipart DoS (no body-size cap) | Medium |

Tornado 6.5.7 → 6.5.8 contains the fix.

## Decision
Bump tornado 6.5.7 → 6.5.8 via `uv lock --upgrade-package tornado`.

## Risk Analysis (per S53 swarm agent)

- **Direct tornado imports в gd_integration_tools**: 0 (`grep -rE 'tornado' src/backend/ → 0 matches`)
- **Transitive usage** (через `dask.distributed`, `jupyter_client`):
  - `src/backend/infrastructure/execution/dask_backend.py` (lazy import)
  - `src/backend/services/jupyter/execution_service/{papermill_backend,kernelspec,e2b_backend}.py`
- **Production HTTP framework**: FastAPI (ASGI). **Не** Tornado.
- **WebSocket**: `websockets` library. **Не** `tornado.websocket`.
- **Cookies**: JWT/Redis session. **Не** `RequestHandler.set_cookie`.

**CVE applicability**: theoretical-only. `tornado.web.RequestHandler` не используется в production paths. CVEs эксплуатируемы ТОЛЬКО если атакующий отправит HTTP-запрос к Tornado-handled endpoint — в gd_integration_tools таких endpoints нет.

**Real risk**: 0%. Bump — compliance/sbom hygiene, не actual security fix.

## Migration Strategy

1. `uv lock --upgrade-package tornado` (single-package, isolated blast radius)
2. Verification — минимальный test subset (10 unit tests + dask smoke, ~10 min):
   ```bash
   uv run python -c "import tornado; assert tornado.version == '6.5.8'"
   uv run pytest tests/unit/dsl/test_dask_compute_smoke.py tests/unit/dsl/builders/test_dask_mixin.py \
                tests/unit/services/jupyter/execution_service/test_papermill_factory_heartbeat.py \
                tests/unit/services/jupyter/execution_service/test_e2b_kernelspec.py \
                tests/unit/services/jupyter/test_hub_actions_contracts.py \
                tests/unit/services/jupyter/test_hub_run_orchestrator.py \
                tests/unit/dsl/engine/processors/test_notebook_jupyter.py \
                tests/unit/dsl/engine/processors/test_notebook_dsl.py \
                tests/unit/dsl/processors/test_notebook_di_singleton.py \
                -v --tb=short -m "not slow"
   make lint-strict
   make type-check
   ```
3. `uv run pip-audit tornado` → expect 0 vulns
4. Atomic commit `chore(deps): uv lock --upgrade-package tornado`

## Consequences

- ✅ Patch-level CVE cleared
- ✅ ADR-0288 compliance: patch level current
- ⚠️ Single-package upgrade минимизирует blast radius, но НЕ zero. Если dask/jupyter transitive tests fail → revert + defer to S54.
- ❌ Не касается `pyproject.toml` (tornado не pinned) — uv lock only.

## Alternatives Considered

- **Bulk upgrade tornado + pypdf + cryptography**: REJECTED (blend atomiticy, hard to blame single package if regression).
- **Defer to S54+**: REJECTED (low risk, ≤10 min validation cost).
- **Replace tornado entirely**: REJECTED (transitive use only, no direct replacement needed).

## Reviewer
Sprint 53 (M3-#3 + M3-#5).

## Related
- `docs/roadmap/M3_AUDIT_2026-09-01.md` — CVE inventory
- `docs/roadmap/SPRINT_53_PLAN.md` — full sprint plan
- `docs/adr/0287-diskcache-pyssec-2447-deferral.md` — sibling ADR (deferred, no fix)