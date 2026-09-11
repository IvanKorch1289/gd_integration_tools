# Runbook: feature-flag kill-switch playbook

**Wave**: `[wave:op-2/kill-switch]`
**Owner**: SRE + Security
**Last verified**: 2026-09-11
**Цель**: за ≤ 5 минут безопасно отключить любую фичу в production через feature flag без полного rollback релиза.

## Когда использовать

Этот playbook активируется при:

1. **Feature regression** — фича прошла CI, но в production вызывает рост 5xx, latency spike, memory leak, или corruption данных.
2. **External dependency failure** — partner API/SaaS/db изменил поведение; фича завязана на него.
3. **Security incident** — фича позволяет обход auth или утечку данных.
4. **Capacity exhaustion** — фича потребляет непропорционально много ресурсов (CPU, memory, MQ lag).
5. **Compliance rollback** — feature ошибочно включена в regulated environment.

## Не использовать для

- Полного отката релиза → см. `docs/runbooks/blue-green-rollback.md`.
- Изменения схемы БД → см. `docs/runbooks/migration-rollback.md`.
- Изменения в core/dsl engine → manual PR через `git revert` + deploy.

## Phase 0 — Триаж (≤ 2 минуты)

### Быстрая диагностика

```bash
# 1. Определить affected scope: tenant / global?
curl -s "$API_BASE/api/v1/admin/feature-flags" -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# 2. Проверить health метрики suspect flag.
curl -s "$PROMETHEUS/api/v1/query?query=feature_flag_eval_total{flag=<flag_name>}" | jq

# 3. Проверить recent error rate.
curl -s "$PROMETHEUS/api/v1/query?query=rate(http_requests_total{status=~'5..',route=~'<affected_route>'}[5m])" | jq
```

### Identify root cause (≤ 2 минут)

| Symptom | Likely flag | First action |
|---|---|---|
| 5xx spike только на одном route | `dsl_processor_<X>_enabled` | Смотреть feature flags этого route |
| Memory leak across workers | `ml_model_<X>_enabled` | Disable ML feature |
| Auth bypass reports | `auth_<X>_enabled` | **IMMEDIATE disable**, см. incident-response.md |
| External API timeout cascade | `partner_<X>_integration_enabled` | Disable + circuit breaker |
| Tenant-specific | `tenant_<X>_feature_enabled` | Disable per-tenant, not global |

## Phase 1 — Disable flag (≤ 1 минута)

### Способ A: Through API (preferred)

```bash
# Disable flag globally.
curl -X POST "$API_BASE/api/v1/admin/feature-flags/disable" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"flag": "<flag_name>", "reason": "<incident_id>", "operator": "<your_name>"}'

# Verify disabled.
curl -s "$API_BASE/api/v1/admin/feature-flags/<flag_name>" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.enabled'
# Expected: false
```

### Способ B: Environment variable (если API unavailable)

```bash
# 1. SSH to running pods.
kubectl exec -it deploy/gd-app -- /bin/bash

# 2. Edit config.
kubectl set env deploy/gd-app FEATURE_<FLAG_NAME>=false

# 3. Verify pods restart with new env.
kubectl rollout status deploy/gd-app

# 4. Verify flag state via metrics endpoint.
curl -s "$API_BASE/api/v1/health/feature-flags" | jq
```

### Способ C: Feature flag override file (emergency bypass)

```bash
# Только если API + kubectl НЕ доступны (extreme case).
# Требует direct filesystem access + service restart.

# 1. Write override file.
mkdir -p /etc/gd-integration/flags
cat > /etc/gd-integration/flags/overrides.json <<EOF
{
  "flags": {
    "<flag_name>": {
      "enabled": false,
      "reason": "<incident_id>",
      "operator": "<your_name>",
      "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    }
  }
}
EOF

# 2. Restart service.
systemctl restart gd-app
```

## Phase 2 — Verify (≤ 2 минут)

### Confirm feature disabled

```bash
# Check flag state.
curl -s "$API_BASE/api/v1/admin/feature-flags/<flag_name>" | jq

# Check error rate dropped.
curl -s "$PROMETHEUS/api/v1/query?query=rate(http_requests_total{status=~'5..',route=~'<affected_route>'}[1m])" | jq

# Check specific feature metrics zeroed out.
curl -s "$PROMETHEUS/api/v1/query?query=feature_flag_eval_total{flag='<flag_name>',result='enabled'}[5m]" | jq
# Expected: 0
```

### Confirm no new incidents

```bash
# Check Sentry for new errors post-disable.
curl -s "$SENTRY/api/0/projects/gd-integration/issues/?query=is:unresolved+since:5m" | jq

# Check logs for unexpected errors.
kubectl logs -l app=gd-app --since=2m | grep -i error | tail -20
```

## Phase 3 — Communicate (≤ 5 минут)

### Internal

```text
#incident channel template
[SEV-<X>] <flag_name> disabled at <timestamp> by <operator>
Reason: <incident_id>
Affected scope: <global|tenant_id|route_id>
Expected impact: <what this should fix>
Rollback plan: <when to re-enable + how>
Docs: <link to incident doc>
```

### Update status page (if user-facing)

```bash
# Post incident to status page.
curl -X POST "$STATUS_PAGE/api/v1/incidents" \
  -H "Authorization: Bearer $STATUS_TOKEN" \
  -d '{"name": "<feature> temporarily disabled", "severity": "minor", "status": "identified"}'
```

