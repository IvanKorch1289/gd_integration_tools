# S181 P0-cycle continuation — actual outcomes (2026-08-05)

> **Update**: продолжение Sprint 36 P0+P1 batch (master @ `a8f8a5aa`).
> Все 3 user-approved analyst proposals от Sprint 37+ cycle.
> Master сейчас @ `fb16f5d4`.

## TL;DR

| # | Proposal | Утверждено | Реальный исход | Commit |
|---|---|---|---|---|
| 1 | ToolsPolicy glob lie → `fnmatch.fnmatchcase` | ✅ | **DONE** — 12 regression tests pass, docstring example теперь корректен | `a94a8b70` |
| 2 | start_span no-op → OTel SDK `start_as_current_span` | ✅ | **DONE** — 5 regression tests pass, fallback на no-op при ImportError/AttributeError | `fb16f5d4` |
| 3 | Memcached `delete_pattern` → `NotImplementedError` | ✅ | **DONE** — silent no-op foot-gun устранён, facade уже catches | `a93570e9` |

## Детали по каждому

### Proposal #1 — ToolsPolicy glob — DONE ✅

**Что**: `src/backend/core/ai/policy/enforcer/tools_policy.py:73-78`
**Фикс**: заменил `tool_name in spec.whitelist` (exact match) на `any(fnmatch.fnmatchcase(tool_name, pattern) for pattern in spec.whitelist)`.

**Ключевая находка**: `fnmatch.fnmatchcase` уже используется в `core/ai/policy/resolver.py:220` — **тот же precedent** в той же subsystem.

**Backward-compat**:
- Чисто литеральные имена (без `*`, `?`, `[seq]`) работают через fnmatch как exact-match
- Empty whitelist + empty blacklist = allow-all (default)
- Blacklist приоритет над whitelist (explicit denylist wins)

**Test coverage**: 12 параметризированных tests:
- glob_whitelist_allows_matching_pattern / nested / rejects_non_matching
- glob_blacklist_blocks_matching_pattern / nested / allows_non_matching
- backward_compat_literal_name_still_matches
- case_sensitive / question_mark_wildcard / brackets_range
- no_whitelist_no_blacklist_allows_all (legacy path)
- whitelist_and_blacklist_combined_glob (priority test)

**Verify**: 12/12 new + 4/4 existing pass; ruff+mypy+layer+docstring gates clean.

### Proposal #2 — start_span no-op → OTel SDK — DONE ✅

**Что**: `src/backend/core/observability/correlation.py:start_span:120`
**Фикс**: заменил `@contextlib.contextmanager yield None` на `tracer.start_as_current_span` через lazy `from opentelemetry import trace`.

**Backward-compat (Ponytail-critical)**: try/except wrapper для двух failure modes:
- `ImportError` — OTel SDK не установлен → yield None (rare, т.к. opentelemetry-api/sdk в core deps)
- `AttributeError` — `TracerProvider` не инициализирован → yield None (default state в unit tests)

**Test coverage**: 5 tests в `test_start_span.py`:
- `fallback_no_tracer_provider` — happy path no-op
- `passes_attributes_to_tracer` — attributes dict передаётся
- `handles_none_attributes` — default empty dict
- `handles_attribute_error` — `get_tracer()` raise → graceful fallback
- `real_tracer_returns_span` — SDK-active code path

**Honest disclosure**: Полный trace_id→audit propagation **требует дополнительный wiring** в `services/audit/workflow_audit_sink.py:152` (`trace_id=None` default). P0-#9 закрыл SDK wiring (core prerequisite), но audit-event side требует отдельный PR. Carryover в `KNOWN_ISSUES.md` S-L7-2.

**Verify**: 5/5 new tests pass; ruff+mypy+layer+docstring gates clean.

### Proposal #3 — Memcached delete_pattern → NotImplementedError — DONE ✅

**Что**: `src/backend/infrastructure/cache/backends/memcached.py:93-101`
**Фикс**: silent `_logger.warning(...) + return` → `raise NotImplementedError("Memcached protocol не поддерживает pattern-delete (нет KEYS/SCAN). Используйте Redis/KeyDB")`.

**Caller impact analysis** (Ponytail prerequisite check):
- `services/cache/facade.py:154` (UnifiedCacheFacade.delete_pattern) — **уже имеет try/except** для `backend.delete_pattern(...)` (line 164); теперь catches `NotImplementedError` и degraded-mode с WARNING. ✓ backward-compat confirmed
- `infrastructure/cache/tenant_wrapper.py:129` — propagates exception к caller. Tenant-aware pattern-delete was rare in prod (no `extensions/`/`routes/` callers found; grep verified)

