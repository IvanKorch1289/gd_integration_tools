# M6 Production Deployment Runbook (2026-09-01)

> **Generated**: Sprint 95 (M6 final docs).
> **Status**: DEFERRED — requires production environment.

## M6 done-критерий (per PRODUCTION_READINESS.md)

> "план доработки завершён, дальнейшие изменения — только по новым бизнес-требованиям"

## Pre-deployment checklist (Sprint 96+ production cycle)

### Step 1: Environment preparation
```bash
# Production env requirements
export ENVIRONMENT=production
export FEATURE_AUDIT_ENABLED=true
export FEATURE_PII_ENABLED=true
export FEATURE_TELEMETRY_ENABLED=true

# Required services
- PostgreSQL 14+ (with pgcrypto extension)
- Redis 7+ (with streams module)
- Kafka 3.5+ ИЛИ RabbitMQ 3.12+
- Vault 1.13+ (для secrets management)
- S3-совместимое хранилище (AWS S3, MinIO, Yandex Object Storage)
- OpenTelemetry collector (для tracing)
- Prometheus + Grafana
```

### Step 2: M6-#1: Run all 38 pre-prod-check gates

```bash
make pre-prod-check
# Ожидаемый результат: "All 38 gates passed" (или list of acceptable warnings)
```

Individual gates (partial list):
- 01 coverage ≥50% — **S88 baseline: 30.8%, partial** → need to verify overall
- 02 mypy ≤30 — **S89 baseline: 30+ errors, may need fixes**
- 03 layers — ✓ (S89 OK)
- 04 ruff strict — ✓ (S91 0 errors)
- 05 secrets — needs production secrets
- ... (33 more gates)

### Step 3: M6-#2: Run lint + type-check + test

```bash
make lint-strict
make type-check-strict
make test
# Ожидаемый результат: all green, ~360+ tests pass
```

### Step 4: M6-#3: Functional verification (curl)

```bash
make dev-light  # запуск в фоне
# Health checks
curl -sf http://localhost:8000/health
curl -sf http://localhost:8000/api/v1/admin/system-info
curl -if http://localhost:8000/api/v1/admin/feature-flags

# Auth flow
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "password": "test"}' | jq -r .token

# DSL dispatch
curl -X POST http://localhost:8000/api/v1/dsl/dispatch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "orders.get", "payload": {"order_id": 1}}'

# GraphQL
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "query { order(orderId: 1) { id isActive } }"}'
```

### Step 5: M6-#4: Browser verification

```
- Swagger UI: http://localhost:8000/docs — test 3-5 endpoints
- GraphQL Playground: http://localhost:8000/graphql — test queries
- Streamlit portal: http://localhost:8501 — open 5 pages
- DevTools Network: check headers, CORS, auth
```

### Step 6: M5-#10: Load test (500 RPS / p99 < 300ms)

```bash
# Install locust
pip install locust

# Run load test (against production-like env)
locust -f tests/load/health_endpoint.py --host=https://api.example.com --users=500 --spawn-rate=50 --run-time=5m --headless --html=load_test.html
```

**Done-критерий**: 500 RPS sustained, p99 < 300ms (per PRODUCTION_READINESS.md).

### Step 7: M6-#5: OWASP ZAP baseline scan

```bash
docker run -t owasp/zap2docker-stable zap-baseline.py -t https://api.example.com -r zap_report.html
# Ожидаемый результат: 0 high-risk alerts (medium допустимы с обоснованием)
```

### Step 8: M6-#6: Final STATUS sync

```bash
# Update docs/STATUS.md with verified metrics:
# - Coverage: from `coverage report` (final number)
# - Ruff: from `ruff check src/`
# - mypy: from `mypy src/` (если fixed)
# - locust: 500 RPS p99 = XX.Xms (from load test)
# - pip-audit: 0 active CVEs (diskcache ADR-0287 close)
```

### Step 9: Final milestone close

```bash
# Update docs/roadmap/PRODUCTION_READINESS.md:
# - All 6 milestones → CLOSED ✓
# - Set production-readiness = 100%
# - Add production deploy date
```

## Sprints 96+ (production deploy cycle)

1. **S96**: Setup production env, run M6-#1 (pre-prod-check 38 gates)
2. **S97**: M6-#2 (lint+type+test) + M6-#3 (cURL functional)
3. **S98**: M6-#4 (browser) + M6-#5 (OWASP ZAP)
4. **S99**: M5-#10 (load test 500 RPS) + M6-#6 (final STATUS sync)
5. **S100**: Final milestone close ceremony

## Time estimate

| Task | Estimate | Blocker |
|---|---|---|
| M6-#1 pre-prod-check | 1h | production env |
| M6-#2 lint+type+test | 4h | env setup |
| M6-#3 cURL verification | 4h | running dev-light |
| M6-#4 browser verification | 4h | running services |
| M6-#5 OWASP ZAP | 2h | public domain |
| M5-#10 load test | 4h | production traffic |
| M6-#6 STATUS sync | 1h | all M6 done |
| **Total** | **~20h** | production env |

## Sprint 96 entry point

When user runs `make dev-light` (Sprint 96+), use this runbook to complete M6.

Honest assessment: M6 требует running production env, cannot be closed
в autonomous mode. Deferred to dedicated deploy cycle (S96+).