# Runbook: Token budget overage

> Owner: K4.

## Symptom

* Tenant получает HTTP 429 `{"error": "token_budget_exceeded"}`.
* Grafana `tenant_budget_breaches` спайк.
* User complains: AI chat не работает с конкретного аккаунта.

## Detection

```bash
curl http://<api>/api/v1/admin/budget/<tenant_id>/snapshot
# {"used": 1000050, "hard_limit": 1000000, "remaining": 0, "period": "daily"}
```

## Diagnosis

`TokenBudget` reserves estimated tokens до LLM-вызова + correction после.
Если usage > hard_limit → `BudgetExceeded` → 429.

Причины:
1. Tenant действительно превысил daily quota.
2. Bug в estimate_tokens (over-estimate).
3. Multiple parallel requests без queue → race за остаток.

## Mitigation

### Option A: reset budget (admin override)
```bash
curl -X POST http://<api>/api/v1/admin/budget/<tenant_id>/reset
```
Используется ТОЛЬКО для emergency или ошибок счётчика.

### Option B: bump plan limits
```python
# composition root
configs["bank-corp-enterprise"] = TokenBudgetConfig(
    soft_limit=20_000_000,  # было 10M
    hard_limit=200_000_000,  # было 100M
)
```

### Option C: temporary disable
```bash
kubectl set env deploy/<service> TENANT_TOKEN_BUDGET_ENABLED=false
```

### Option D: fail_mode=open при Redis-outage
Уже default в `TokenBudgetConfig`. Если Redis недоступен →
budget не проверяется, requests proceed.

## Verification

* Tenant snapshot: `used < hard_limit`.
* AI chat работает.
* Audit-event `token_budget.reset` логирован с operator name.

## Communication

При hard breach:
1. Email tenant admin с budget snapshot + action items.
2. Slack `#cs-tenant-alerts` с tenant_id + plan.
3. Open ticket в CRM (`bank-corp-enterprise upgrade discussion`).

## Postmortem

* Какой LLM call превысил threshold (model + input size).
* Был ли это spike или steady-state increase?
* Action items: lower estimate factor / chunked retrieval / per-route limits.
