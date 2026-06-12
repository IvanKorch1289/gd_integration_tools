# ADR-0175: Sprint 93 Wave 1 — Cleanup + Critical Fixes

**Status:** Accepted
**Date:** 2026-06-12
**Sprint:** 93 (Wave 1 of 5)
**Author:** Assistant (autonomous cycle, follow-up на DEEP-RESEARCH 2026-06-12)

## Context

DEEP-RESEARCH анализ (2026-06-12, `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md`)
выявил 4 critical gaps + cross-cutting concerns. S93 W1 закрывает 5 low-risk,
high-impact задач (cleanup + critical bug fix + 2 layer violation fixes + 1 DI refactor).

## Решения

### W1-C1: core/di/providers/cache.py → entrypoints violation (CRITICAL)

**Проблема:** `core/di/providers/cache.py:130` импортировал `_get_three_tier_cache`
из `entrypoints/api/v1/endpoints/rag_cache_admin.py` — грубейшее нарушение
layer policy (core → entrypoints).

**Решение:**
- New core facade: `core/di/app_state.get_three_tier_rag_cache_from_state()`
- `cache.py` использует facade (lazy import для сохранения circular-safety)
- Endpoint shim: `_get_three_tier_cache = get_three_tier_rag_cache_from_state` (backward-compat)
- TODO(S94): удалить shim после миграции callsite'ов

**Validation:** `python tools/check_layers.py` → 0 новых (186 legacy, было 186 → 185 после
cleanup stale записей в allowlist).

### W1-C7: NeMo guard — критический NameError bug + warning + fallback

**Проблема:** `input_guard_mixin.py` использовал `logger` БЕЗ ИМПОРТА. Любой вызов
`_guard_input_one("nemo:...")` падал с `NameError: name 'logger' is not defined`.
Никто не ловил — 0 тестов на этот код.

**Решение:**
- Add import: `from src.backend.core.logging import get_logger`
- Add module-level: `logger = get_logger(__name__)`
- `logger.debug` → `logger.warning` для NeMo skip (visibility)
- New fallback map `_NEMO_TO_LLM_GUARD_FALLBACK`:
  - `nemo:colang:topics` → `llm_guard:BanTopics`
  - `nemo:colang:sensitive` → `llm_guard:Sensitive`
  - `nemo:moderation` → `llm_guard:PromptInjection`
  - `nemo:prompt_injection` → `llm_guard:PromptInjection`
- Fallback delegates к `_guard_input_llm_guard` с mapped GuardRef
- `category="policy_degradation"` для monitoring/alerting

### W1-C6: NotebookExecutionService → singleton via DI

**Проблема:** 3 processor-а (`notebook_dsl`, `notebook_execute`, `notebook_export`)
создавали `NotebookExecutionService(jupyter_hub_settings)` в `__init__` — каждый
processor instance получал свой service (no shared connection pool, no singleton).

**Решение:**
- New: `src/backend/core/di/providers/jupyter.py` с:
  - `get_notebook_execution_service_provider()` — singleton с `_overrides` dict
  - `set_notebook_execution_service_provider()` — test-override
  - `reset_notebook_execution_service_overrides()` — test-isolation
- 3 процессора обновлены: `__init__` хранит только config, `process()` lazy-resolves

### W1-C29: L2 RAG semantic cache — default ON

**Проблема:** `three_tier.py:29` имел `l2_enabled: bool = False` default. RAG cache
фактически работал как 2-tier. L2 (Qdrant-based) даёт semantic recall при промахе L1.

**Решение:** Flip default на `True`. Безопасно, т.к.:
- `L2SemanticRagCache._ensure_client()` — lazy + try/except
- Если Qdrant недоступен → `_client = None` → `get()` возвращает `None` (no errors)
- Существующие тесты используют explicit `l2_enabled=...` → default change не ломает

### W1-C30: Удалить 2 dead demo routes

**Проверено** (grep по src/, tests/, extensions/):
- `test_mf` — 0 references → DEAD
- `credit_check_demo` — 0 references → DEAD (S27 W3/W4 PoC артефакт)
- `health_proxy_demo` — referenced в `tests/unit/dsl/route/test_routes_v11_discovery.py` → ОСТАВЛЕН

**Удалено:** 5 файлов (2 manifests + 3 dsl/builder файла)

## Метрики (baseline → result)

| Метрика | S92 W5 | S93 W1 | Δ |
|---------|--------|--------|---|
| Layer violations (new) | 0 | 0 | 0 |
| Layer violations (legacy) | 189 | 186 | -3 (stale cleanup) |
| Docstring violations | 586 | 586 | 0 (deferred to S93 W3) |
| Dead demo routes | 3 candidates | 1 (`health_proxy_demo`) | -2 |
| stdlib logging files | 24+20 | 24+20 | 0 (deferred to S93 W4) |
| Critical bugs (NameError) | 1 (NeMo guard) | 0 | -1 |
| NotebookService singletons | 1 per processor | 1 per process | shared |
| Test count (S93 W1 NEW) | 10777 | 10790 | +13 (4 NeMo + 3 cache + 5 notebook + 1 ... = 13) |

## Следующие шаги (S93 W2-W5)

- **W2:** NotebookService уже DI-singleton. C11 (sys.path.insert в Streamlit),
  C25/C26 (4× retry/CB consolidation → ResilienceCoordinator facade).
- **W3:** AuthGateway facade (12+ locations → 1).
- **W4:** PollCDCBackend реализация, stdlib logging codemod (24+20 → 0).
- **W5:** DSL features (from_sse, fork_join, db_insert/upsert/delete) + closure.

## Lessons Learned

1. **V2 P0 #5 был resolved в S88**, но НОВЫЕ violations появляются
   (comment-based detection в cache.py:130 — comment текст триггерил linter).
2. **NameError в `input_guard_mixin.py`** — 0 тестов на этот файл = баг прожил
   N спринтов. Регрессионный тест + AST coverage gate для policy-critical paths.
3. **`health_proxy_demo` referenced в tests** — нельзя удалять "по V2 claims" без
   факт-чека. V2 не покрыл test usage. DEEP-RESEARCH spot-check поймал.

## References

- DEEP-RESEARCH 2026-06-12: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md`
- V2 P0: `analysis/v2/FINAL_REPORT_V2.md`
- ADR-0169 (S87 reverification): `docs/adr/0169-sprint-87-v2-p0-reverification.md`
- Master prompt: `gap-analysis/MASTER-PROMPT-factcheck-plan-execute.md`
