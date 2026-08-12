# Cycle 4 — baseline

- Date: 2026-08-06
- HEAD: `22e08a0d` (cycle-1/2/3 reapply commit; +1 over cycle-3 baseline `7f3d94a3`)
- Commit summary: 12 files changed, 313 insertions(+), 68 deletions(-)
- Working tree: clean (all cycle-1/2/3 source fixes committed); pre-existing drift (`M uv.lock` -15 svcs, `?? pip-audit.json`, `?? .blue_green.state`, untracked audit docs, untracked test files) — НЕ этому swarm.
- Layer checker: `python tools/check_layers.py --root src` → exit 0; **175 legacy / 0 new** (2274 files scanned).
- Security allowlist: `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → **27 active IDs** (cycle-4 D-AUDIT-02: 35→27; 8 stale CVE removed).
- Docstring gate: `make check-docstrings MAX_ALLOWED=0` → 0 missing (838 files).
- Streamlit: `pyproject.toml:137` `streamlit>=1.58.0,<2.0.0` (cycle-4 D-AUDIT-03).
- Smoke-тесты (8/8 PASS, .venv/bin/python):
  - T-1.4 multicast: ExecutionEngine() without route_registry ✓
  - T-1.4 redelivery: `except (TypeError, ValueError):` Python-3 syntax ✓
  - T-1.5 policy_mixin: inspect.signature dual-signature ✓
  - T-1.5 gateway_adapter: AIGatewayProductionWiringError fail-closed ✓
  - T-3.1 cachetools: TTLCache wrapped in asyncio.Lock ✓
  - T-W1-01 AuthenticationProviderUnavailableError import OK ✓
  - T-W1-05 cdc_routes: cdc_router.dependencies set ✓
  - T-W1-08 credit_pipeline: unknown_tenant branch in scoring_agent ✓

## Что осталось от cycle 1+2+3 (deferred, под фокус cycle 4)

### Cycle 1 (4 закрыто, 5 отложено — ВСЁ ещё отложено, кроме T-1.1 и T-2.1)
- T-1.1 composition root fix
- T-1.2 SSE/HITL auth (8 xfailed тестов)
- T-1.3 MQ DLQ data-loss
- T-2.1 reverse-layer cleanup
- T-4.1 text-RAG E2E test

### Cycle 2 (3 закрыто, 12 отложено)
- T-W1-02 CDC DLQ handoff failure
- T-W1-03 MQ subscribers ACK vs DLQ
- T-W1-04 composition root DI (critical path)
- T-W1-06 RagCachePrewarmer runtime + phantom fill_cache
- T-W1-07 SSE principal/permissions
- T-W2-01..04 layer track
- T-W3-01 tenacity library replacement
- T-W4-01 text-RAG E2E

### Cycle 3 (2 закрыто, 9 отложено)
- T-04 4-way CVE enforcement unification
- T-05 hardcoded shutdown timeout
- T-06 test-infra conftest
- T-08 TenantFacade kwargs fix
- T-09 credit_pipeline_v2 default consistency
- T-10 defusedxml drop-in
- T-11 organic feature

### Pre-existing residuals (не этому плану)
- `src/backend/services/ai/gateway_adapter.py:128-129` — `except Exception: pass` (cycle-1 critic flagged, cycle-2/3/4 plans явно НЕ переписывать)
- 1 pre-existing mypy error в `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54`
- 5 pre-existing failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (spacy/feature flag)

## Ограничения для cycle 4

- Phase 1 аналитики **обязаны перепроверить** все находки cycle 1+2+3, не считать их финальными.
- Аналитики читают только свой домен, не заимствуют выводы.
- Русские docstrings/comments не переводить.
- Числа не брать из cycle-1/2/3 markdown, проверять прогоном инструмента.
- Phase 1 запрещено менять source/lockfile/allowlist/s3.py/blue_green (8 правок уже закоммичены в HEAD 22e08a0d).
- Phase 1 сохраняет отчёт в `docs/audit/swarm-2026-08-06/cycle-4/phase-1/<NN>-<domain>.md`.
- **КРИТИЧНО**: все runtime-тесты через `.venv/bin/python -m pytest` (system Python не подключён к .venv).
