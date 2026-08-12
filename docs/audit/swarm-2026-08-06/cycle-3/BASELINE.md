# Cycle 3 — baseline

- Date: 2026-08-06
- HEAD: `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` (+1 от cycle-2 baseline `ca5bff93` — cycle retrospective commit)
- Working tree: 14 modified files (cycle-1 uncommitted: 5 source + 4 test + 1 preflight; cycle-2 uncommitted: 4 source + 2 test + 1 audit doc; + `M uv.lock` pre-existing -15 svcs) + 8 untracked. Все cycle-1/cycle-2 Phase 4 правки и `tools/cycle-1-preflight.sh` НЕ закоммичены. Роу cycle 3 не должен их ровнить — developer commit step.
- Pre-existing drift: `M uv.lock` (-15 svcs), `?? pip-audit.json`, `?? .blue_green.state` — НЕ атрибутируется рою, не трогать.
- Layer checker: `python tools/check_layers.py --root src` → exit 0; **175 legacy / 0 new** (2274 files scanned).
- Security allowlist: `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → **35 active IDs** (стабильно).
- Docstring gate: `make check-docstrings MAX_ALLOWED=0` → 0 missing (838 files).
- Environment: `python -c "import prometheus_client" / fastapi / hypothesis` → `ModuleNotFoundError` (debian system Python, не подключён к `.venv`). Reviewer cycle 2 указывал на это как pre-existing environment state. `.venv/lib/python3.14/site-packages` содержит `prometheus_client-0.26.0.dist-info`, `fastapi-*`, `hypothesis-6.165.1.dist-info` (то есть пакеты установлены в venv, но reviewer запускал pytest не из venv).

## Что осталось от cycle 1 + cycle 2 (deferred, под фокус cycle 3)

### Cycle 1 (4 закрыто, 5 отложено)
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

### Pre-existing residuals
- `src/backend/services/ai/gateway_adapter.py:128-129` — `except Exception: pass` (cycle-1 critic flagged, cycle-2 plan НЕ переписывать; test-фиксация отложена)
- 5 uncommitted cycle-1 правок (T-0.1, T-1.4, T-1.5, T-3.1)
- 3 uncommitted cycle-2 правки (T-W1-01, T-W1-05, T-W1-08)
- 1 pre-existing mypy error в `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54`
- 5 pre-existing failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (spacy/feature flag)
- 1 pre-existing ruff I001+W292 в cycle-2 test files (auto-fixable)
- 1 pre-existing ruff line-length в `test_scoring_fail_closed.py:32` (auto-fixable)
- Test environment: pytest collection требует активации `.venv` (bin/pytest или `source .venv/bin/activate`)

## Ограничения для cycle 3

- Phase 1 аналитики **обязаны перепроверить** все находки cycle 1 + cycle 2, не считать их финальными.
- Аналитики читают только свой домен, не заимствуют выводы.
- Русские docstrings/comments не переводить.
- Числа не брать из cycle-1/cycle-2 markdown, проверять прогоном инструмента.
- Phase 1 запрещено менять source/lockfile/allowlist/s3.py/blue_green.
- Phase 1 сохраняет отчёт в `docs/audit/swarm-2026-08-06/cycle-3/phase-1/<NN>-<domain>.md`.
- **Новое в cycle 3**: аналитики ОБЯЗАНЫ явно тестировать pytest с активированным `.venv` (через `.venv/bin/python` или `source .venv/bin/activate`) иначе reviewer-FAIL повторится. Документировать в отчёте какой Python-интерпретатор использовался.
- **Новое в cycle 3**: предпринять targeted runtime test в `.venv/bin/python -m pytest <path>` для подтверждения real-runtime assertion (не AsyncMock) и проверки test-masking issues из cycle 2 PHASE-2 §5.3.
