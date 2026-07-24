# Dependency Analysis — Replacements & Future Additions

**Date**: 2026-07-23
**HEAD**: `ea5f63db`
**Scope**: Direct dependencies (pyproject.toml) + actual usage (src/, tests/)
**Approach**: Ponytail-YAGNI (drop-in only, no breaking refactors)

---

## Methodology

1. Parsed all direct deps from pyproject.toml (94 deps)
2. Counted actual imports in src/ + tests/ (top 30 packages used)
3. Identified:
   - **Underused**: declared but rarely imported
   - **Heavy**: large transitive trees, slow imports
   - **Replacements**: drop-in alternatives with better feature set
   - **Future**: not in deps but project would benefit
4. Honored `AGENTS.md` rule: lockfile changes need approval

---

## Current dependency footprint

| Category | Deps | Direct in pyproject.toml |
|---|---|---|
| Web framework | 11 | fastapi, uvicorn, pydantic, pydantic-settings, starlette, fastapi-filter, starlette-exporter, fastapi-limiter, fastapi-pagination, openapi-pydantic |
| Database | 7 | sqlalchemy, alembic, sqlalchemy-utils, sqlalchemy-continuum, asyncpg, psycopg2-binary, opentelemetry-instrumentation-asyncpg |
| Messaging | 3 | aiokafka, nats-py, faststream |
| Cache/Resilience | 3 | purgatory, redis, cachetools |
| HTTP clients | 2 | httpx, httpx-retries |
| LLM providers | 8 | openai, anthropic, cohere, groq, mistralai, xai-sdk, litellm, instructor |
| LLM frameworks | 4 | langsmith, langchain-core (transitive), langgraph (transitive) |
| Observability | 7 | opentelemetry-* (5), sentry-sdk, prometheus_client (transitive) |
| Security/crypto | 4 | argon2-cffi, cryptography, passlib, joserfc |
| Frontend | 1 | streamlit |
| Other | 42 | various (pulp, lxml, beautifulsoup4, etc.) |

---

## Recommendations

### A. Replacements (drop-in, low risk)

| Current | Replacement | Why | Risk |
|---|---|---|---|
| `fastapi-limiter` (lightweight rate-limit) | **`slowapi`** | Better async support; decorator-based; battle-tested. Replaces custom Limiter. | LOW — drop-in replacement |
| `httpx-retries` | **built-in `httpx.HTTPTransport(retries=N)`** (httpx ≥0.28) | httpx added native retries; one less dep | LOW — depends on httpx version |
| `cachetools` | **keep** (already used) | — | none |
| `python-multipart` | **keep** (FastAPI required) | — | none |
| `greenlet` (sqlalchemy async) | **keep** | required for asyncpg | none |
| `pendulum` (datetime replacement) | **keep** | Optional; stdlib datetime still works | none |
| `starlette-exporter` | **prometheus-fastapi-instrumentator** | More features, decorator-based, richer histograms | MEDIUM — config diff |
| `pyyaml` | **ruamel.yaml** (already in deps) | ruamel.yaml is safer (preserves comments, no code execution). pyyaml still used in tests. | MEDIUM — migration cost |
| `beautifulsoup4` | **selectolax** (C-extension, 10x faster) | Where parsing speed matters | MEDIUM — API differs |
| `lxml` | **selectolax** OR **lxml-html-clean** | When need HTML cleaning | MEDIUM — narrow use case |
| `glom` | **keep** (point-free data transforms) | Already integrated | none |
| `pydash` | **keep** | Already integrated | none |
| `croniter` | **keep** | apscheduler dep | none |

### B. Add (drop-in additions, low risk)

| New dep | Purpose | Justification | Risk |
|---|---|---|---|
| `limits` | Rate-limit primitives | Already using fastapi-limiter; limits is the underlying library. Useful for moving rate-limits to Redis when scale demands. | LOW — additive |
| `tiktoken` (already transitive?) | OpenAI tokenizer for accurate cost estimation | Already imported in some paths; check it's actually present. If yes, promote to direct. | LOW |
| `cryptography` rotation helper: `pyjwt[crypto]` | PyJWT with crypto algorithms | Already have pyjwt; ensure crypto algorithms are available | LOW |
| `orjson` | Already direct (59 files); ensure consistent use over `json` | Already done | none |
| `tenacity` | Already direct (24 imports); great for retry decorators | Already done | none |
| `dirty-equals` | Library for comparing complex Pydantic models | Already using pydantic; dirty-equals makes tests more readable | LOW |

### C. Strongly consider (build vs buy decision)

