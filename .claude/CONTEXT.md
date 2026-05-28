# CONTEXT.md

## Текущее состояние (2026-05-28 ~00:00)

**HEAD**: `f698260b` — feat(ai): S32 W2 model capability registry + dynamic routing
**Предыдущая сессия**: `vault/session-2026-05-28-0000-summary.md`

---

### Сессия 2026-05-28 итоги

| Коммит | Описание |
|--------|----------|
| `f698260b` | feat(ai): S32 W2 model capability registry + dynamic routing |

**HEAD ahead of origin/master**: 2 коммита (`f698260b` + `b9a24991`)

---

### Связанные тесты (все passing)

```
uv run pytest tests/unit/services/ai/test_model_registry_w2.py \
  tests/unit/services/ai/test_model_registry.py \
  tests/unit/services/ai/test_model_registry_composite.py \
  tests/unit/core/ai/test_pydantic_ai_client.py -q
# → 42 passed, 13 warnings
```

**Ruff**: `All checks passed` на всех изменённых файлах.

---

### Code review findings

| Замечание | Severity | Status |
|-----------|----------|--------|
| Substring allowlist bypass в `desktop_rpa_handler.py` | Medium | ✅ Исправлен (`ntpath.basename` + `.rstrip(".exe")`) |
| 3 функции без docstrings (windows_worker/testkit/services/rpa) | Low | ✅ Добавлены docstrings |

---

### Открытые риски

| Риск | Severity | Notes |
|------|---------|-------|
| `ml_model_loader.py` / `ml_predict.py` — `torch.load(..., weights_only=False)` | MEDIUM | Untracked файлы из параллельной сессии. Path traversal + unsafe deserialization. Требует отдельного исследования. |
| DI wire-up для `model_registry` в `LiteLLMGateway` | LOW | API готово, wire-up — follow-up wave |

---

### Git состояние

```
HEAD: f698260b feat(ai): S32 W2 model capability registry + dynamic routing
branch: master, ahead of origin/master на 2 коммита
```

**Untracked** (параллельная сессия):
```
src/backend/core/ai/ml_model_loader.py     ⚠️ MEDIUM: torch.load unsafe
src/backend/dsl/engine/processors/ml_predict.py ⚠️ MEDIUM: path traversal + torch.load unsafe
src/backend/services/ai/model_registry/local_fs_backend.py
routes/ml_demo/ml_demo.dsl.yaml
routes/ml_demo/route.toml
```

---

### Следующий шаг

- [MEDIUM PRIORITY] Исследовать `ml_model_loader.py` / `ml_predict.py` — определить exploitability path traversal + unsafe deserialization
- S32 W3 — MCP Gateway domain namespaces (PLANNED)
- `git push` (2 коммита ahead of origin/master)

---

### S32 Waves status

| Wave | Task | Status |
|------|------|--------|
| w1 | PydanticAI unified client (model router → AIGateway) | ✅ DONE |
| w2 | LiteLLM Proxy integration + model registry | ✅ DONE |
| w3 | MCP Gateway domain namespaces | 🟡 PLANNED |
| w4 | Unified RAG cache 3-level | 🟡 PLANNED |
| w5 | AI Audit Unified Schema | 🟡 PLANNED |
