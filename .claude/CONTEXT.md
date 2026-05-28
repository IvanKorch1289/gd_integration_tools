# CONTEXT.md

## Текущее состояние (2026-05-28 ~12:45)

**HEAD**: `365a8682` — [wave:s34/w1] Sphinx auto-api: narrow scope core/dsl/engine/core/interfaces
**Предыдущая сессия**: `vault/session-2026-05-28-0000-summary.md`

---

### Сессия 2026-05-28 — S29/S32 ML + MCP Completion (ALL DONE ✅)

**S29 W1+W2+W3**: local models repository — MLModelLoader + LocalFSModelRegistry + MLPredictProcessor
**S32 W3**: MCP AI namespace (`ai_mcp.py`, `AI_NAMESPACE` prefixes ai./ml./rag./embed.)
**Review fixes**: ai_mcp null guard, ml_predict async def fix, joblib importorskip

| Коммит | Описание |
|--------|----------|
| `856e8f2c` | [wave:s29] Migrate MLModelLoader: core/ai/ → services/ai/ml/ |
| `ae84bf5e` | refactor(ai): move asynccontextmanager import to top-level |
| `16f36d37` | [wave:s32/w3] MCP Gateway AI namespace (ADR-NEW-23) |
| `f712e7b0` | feat(mcp): add AI namespace for ML/RAG/embed actions |
| `365a8682` | [wave:s34/w1] Sphinx auto-api scope fix (graphify hook) |

**HEAD ahead of origin/master**: 6+ коммитов

---

### Новые файлы (S29/S32)

- `src/backend/core/interfaces/ml_model_loader.py` — Protocol
- `src/backend/services/ai/ml/__init__.py` — module init
- `src/backend/services/ai/ml/model_loader.py` — MLModelLoader (LRU cache, async loading)
- `src/backend/entrypoints/mcp/namespaces/ai_mcp.py` — AI namespace MCP tools

---

### Баги исправлены (code review)

1. **`ai_mcp.py` null result guard**: `dispatch()` returning `None` → `{"error": "action_returned_null"}` (был silent JSON null)
2. **`ml_predict.py` async fix**: `_resolve_artifact_uri()` → `async def` (run_until_complete в работающем loop → RuntimeError)
3. **`joblib` tests**: `pytest.importorskip("joblib")` → graceful skip без ML-стека

---

### Проверки

```bash
# ML component tests
uv run python -m pytest \
  tests/unit/core/ai/test_ml_model_loader.py \
  tests/unit/services/ai/model_registry/test_local_fs_backend.py \
  tests/unit/dsl/engine/processors/test_ml_predict.py -q
# Result: 35 passed, 3 skipped (joblib unavailable), 0 failed

# Lint (ml_predict, ai_mcp, tests)
uv run ruff check \
  src/backend/dsl/engine/processors/ml_predict.py \
  src/backend/entrypoints/mcp/namespaces/ai_mcp.py \
  tests/unit/dsl/engine/processors/test_ml_predict.py \
  tests/unit/core/ai/test_ml_model_loader.py --fix
# All clean
```

---

### Открытые риски

| Риск | Severity | Notes |
|------|---------|-------|
| `torch.load(..., weights_only=False)` security | MEDIUM | S29 wave — requires separate audit |
| W1 cost_usd=0.0 — LiteLLM callback не проброшен | MEDIUM | Callback в LiteLLMGateway, нужен separate tracker |
| `local_fs_backend.py` mypy lambda error | LOW | Pre-existing, not introduced this session |
| `docs/conf.py` S34 W1 autoapi | LOW | Graphify hook auto-committed — belongs to future S34 |

---

### Следующий шаг

**S33** (стартует 2026-07-07) или carryover items:
- W1 cost_usd tracking (LiteLLM callback propagate)
- Demo route `ml_demo/` с fake model artifact
- `torch.load(..., weights_only=False)` security audit
