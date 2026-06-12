# ADR-0164: Sprint 82 — Documentation Cookbooks Closure

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S82 (Documentation Cookbooks)
**Author**: Ivan (autonomous cycle)

## Context

`docs/cookbooks/` было пусто (P1 #10 из FINAL_REPORT_V2, направление #13).
Production users не имели operational recipes для новых features S73-S81:
- AI tools whitelist (P0-B)
- Multi-instance outbox claim
- E2B sandbox execution
- Circuit breaker middleware
- Pool health monitoring

## Decision

Создать `docs/cookbooks/` с 5+ рецептами в формате "Use Case → Solution → Recipe → Key Points".

### 1. AI Agent Tools Whitelist (cookbook 01)

Привязка S76 `AIPolicySpec.tools_whitelist` к реальному agent use case.
Фокус: как настроить policy.yaml + интегрировать в `agent_registry.py`.

### 2. Outbox Multi-Instance Claim (cookbook 02)

S72 per-row `SELECT-FOR-UPDATE-SKIP-LOCKED` pattern с worker_id lease.
Фокус: race-free claim + sweeper recovery + lease TTL tuning.

### 3. E2B Jupyter Sandbox (cookbook 03)

S75 `E2BExecutionBackend` + S74 factory + S75 KernelSpecDiscovery.
Фокус: safe AI code execution без risk для production Python.

### 4. Circuit Breaker Middleware (cookbook 04)

S81 `CircuitBreakerMiddleware` + per-service policy + observability.
Фокус: cascade failure prevention.

### 5. Pool Health Monitoring (cookbook 05)

S80 `PoolHealthMonitor` + LiteLLM registration + `/health/pools`.
Фокус: per-pool/per-tenant visibility для AI gateway.

## Consequences

### Positive
- Production users получают executable recipes для всех P0 features
- Pattern: use case → solution → code → pitfalls → related
- New cookbok per sprint становится default practice

### Negative
- 5 docs файлов требуют maintenance (но <2% от sprint capacity)
- При изменении API нужно обновлять cookbook (S79+ practice: cookbook обновляется в feature PR)

## Files Changed

- `docs/cookbooks/README.md` (W1)
- `docs/cookbooks/01-ai-agent-tools-whitelist.md` (W2)
- `docs/cookbooks/02-outbox-multi-instance-claim.md` (W2)
- `docs/cookbooks/03-e2b-jupyter-sandbox.md` (W3)
- `docs/cookbooks/04-circuit-breaker-middleware.md` (W3)
- `docs/cookbooks/05-pool-health-monitoring.md` (W4)
- `CHANGELOG.md` (W5)
- `.shared/context/TECH_DEBT.md` (W5)

## Related ADRs

- ADR-0155 (S73 P0-A SyntaxError closure)
- ADR-0156 (S74 papermill/factory/heartbeat)
- ADR-0157 (S75 E2B/kernelspec)
- ADR-0158 (S76 tools whitelist)
- ADR-0159 (S77 AI policy DSL)
- ADR-0160 (S78 CORS/XSRF)
- ADR-0161 (S79 capability gate integration)
- ADR-0162 (S80 LiteLLM pool)
- ADR-0163 (S81 circuit breaker)

## Outcome

- **P1 #10 (cookbooks) CLOSED**
- 6 production-ready recipes covering все 4 P0 + 3 P1 features S73-S81
- Pattern: каждый новый P0 feature в S83+ автоматически получает cookbook
