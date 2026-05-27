# CONTEXT.md

## Текущее состояние (2026-05-27 18:22)

**HEAD**: `df351e26` — feat(testkit): add src/testkit/ public API for plugin authors (S19 K5 W3)
**Session summary**: `vault/session-2026-05-27-1812-summary.md` (Project Structure + Deferred Tasks Analysis)

---

### Project Structure Cleanup (2026-05-27) ✅ CLOSED

| Что | Результат |
|-----|-----------|
| `src/backend/testkit/` stub | ✅ REMOVED (duplicate of `/testkit/`) |
| `src/backend/windows_worker/` empty stub | ✅ REMOVED via `git clean -fd` |
| T5 layer violations (57 import violations) | **DEFERRED** — needs separate wave, ALL project plugins use `src.backend.*` imports |
| `plugins/composition/` fate (T4.1) | **DEFERRED** — 2705 LOC composition root, NOT a plugin, requires separate ADR |

---

### S27 Architecture Violations Migration ✅ DONE

| Что | Файлы | Результат |
|-----|-------|-----------|
| TYPE_CHECKING detection | `tools/check_layers.py` | ✅ DLQEnvelope violation fixed |
| Lazy-import detection (bridge pattern) | `tools/check_layers.py` | ✅ bypass runtime-only infra imports |
| CircuitBreakerMetricsRecorder protocol | `core/interfaces/observability.py` | ✅ +2 protocols added |
| CorrelationIdProvider protocol | `core/interfaces/observability.py` | ✅ +2 protocols added |

**Allowlist**: 3 entries eliminated, 21 stale pending cleanup (→ `--update-allowlist`)

---

### Code Review Findings (max effort, 2026-05-27)

Проанализированы: `pydantic_ai_client.py`, `features.py`, `test_orchestrator.py`

| Находка | Severity | Status |
|---------|----------|--------|
| `gateway: Any` typing | Important (80%) | Deferred (linter revert) |
| Lambda-mocking private method | Minor (80%) | Deferred (needs mock refactor) |
| `_mock_result()` unused | Info (65%) | Low priority |
| JMESPath context inconsistency | Minor (65%) | Not a bug |

---

### Следующий шаг

1. **Commit unstaged changes** or revert:
   - `src/backend/core/ai/pydantic_ai_client.py`
   - `src/backend/core/config/features.py`
   - `tests/unit/dsl/workflow/test_orchestrator.py`

2. **T5 wave** — separate session for 57 layer violations fix:
   - Requires global codemod or wave with all plugin authors
   - ALL plugins use `src.backend.*` imports (not just core_entities)

3. **T4.1 ADR** — composition root doesn't belong in `extensions/`:
   - `plugins/composition/` stays in `src/backend/plugins/`
   - Write ADR documenting this decision

---

### Открытые риски

| Риск | Уровень |
|------|---------|
| T5 layer violations: ALL plugins use `src.backend.*` | HIGH → separate wave needed |
| Composition root (`src/backend/plugins/composition/`) vs `extensions/example_plugin/` | MEDIUM → needs ADR |
| 21 stale entries in allowlist | HIGH → `python tools/check_layers.py --update-allowlist` |

---

## Проверки (current session)

```bash
make lint        # ✅ Soft lint complete (pre-existing Vulture warnings)
make type-check  # ⚠️ 806 errors pre-existing (not from our changes)
make routes      # Not run in this session
```