| Use case | Library | Replaces | Why |
|---|---|---|---|
| Agent framework | **`pydantic-ai`** (PydanticAI) | langgraph + langchain_core (partial) | Already in pyproject; pure-Pydantic; less ceremony than LangGraph; better type safety |
| Vector DB | **`qdrant-client`** (already direct) | — | Already chosen. No change. |
| Policy engine | **`casbin`** (already direct) | — | Already chosen |
| Temporal | **none** (custom SagaLRA) | Could add `temporalio` proper SDK | Out of scope; current SagaLRA is custom |
| Tracing | **OpenTelemetry** (already direct) | — | Already chosen |
| Rate limit | **`slowapi`** (proposed) | fastapi-limiter | Better feature set |

### D. **NOT recommended** (would regress)

- Replacing `sqlalchemy` with raw asyncpg: loses ORM, migrations, type safety
- Replacing `streamlit` with anything else: project is Streamlit-only per ADR-NEW-8
- Replacing `fastapi` with litestar/flask: massive refactor, no benefit
- Replacing `pydantic` with msgspec alone: msgspec is great but less ecosystem
- Adding `boto3` direct dep (already transitive): version conflicts common
- Adding `transformers` direct dep (already transitive, heavy): 5GB+ download
- Adding `torch` direct dep (already transitive): 2GB+ download

---

## Ponytail-YAGNI: Minimal additions

**Add immediately** (no refactor needed):
1. `slowapi` — replaces fastapi-limiter
2. `dirty-equals` — test readability
3. `limits` — Redis-backed rate limit primitives (additive, no breaking change)

**Defer** (large impact):
1. langchain → pydantic-ai migration (already started in services/ai/)
2. starlette-exporter → prometheus-fastapi-instrumentator (cosmetic)
3. pyyaml → ruamel.yaml (only if YAML round-trip comments become critical)

**Remove** (if confirmed unused):
- `lxml` (only if no XML parsing remains; check first)
- `beautifulsoup4` (same; check first)

---

## Underused direct deps (candidates for removal)

| Dep | Files importing | Recommendation |
|---|---|---|
| `glom` | 1+ (1 file) | Keep — point-free transforms |
| `pydash` | 1+ | Keep |
| `fastavro` | check usage | Investigate |
| `cbor2` | check usage | Investigate |
| `xmltodict` | check usage | Investigate |
| `qdrant-client` | check usage | Probably keep (vector DB) |
| `motor` | check usage | Probably keep (Mongo async) |
| `elasticsearch` | check usage | Probably keep |
| `granian` | check usage | Investigate — alt to uvicorn? |
| `hishel` | check usage | HTTP cache; keep |
| `croniter` | apscheduler dep | Keep (transitive) |
| `uvloop` | check usage | Possibly remove if asyncio loop is sufficient |
| `msgpack` | check usage | Possibly remove (compact; not many use cases) |
| `cachetools` | 5 | Keep |
| `redis-lock_processor` | check | (this is project code) |
| `pendulum` | check usage | Keep if any datetime needed |
| `python-multipart` | fastapi req | Keep |
| `whitenoise` | check | If static files served |

Let me verify a few:

## Underused direct deps — VERIFIED 2026-07-23

After running `grep -rn "^(from|import) <pkg>" src/ tests/` for every direct dep,
the following have **0 direct imports** (verified):

| Dep | Purpose (per PyPI) | Files | Recommendation |
|---|---|---|---|
| `lxml` | XML processing | 0 | **REMOVE** (check zeep transitive) |
| `fastavro` | AVRO read/write | 0 | **REMOVE** |
| `cbor2` | CBOR serializer | 0 | **REMOVE** |
| `xmltodict` | XML→dict | 0 | **REMOVE** |
| `qdrant-client` | Qdrant vector DB | 0 | **REMOVE** (consider only if vector search needed) — OR wrap as DSL processor (Ponytail YAGNI: do later) |
| `motor` | MongoDB async | 0 direct (1 processor) | **KEEP** — wrapped as DSL processor in S170 M2 (`infra_mongodb_find`). Already integrated. |
| `elasticsearch` | ES client | 0 direct (4 in builders/infrastructure_dsl.py) | **KEEP** — wrapped as DSL processors in cycle 26 (`infra_elasticsearch_search`, `infra_elasticsearch_index`). Also builder methods `es_index`, `es_search`. |
| `hishel` | HTTP cache | 0 | **REMOVE** |
| `uvloop` | libuv event loop | 0 | **REMOVE** (standard asyncio sufficient) |
| `msgpack` | MessagePack | 0 | **REMOVE** |
| `pendulum` | datetime lib | 0 | **REMOVE** (stdlib datetime sufficient) |
| `pulp` | LP solver | 0 | **REMOVE** |
| `beautifulsoup4` | HTML scraping | 0 | **REMOVE** |
| `pillow` | PIL | 0 | **REMOVE from direct** (already in lockfile at 12.3.0) |
| `whitenoise` | static files | 0 | **REMOVE** (FastAPI StaticFiles built-in) |
| `pyjwt` | JWT | 0 | **REMOVE** (joserfc covers JWT) |
| `openpyxl` | Excel | 0 | **REMOVE** |
| `svcs` | service locator | 0 | **REMOVE** (project has own DI) |
| `pypdf` | PDF | 0 | **REMOVE** |
| `python-docx` | Word | 0 | **REMOVE** |
| `markitdown` | file→markdown | 0 | **REMOVE** |
| `whoosh-reloaded` | full-text search | 0 | **REMOVE** |
| `rank-bm25` | BM25 ranking | 0 | **REMOVE** |
| `httpx-retries` | retry layer | 0 | **REMOVE** (httpx ≥0.28 native retries) |
| `langchain-core` | LLMs framework | 0 direct (transitive via langgraph) | **REMOVE from direct** |
| `langgraph` | stateful LLMs | 4 files | **INVESTIGATE** — consider pydantic-ai |

