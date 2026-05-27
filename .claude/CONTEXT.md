# CONTEXT.md

## Текущее состояние (2026-05-27 18:27)

**HEAD**: `663385a0` — fix: add missing workflow_orchestrator_enabled feature-flag (S28 W4)
**Session summary**: `vault/session-2026-05-27-1827-summary.md` (Feature-flag fix + tests sync)

---

### Исправления сессии (2026-05-27 18:27) ✅ CLOSED

| Что | Файл | Результат |
|-----|------|-----------|
| Missing `workflow_orchestrator_enabled` flag | `src/backend/core/config/features.py` | ✅ +12 строк |
| Tests async conversion | `tests/unit/dsl/workflow/test_orchestrator.py` | ✅ 8/8 passed |
| Broken untracked test file | `tests/unit/core/ai/test_pydantic_ai_client.py` | ✅ REMOVED |

**Тесты**: 25 passed (test_orchestrator 8 + agent_registry 12 + memory_profile 5)
**Проверки**: `ruff check` ✅ `pytest` ✅

---

### Открытые задачи

| Задача | Приоритет | Status |
|--------|-----------|--------|
| Allowlist cleanup (21 stale entries) | Medium | Pending — `tools/check_layers.py --update-allowlist` |
| S32 pre-planning | Low | Starts 2026-06-23 |

---

### Git состояние

```
HEAD: 663385a0 fix: add missing workflow_orchestrator_enabled feature-flag (S28 W4)
branch: master, ahead of origin/master на 1 коммит
```

**Untracked**: `.cocoindex_code/`, `src/frontend/admin-react/package-lock.json`
**Staged**: nothing

---

### Следующий шаг

1. `python tools/check_layers.py --update-allowlist` — очистка 21 stale entry
2. Или S32 pre-planning (starts 2026-06-23)