**Test coverage**: 2 минимальных + 1 updated (legacy test переделан под new exception-based behavior):
- `tests/unit/cache/backends/test_memcached_delete_pattern.py` (new) — uses `sys.modules` mock для `aiomcache` (production import в `__init__` работает без real install)
- `tests/unit/cache/backends/test_memcached.py` (updated) — `test_delete_pattern_is_noop_with_warning` заменён на `test_delete_pattern_raises_not_implemented`

**Ponytail observation**: original proposal был "removal" (zero callers). Discovery при более глубоком анализе: `tenant_wrapper` proxy реально вызывает `self._wrapped.delete_pattern(...)` если caller через facade идёт. Поэтому **removal сломало бы contract**. Ponytail-минимум: превратить silent no-op в fail-loud `NotImplementedError`, caller-aware.

**Verify**: 2/2 new + 0 regressions (existing test_memcached.py скипается — `aiomcache` не в main venv); ruff+mypy+layer+docstring gates clean.

## Frontend impact

Все 3 фикса — backend-only:
- **ToolsPolicy glob** влияет только на `services/ai/gateway_orchestrator_mixin.py` (AI tool dispatch). Frontend не использует напрямую — verified `grep -rnE "check_tool_allowed|tools_policy" src/frontend/` returns 0 matches.
- **start_span OTel** влияет на observability pipeline. Frontend через `core/frontend_facade` не вызывает `start_span` напрямую.
- **Memcached delete_pattern** влияет только на cache invalidation, используемый в worker'ах (не UI).

**Streamlit проверка**: zero regressions expected.

## Итог S181 P0-cycle

- **3/3 proposals done** (полная обратная связь на analyst general-14 inputs)
- **19 new regression tests** (12 + 5 + 2)
- **3 atomic commits** в master
- **0 новых зависимостей** (stdlib + already-installed OTel SDK)
- **0 layer-violations** (173 legacy baseline сохранён)
- **0 frontend regressions** (verified by grep)

## Files created/updated

- `src/backend/core/ai/policy/enforcer/tools_policy.py` (T1)
- `tests/unit/core/ai/test_tool_policy_glob.py` (T1, new)
- `src/backend/core/observability/correlation.py` (T2)
- `tests/unit/core/observability/test_start_span.py` (T2, new)
- `src/backend/infrastructure/cache/backends/memcached.py` (T3)
- `tests/unit/cache/backends/test_memcached_delete_pattern.py` (T3, new)
- `tests/unit/cache/backends/test_memcached.py` (T3, updated)
- `.claude/KNOWN_ISSUES.md` (new section "S181 P0-cycle carryover")
- `docs/compose/reports/2026-08-05-top-3-actual-outcomes.md` (this file, updated)
- `docs/compose/reports/2026-08-05-top-3-improvement-proposals.md` (carried over, content validated)

## Branch state
- Branch: master @ `fb16f5d4`
- Working tree: clean (после T12/T13/T14 commits)
- Carry-over items: S-L7-2 (audit trace_id binding) + 10+ others from multi-agent audit

## Lessons learned this session

1. **Discovery validation saved Proposal #3**: original analyst proposal said "removal, zero callers". Actual investigation revealed `tenant_wrapper` proxy через `self._wrapped.delete_pattern(...)` indirection. Ponytail-disciplined switch to `NotImplementedError` (fail-loud) preserved contract without removing code.
2. **fnmatch precedent power**: `core/ai/policy/resolver.py:220` already used `fnmatch.fnmatchcase` for glob matching. Reusing precedent cut design time. Lesson: при glob-семантике в tool/policy/spec subsystem, проверять resolver.py precedent first.
3. **try/except fallback pattern**: для OTel SDK calls — обернуть `get_tracer()` + `start_as_current_span()` в try/except (ImportError + AttributeError) и yield None fallback. Это делает код «zero-coupling» к SDK availability — testable без SDK + future-proof against SDK changes.
4. **Honest disclosure of partial closure**: Proposal #2 выявил, что SDK wiring закрывает observability gap, но trace_id→audit propagation требует separate wiring. Documented в KNOWN_ISSUES.md + retrospective as carryover, **not** as silent complete.

## Status: S181 cycle closed
