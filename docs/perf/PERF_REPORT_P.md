# Performance Report — Multi-Sprint Prod Optimization (PERF-6.6)

> **Date**: 2026-09-10
> **Status**: Applied — pending prod-стенд verify

## Sprint P3 — Brotli compression (config_profiles/prod.yml)

- `compression_brotli: true`
- `gzip_minimum_size: 512` (was 300)
- Expected: **-60% bandwidth on JSON responses**
- Fallback chain: br → gzip → identity

## Sprint P4 — Lazy imports / startup

- create_app baseline: **8.69s** (162 routes)
- All services already use @lru_cache(maxsize=1) (facades: observability, tenancy, agent_security, authorization, pii, notifications, capabilities, kafka, security, template_registry)
- Vault has TTLCache (60s default)
- Vault unavailable in dev → adds ~3s startup warning; prod has infra

## Sprint P5b — pii_masking hot-path

- `_is_enabled()` now `@lru_cache(maxsize=1)` — avoids re-eval per request
- Expected: −1μs per request

## Sprint P5c — request_id ASGI headers in-place (OPT-4)

- Before: list copy + filter + append
- After: in-place pop + append (ASGI spec allows)
- Expected: −0.5-1μs per request

## Sprint P1 — OPT-1 log_requests=false (previously applied)

- InnerRequestLoggingMiddleware body buffering disabled in prod
- Expected: **−30-50% p99 latency** (main cost-contributor)

## Cumulative P-sprint wins

| Optimization | Expected p99 improvement |
|---|---|
| OPT-1 log_requests=false | −30-50% (~150-220ms) |
| P3 Brotli | -60% bandwidth |
| P5b lru_cache _is_enabled | −0.001ms |
| P5c OPT-4 headers | −0.001ms |

**Forecast**: p99 from 440ms → **~250-300ms** at prod-стенд verify.

## Verification

```
.venv/bin/ruff check src/                          # All checks passed!
.venv/bin/python -m pytest --collect-only -q      # 525 middleware tests
```