**Low-usage (1-2 files):**

| Dep | Files | Recommendation |
|---|---|---|
| `granian` | 1 | Keep (alt uvicorn) |
| `pydash` | 1 | Keep (point-free utils) |
| `glom` | 2 | Keep |
| `pandas` | 1 | Keep (data processing) |
| `tiktoken` | 1 | Keep (token counting) |
| `typer` | 2 | Keep (CLI) |
| `structlog` | 2 | Keep (structured logging) |
| `purgatory` | 1 | Keep (circuit breaker) |
| `sqladmin` | 1 | Keep (admin UI) |

**Used heavily (>5 files) — KEEP:**

| Dep | Files |
|---|---|
| `httpx` | 37 |
| `redis` | 7 |
| `cachetools` | 5 |
| `sqlalchemy` | 62+ |
| `pydantic` | 231 |
| `fastapi` | 178 |
| `streamlit` | 95 |
| `orjson` | 59 |
| `pytest` | 1099 |


---

## DSL wrapping strategy (user-requested, cycle 26)

Per user request "wrap unused deps as DSL processors":
- Many unused direct deps have facade counterparts in `core/di/providers/infrastructure_facade.py`
- Project pattern (per MEMORY-m2-phase-ships.md): wrap each backend as a DSL processor
  under `dsl/engine/processors/infra_*.py` namespace=infra, with capability gates.

### Already wrapped (via S170 M2)

- `motor` (MongoDB) → `infra_mongodb_find` (cycle 36 S171 M2.3)
- `redis` → `infra_redis_get/set/...` (multiple)
- `kafka` → `infra_kafka_*`
- `clickhouse` → `infra_clickhouse_*`
- `s3` → `infra_s3_*`
- `db` → `infra_db_*`
- `elasticsearch` → builder methods `es_index`, `es_search`

### Wrapped in cycle 26 (this report)

- `elasticsearch` (full DSL processor, not just builder):
  - `infra_elasticsearch_search` — full-text search via facade
  - `infra_elasticsearch_index` — document indexing
  - 10 tests added (`tests/unit/cycle_26_infra_elasticsearch.py`)
  - `elasticsearch_client_class` registered in facade

### Candidates for future cycles (Ponytail-YAGNI: do later if needed)

| Dep | DSL processor name | Notes |
|---|---|---|
| `qdrant-client` | `infra_qdrant_search`, `infra_qdrant_upsert` | Vector search integration |
| `pypdf` | `infra_pdf_extract` | Useful for document processing pipelines |
| `python-docx` | `infra_docx_extract` | Office docs |
| `openpyxl` | `infra_xlsx_extract` | Spreadsheet processing |
| `whoosh-reloaded` | `infra_whoosh_search` | In-process full-text (fallback when ES unavailable) |
| `rank-bm25` | `infra_bm25_rank` | BM25 ranking for RAG pre-filter |
| `markitdown` | `infra_markdown_convert` | Multi-format → markdown conversion |
| `beautifulsoup4` | `infra_html_extract` | HTML scraping/parsing |
| `pillow` | `infra_image_*` | Image processing (resize, OCR fallback) |
| `pulp` | `infra_lp_solve` | Linear programming (if business uses it) |

### Anti-candidates (do NOT wrap)

- `pandas`, `numpy` — too generic; belong in user code, not DSL
- `sqlalchemy`, `alembic` — DSL composition layer; ORM is platform concern
- `faststream`, `aiokafka` (raw) — already wrapped via Kafka facade
- `lxml`, `xmltodict` — narrow; only if XML round-trip is needed
- `msgpack`, `cbor2` — serializers; not workflow actions

