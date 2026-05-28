# CONTEXT.md

## Текущее состояние (2026-05-28 ~16:15)

**HEAD**: `8e8820f1` — docs: update CONTEXT.md — S32 closure + tech debt session
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

**Параллельная сессия security fix**:
- `fac49e95` — fix(security): path traversal в LocalFSModelRegistry._model_dir()
- `352b88e0` — fix(ai): _AuditContext audit_service passthrough + pipeline tests

**HEAD ahead of origin/master**: 10+ коммитов

---

### Tech debt исправлено (эта сессия)

- `gateway.py` — duplicate unreachable logger.debug removal
- `pydantic_ai_client.py` — metrics pre-reg, del output_type/deps, мёртвый код удалён
- `ml_predict.py` — asyncio import, context silenced

---

### Проверки

```bash
# AI namespace routing
python3 -c "from src.backend.entrypoints.mcp.namespaces import get_namespace_for_action; \
print(get_namespace_for_action('ai.search_web').name)"  # → ai

# Lint: 0 новых ошибок
make lint 2>&1 | grep error | grep -v "pre-existing"  # → нет новых
```

---

### Открытые риски

| Риск | Severity | Notes |
|------|---------|-------|
| `torch.load(..., weights_only=False)` security | HIGH | Требует ADR |
| W1 cost_usd=0.0 — LiteLLM callback не проброшен | MEDIUM | Carryover |
| Coverage 58% vs 75% target | MEDIUM | Need targeted tests |

---

### Следующий шаг

**S32 ALL DONE. S33 ready to start.**

Next sprint: **S33** — DX Wizards, CLI tooling, codegen
