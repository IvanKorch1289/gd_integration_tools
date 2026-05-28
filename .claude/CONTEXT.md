# CONTEXT.md

## Текущее состояние (2026-05-28 ~12:49)

**HEAD**: `a21b5136` — feat(ml): S32 W3 ML model loader + MLPredictProcessor
**Предыдущая сессия**: `vault/session-2026-05-28-0000-summary.md`

---

### Сессия 2026-05-28-1249 — Tech Debt + S32 W1/W2 Assessment

**Выполнено:**

1. **`pydantic_ai_client.py`**: metrics pre-registration (`_register_metrics()`), `del output_type/deps`, удалён dead code (`_mock_result` + unreachable raise)

2. **`gateway.py`**: удалён дублирующий unreachable `logger.debug()` (gateway.py:669-671)

3. **`ml_predict.py`**: `asyncio` → top-level import, `context` silenced, artifact URI caching

4. **S32 W1/W2 Assessment**: Scaffold готов для W1 (metrics pre-reg) и W2 (LocalFSModelRegistry + find_model_by_capabilities + tests). Cost tracking `cost_usd=0.0` — всё ещё hardcoded.

| Коммит | Описание |
|--------|----------|
| `28f67d79` | [wave:s29/local-models-repository] ML Model Loader + LocalFSModelRegistry + MLPredictProcessor + tests |
| `a21b5136` | feat(ml): S32 W3 ML model loader + MLPredictProcessor |
| `f698260b` | feat(ai): S32 W2 model capability registry + dynamic routing |

**HEAD ahead of origin/master**: 4 коммита (`a21b5136` + `28f67d79` + `f698260b` + `b9a24991`)

---

### Связанные тесты (проверяны)

```bash
# Проверено в этой сессии:
make lint 2>&1 | grep -E "pydantic_ai_client\.py|ml_predict\.py|gateway\.py"
# → 0 новых ошибок (pre-existing F841 в gateway.py:540-546, S110 try-except-pass)

# test_pydantic_ai_client.py — existing tests pass (233 строки, 8 тестов)
# test_model_registry_w2.py — existing tests pass (model capability routing)
```

---

### Code review findings (эта сессия)

| Замечание | Severity | Status |
|-----------|----------|--------|
| S32 W1 metrics pre-registration | ✅ Done | `_register_metrics()` idempotent, 4 метрики |
| S32 W1 cost_usd=0.0 remain | ⚠️ Carryover | LiteLLM callback не проброшен в PydanticAIClient |
| gateway.py dead variables (budget/strategy) | Low | Pre-existing, not this session |
| ml_predict.py torch/numpy import-not-found | Low | Heavy deps, not installed in env |

---

### Открытые риски

| Риск | Severity | Notes |
|------|---------|-------|
| `torch.load(..., weights_only=False)` security | MEDIUM | S29 wave — требует audit |
| W1 cost_usd=0.0 — LiteLLM callback не проброшен | MEDIUM | Callback в LiteLLMGateway, нужен separate tracker |
| S29 backport conflict | MEDIUM | HEAD содержит 2 wave commits S29/S32,возможны конфликты |
| `src/backend/services/ai/ml/` untracked | LOW | Новая директория — проверить содержание |
| W3 MCP Gateway namespaces | LOW | Не начато, зависит от W2 DI |

---

### Следующий шаг (S32 W2 DI Integration)

**Priority 1**: DI wire-up для `LocalFSModelRegistry` + `CompositeModelRegistry`
- Регистрация в app lifecycle / composition root
- `find_model_by_capabilities()` в DI singleton `LiteLLMGateway`

**Priority 2**: LiteLLM Proxy URL support
- `litellm_proxy_url` в `LiteLLMGatewaySettings`
- LiteLLM Proxy endpoint вместо прямых провайдеров

**Priority 3**: Demo route validation — `ml_demo/` с fake model artifact
