#!/usr/bin/env bash
# verify_s13_phase4_readiness.sh — pre-flight check для S13 Phase 4 staging rollout.
#
# Per docs/security/S13_PHASE4_STAGING_ROLLOUT_RUNBOOK.md:
# - Phase 1: Dev (3-day soak)
# - Phase 2: Staging (5-day soak)
# - Phase 3: Production canary (10% → 50% → 100%)
#
# This script verifies the code-side prerequisites BEFORE enabling
# circuit_breaker_use_registry flag:
#   1. Feature flag exists in config
#   2. Middleware reads flag correctly
#   3. BreakerPolicyAdapter wired
#   4. Prometheus metrics emitted
#   5. Sentinel support enabled (for multi-pod)
#
# Usage:
#   ./scripts/verify_s13_phase4_readiness.sh dev       # pre-flight for dev rollout
#   ./scripts/verify_s13_phase4_readiness.sh staging   # pre-flight for staging rollout
#   ./scripts/verify_s13_phase4_readiness.sh prod      # pre-flight for prod rollout
#
# Exit codes:
#   0 — все checks pass (ready for rollout)
#   1 — pre-flight check fail
#   2 — environment error (python не найден, etc.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

ENVIRONMENT="${1:-dev}"

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

note()  { printf "\033[36m[note]\033[0m  %s\n" "$*"; }
pass()  { printf "\033[32m[pass]\033[0m  %s\n" "$*"; }
fail()  { printf "\033[31m[fail]\033[0m  %s\n" "$*" >&2; }
header(){ printf "\n\033[1m== %s ==\033[0m\n" "$*"; }

VENV_PY=".venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
    fail "Python venv not found at $VENV_PY"
    exit 2
fi

# ──────────────────────────────────────────────────────────────────────
# Check 1: Circuit breaker feature flag exists in config
# ──────────────────────────────────────────────────────────────────────

header "Check 1: circuit_breaker_use_registry flag in RedisSettings"

if grep -q "circuit_breaker_use_registry" src/backend/core/config/features/resilience.py; then
    pass "circuit_breaker_use_registry flag exists in resilience.py"
else
    fail "circuit_breaker_use_registry flag NOT FOUND — Phase 4 cannot proceed"
    exit 1
fi

if grep -q "circuit_breaker_use_registry" src/backend/entrypoints/middlewares/circuit_breaker.py; then
    pass "Middleware reads circuit_breaker_use_registry flag"
else
    fail "Middleware does NOT read the flag — Phase 4 cannot proceed"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 2: BreakerPolicyAdapter exists
# ──────────────────────────────────────────────────────────────────────

header "Check 2: BreakerPolicyAdapter wired"

if [[ -f "src/backend/core/resilience/breaker_policy_adapter.py" ]]; then
    pass "BreakerPolicyAdapter present at src/backend/core/resilience/breaker_policy_adapter.py"
else
    fail "BreakerPolicyAdapter NOT FOUND — Phase 4 cannot proceed"
    exit 1
fi

if grep -q "BreakerPolicyAdapter" src/backend/entrypoints/middlewares/circuit_breaker.py; then
    pass "Middleware imports BreakerPolicyAdapter"
else
    fail "Middleware does NOT use BreakerPolicyAdapter — registry path won't work"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 3: Prometheus metrics wired (S58)
# ──────────────────────────────────────────────────────────────────────

header "Check 3: Prometheus metrics for circuit breaker"

if grep -q "_record_breaker_metric" src/backend/entrypoints/middlewares/circuit_breaker.py; then
    pass "Prometheus metric emission wired (S58)"
else
    fail "Prometheus metrics NOT wired — Grafana dashboards will have no data"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 4: Sentinel support enabled (S59)
# ──────────────────────────────────────────────────────────────────────

header "Check 4: Sentinel support in RedisSettings"

if grep -q "sentinel_mode" src/backend/core/config/services/cache.py; then
    pass "Sentinel mode field exists (S59 W2)"
else
    fail "Sentinel mode NOT configured — multi-pod HA unavailable"
    exit 1
fi

if grep -q "redis.asyncio.sentinel" src/backend/infrastructure/clients/storage/redis/connection_mixin.py; then
    pass "Sentinel connection path implemented (S59 W2)"
else
    fail "Sentinel connection path NOT implemented"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 5: Tests pass
# ──────────────────────────────────────────────────────────────────────

header "Check 5: Circuit breaker tests pass"

note "Running circuit breaker test suite..."
if timeout 120 uv run pytest tests/unit/entrypoints/middlewares/test_circuit_breaker_registry_path.py tests/unit/entrypoints/middlewares/test_circuit_breaker_metrics.py -q 2>&1 | tail -5; then
    pass "Circuit breaker tests pass"
else
    fail "Circuit breaker tests FAIL — Phase 4 cannot proceed"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 6: Environment-specific prerequisites
# ──────────────────────────────────────────────────────────────────────

header "Check 6: $ENVIRONMENT environment prerequisites"

case "$ENVIRONMENT" in
    dev)
        note "Dev environment: minimal prerequisites"
        note "  - Redis NOT required (single-process SlidingWindowBreaker fallback works)"
        note "  - Prometheus metrics optional"
        ;;
    staging)
        note "Staging environment requirements:"
        note "  - Redis HA required (Sentinel or Cluster)"
        note "  - REDIS_ENABLED=true"
        note "  - Multi-pod replica (test failover)"
        note "  - Prometheus exporter deployed"

        if [[ -z "${REDIS_ENABLED:-}" ]] || [[ "$REDIS_ENABLED" != "true" ]]; then
            note "  [WARN] REDIS_ENABLED not set to true — Registry may use in-memory fallback"
            note "         This is OK for dev but NOT recommended for staging"
        fi
        ;;
    prod)
        note "Production environment requirements (STRICT):"
        note "  - Redis HA (Sentinel quorum 3/3 OR Cluster 6+ nodes)"
        note "  - REDIS_ENABLED=true"
        note "  - REDIS_URL set (Sentinel: sentinel-0,sentinel-1,sentinel-2)"
        note "  - Multi-pod with PDB (minAvailable: 1)"
        note "  - Prometheus Sentinel exporter deployed"
        note "  - Grafana dashboard: circuit breaker panel"
        note "  - On-call alert: Redis down, breaker open rate spike"

        if [[ -z "${REDIS_ENABLED:-}" ]] || [[ "$REDIS_ENABLED" != "true" ]]; then
            fail "REDIS_ENABLED must be true for production"
            exit 1
        fi
        ;;
    *)
        fail "Unknown environment: $ENVIRONMENT (use: dev | staging | prod)"
        exit 2
        ;;
esac

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────

header "Pre-flight check PASSED"
note "Ready for S13 Phase 4 $ENVIRONMENT rollout"
note ""
note "Next steps:"
note "  1. Set FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=true"
note "  2. Restart application pods"
note "  3. Verify 'Circuit OPEN (registry adapter)' log appears on failures"
note "  4. Monitor Grafana dashboard for 3-5 days"
note "  5. Check audit logs for reuse/family-revocation events"
note ""
note "Rollback: Set FEATURE_CIRCUIT_BREAKER_USE_REGISTRY=false (instant)"

exit 0
