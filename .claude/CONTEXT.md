# CONTEXT.md

## Текущее состояние (2026-05-28 ~15:28)

**HEAD**: `49bb8bcb` — docs: update CONTEXT.md post-S32 completion
**Предыдущая сессия**: `vault/session-2026-05-28-0000-summary.md`

---

### Сессия 2026-05-28 — S32 AI Platform Consolidation (ALL DONE ✅)

| Wave | Status | Commit |
|------|--------|--------|
| W1 | ✅ Metrics pre-registration | `pydantic_ai_client.py` |
| W2 | ✅ DI wire-up (LocalFSModelRegistry) | `setup_ai_2026.py` |
| W3 | ✅ AI namespace (ai., ml., rag., embed.) | `16f36d37` |
| W4 | ✅ `get_rag_cache_provider()` | `574af373` |
| W5 | ✅ Schema docfix (tokens_total OK) | `574af373` |

**HEAD ahead of origin/master**: 6+ коммитов

---

### Изменённые файлы (S32)

- `src/backend/core/ai/pydantic_ai_client.py` — metrics pre-reg, dead code removal
- `src/backend/plugins/composition/setup_ai_2026.py` — W2 DI wire-up
- `src/backend/entrypoints/mcp/namespaces/__init__.py` — AI_NAMESPACE
- `src/backend/entrypoints/mcp/namespaces/ai_mcp.py` — NEW
- `src/backend/entrypoints/mcp/mcp_server.py` — register_ai_tools()
- `src/backend/core/di/providers.py` — get_rag_cache_provider()
- `src/backend/core/audit/schema/ai_invocation.py` — docstring count fix

---

### Проверки

```bash
# AI namespace routing
python3 -c "from src.backend.entrypoints.mcp.namespaces import get_namespace_for_action; \
print(get_namespace_for_action('ai.search_web').name)"  # → ai

# Lint: 0 новых ошибок
make lint 2>&1 | grep -E "pydantic_ai_client|gateway.py|ml_predict|setup_ai_2026" | grep error
# → нет новых ошибок
```

---

### Открытые риски

| Риск | Severity | Notes |
|------|---------|-------|
| `torch.load(..., weights_only=False)` security | MEDIUM | Требует аудит |
| W1 cost_usd=0.0 — LiteLLM callback не проброшен | MEDIUM | Carryover |
| `src/backend/services/ai/ml/` untracked | LOW | Carryover |

---

### Следующий шаг

**S32 ALL DONE.**

Carryover items:
- W1 cost_usd tracking (LiteLLM callback propagate)
- Demo route `ml_demo/` с fake model artifact
- `torch.load(..., weights_only=False)` security audit
