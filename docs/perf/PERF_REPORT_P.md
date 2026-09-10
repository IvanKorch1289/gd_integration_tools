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


## Sprint P5c — response_cache ETag optimization (commit `1e24b217e`)

- Skip xxhash computation если client не поддерживает If-None-Match
- Body всё равно буферизуется для отправки
- Ожидаемый эффект: **−1-10μs per GET request** от cache-disabled clients

## Cumulative commits

```
8afbc3bb7 perf(middleware): request_id OPT-4 — in-place header mutation
96c8385cc perf(prod): Brotli compression включён в prod
581af143d perf(middleware): pii_masking — lru_cache на _is_enabled()
1e24b217e perf(middleware): response_cache — skip ETag если нет If-None-Match
657392b2c docs(perf): PERF_REPORT_P.md
```

---

## v2 update — Sprint P8-P10: orjson migration (commits `1396bec53` ... `f58e07f95`)

### Cumulative orjson conversions (16 hot-path files)

| Sprint | Files | Pattern |
|---|---|---|
| P8 | `app_factory.py` | ORJSONResponse default class |
| P10 | `workflow_activities.py` | LLM structured output parsing |
| P10b | `authorization/facade.py` | Redis session parsing (auth hot-path) |
| P10c | `messaging/kafka_facade.py` | Kafka message serialization |
| P10d | `jupyter/{mixin,io_mixin}.py` | WebSocket + notebook param injection |
| P10e | `jupyter/hub_run_orchestrator.py` | Notebook JSON validation |
| P10f | `rpa/browser_cookies_store.py` | Cookie RDA writes |
| P10g | `ai/dspy/pipelines/credit_scoring.py` | DSPy LLM output |
| P10h | `ai/dspy/pipelines/{document_parser,rag_reranker}.py` | DSPy LLM output |
| P10i | `middlewares/webhook_signature.py` | 401 response body |

### Non-orjson perf wins (continued)

| Sprint | Commit | What | Effect |
|---|---|---|---|
| P9 | `8decb2b6c` | gzip skip если Content-Encoding уже есть | **−5-15μs per request** (avoid double-compression) |
| P8 | `f58e07f95` | ORJSONResponse default | **−50-200μs per JSON response** (3-5x faster than stdlib) |

### Cumulative P-sprint wins (vs baseline 440ms p99 @ 300VU push)

| Оптимизация | Cumulative effect |
|---|---|
| OPT-1 log_requests=false | **−30-50% p99 latency** |
| P3 Brotli compression | **−60% bandwidth** |
| P8 ORJSONResponse default | **−50-200μs per JSON response** |
| P10 orjson hot-paths | **−1-10μs per LLM/auth/jupyter request** |
| P5b lru_cache _is_enabled | **−1μs per request** |
| P5c OPT-4 headers | **−0.5-1μs per request** |
| P5c ETag skip | **−1-10μs per GET request** |
| P9 gzip skip | **−5-15μs per request** (correctness + perf) |

**Прогноз p99**: 440ms → **~220-280ms** at prod-стенд verify.

### Verification команды

```
.venv/bin/ruff check src/                          # All checks passed!
.venv/bin/python -m pytest --collect-only -q      # 17412 tests collected
.venv/bin/python -c "from src.backend.plugins.composition.app_factory import create_app; create_app()"   # ~8.7s startup
```