## Phase 4 — Postmortem (within 24 hours)

### Document

- Что именно сломалось и почему.
- Как обнаружили (alert, customer report, internal test).
- Почему НЕ обнаружили в CI/staging.
- Timeline: detect → triage → disable → verify → fix plan.
- Prevention: test gap, missing rollback test, alert, documentation.

### Permanent fix

1. Add regression test для случая, который привёл к инциденту.
2. Update feature flag documentation: conditions when to disable.
3. Consider tighter feature flag scope (default-OFF, narrower audience).
4. Add monitoring/alerts на critical metrics для этого flag.

### Re-enable plan (DO NOT auto re-enable)

```bash
# Re-enable только через change approval workflow.
# НЕ re-enable в peak hours.
# НЕ re-enable без rollback plan (if X → disable <flag>).

curl -X POST "$API_BASE/api/v1/admin/feature-flags/enable" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"flag": "<flag_name>", "reason": "<postmortem_link>", "operator": "<your_name>"}'
```

## Critical feature flags reference

Высокоимпактные флаги (disable в первую очередь):

| Flag | Scope | Impact if disabled |
|---|---|---|
| `granian_rsgi_mode_enabled` | global | Reverts to ASGI interface (perf impact, no breaking change) |
| `dlq_unified_enabled` | global | Reverts to per-broker DLQ (less unified telemetry) |
| `route_authz_requires_permission` | global | Disables route-level auth checks (EMERGENCY ONLY) |
| `gateway_orchestrator_enabled` | global | Bypasses orchestrator, uses simple dispatcher |
| `llm_provider_anthropic_enabled` | global | Switches AI agent to fallback provider |
| `cdc_postgres_logical_replication_enabled` | global | Stops CDC consumer (DB writes work, no downstream sync) |
| `saga_compensation_enabled` | global | Disables Saga rollback (transactions proceed without compensation) |

Безопасные для disable (low blast radius):

- `metrics_labels_redis_*`
- `cache_warmup_*`
- `dev_debug_toolbar`
- `experimental_*` (по определению)

## Tools и commands

### Быстрая проверка всех feature flags

```bash
# List all flags + state.
curl -s "$API_BASE/api/v1/admin/feature-flags" -H "Authorization: Bearer $ADMIN_TOKEN" | jq
```

### Bulk disable (multiple flags)

```bash
for flag in <flag1> <flag2> <flag3>; do
  curl -X POST "$API_BASE/api/v1/admin/feature-flags/disable" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"flag\": \"$flag\", \"reason\": \"<incident>\", \"operator\": \"$USER\"}"
done
```

### Verify flag change propagated

```bash
# Wait for all pods to pick up change (default 30s).
sleep 30

# Check effective flag state on each pod.
for pod in $(kubectl get pods -l app=gd-app -o name); do
  echo "=== $pod ==="
  kubectl exec $pod -- curl -s localhost:8000/api/v1/health/feature-flags | jq
done
```

## Anti-patterns

- ❌ Disable flag AND restart service одновременно (трудно различить эффект).
- ❌ Disable multiple flags at once без понимания зависимостей.
- ❌ Disable flag → forget to log → team investigates non-existent issue.
- ❌ Re-enable flag без postmortem и approval.
- ❌ Disable flag без notifying on-call (silent fix).
- ❌ Disable flag в dev/staging вместо prod (разное поведение).
- ❌ Use env var override как permanent solution.

## Связанные документы

- `docs/runbooks/incident-response.md` — General incident process.
- `docs/runbooks/blue-green-rollback.md` — Full release rollback.
- `docs/runbooks/feature-flag-rollout.md` — Enabling new features.
- `docs/runbooks/chaos-test-debug.md` — Test flag disable behavior under chaos.
- `src/backend/core/config/features/` — Feature flag definitions.

## Метрика готовности

Этот playbook работает если:

- ✅ On-call инженер может disable critical flag за ≤ 1 минуту.
- ✅ Disable НЕ требует coordinated deploy.
- ✅ Disable виден в metrics/logs/alerts за ≤ 30 секунд.
- ✅ Re-enable защищён approval workflow.
- ✅ Postmortem шаблон применяется ко всем disable events.
- ✅ Feature flag coverage ≥ 90% для production-critical features.

## Verification (открытие playbook)

Проверять каждый квартал:

```bash
# 1. Find suspect flag.
FLAG=$(curl -s "$API_BASE/api/v1/admin/feature-flags" | jq -r '.flags[] | select(.critical==true) | .name' | head -1)

# 2. Disable + verify.
curl -X POST "$API_BASE/api/v1/admin/feature-flags/disable" \
  -d "{\"flag\": \"$FLAG\", \"reason\": \"drill_$(date +%s)\", \"operator\": \"oncall\"}" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

sleep 30
curl -s "$API_BASE/api/v1/health/feature-flags/$FLAG" | jq

# 3. Re-enable.
curl -X POST "$API_BASE/api/v1/admin/feature-flags/enable" \
  -d "{\"flag\": \"$FLAG\", \"reason\": \"drill_end\", \"operator\": \"oncall\"}" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Track drill results в `docs/runbooks/drill-results.md`.

## References

- Google SRE Book, Ch. 12 "Effective Troubleshooting" + Ch. 27 "Reliable Product Launches at Scale".
- Martin Fowler, "Feature Toggles (aka Feature Flags)" — https://martinfowler.com/articles/featureToggles.html.
- Project ADR-0296 (kill-switch playbook requirement).
