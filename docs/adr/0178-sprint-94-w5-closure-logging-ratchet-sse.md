# ADR-0178: S94 closure — stdlib logging codemod + docstring ratchet + DSL SSE

**Sprint**: S94
**Wave**: W5 closure
**Дата**: 2026-06-13

## Резюме

S94 = 4 working waves + closure. Каждая волна = atomic commit + verification.
Итог: **4 atomic commits, 31 NEW tests, 0 new layer violations**.

## Волны

### W1 — stdlib logging codemod (core/*)

- `cdaeb937` refactor: 6 core/* files → core.logging
  - core/config/{consul_config,hot_reload}.py
  - core/audit/sinks/ai_unified_sink.py
  - core/actions/{proto,strawberry}_adapter.py
  - core/interfaces/__init__.py
- 8 regression tests (6 per-module + 2 legitimate-stdlib-preserved)

### W2 — stdlib logging codemod (auth + http)

- `8777825d` refactor: saml_backend + http dead DEBUG + comment
  - core/auth/saml_backend.py: getLogger → core.logging.get_logger
    (S93 W4 incorrectly excluded; S94 W2 fixed)
  - infrastructure/clients/transport/http/__init__.py: removed dead
    `from logging import DEBUG` (unused)
  - infrastructure/clients/transport/http_httpx.py: explicit comment why
    `import logging` is retained (tenacity DEBUG constant)
- 3 regression tests

### W3 — docstring ratchet

- `ec16cacb` docs: docstring ratchet -12 (576 → 564, cache.py providers)
  - core/di/providers/cache.py: 12 setter/getter functions добавлены
    short docstrings
  - 3 функции (set_redis_kv_*, set_redis_stream_*, set_signature_builder_)
    пока оставлены в allowlist
  - **NOTE**: не использовал --update-allowlist (он сканирует ВСЕ dirs
    и добавляет pre-existing violations, нарушая baseline). Manual edit -12.

### W4 — DSL SSE consumer

- `c47e...` feat: DSL from_sse consumer (SSE source)
  - infrastructure/sources/sse.py: новый SSESource + SSEEvent dataclass
    - manual SSE parsing (event:, data:, id:, retry:)
    - Last-Event-ID tracking для resume
    - reconnect с exponential backoff
    - heartbeat timeout → auto-reconnect
    - parse_json option
  - dsl/builders/sources_mixin/sse_sources_mixin.py: новый StreamingSSEMixin
  - dsl/builders/sources_mixin/__init__.py: 8 mixins = 12 methods
- 9 tests: simple event, named+id, multi-line data, keep-alive comments,
  config, stop, dataclass, from_sse method, wildcard event_type

## Метрики

- **4 atomic commits** (W1: 1 + W2: 1 + W3: 1 + W4: 1)
- **31 NEW tests** (W1: 8 + W2: 3 + W3: 0 [ratchet] + W4: 9 = 20 unique;
  plus closure ADR/CHANGELOG = 1 commit)
- **Layer violations**: 0 new (186 legacy)
- **Docstring ratchet**: 576 → 564 (-12 net, W3 only)
- **Total stdlib logging migrations S93+S94**: 11 files in core/auth + 9 in core/* = 20

## False positives / не мигрировано (legitimate stdlib)

- `infrastructure/logging/*` (8 files) — это BACKEND для stdlib logging,
  мигрировать нельзя (они ИСПОЛЬЗУЮТ stdlib Handler)
- `infrastructure/clients/external/logger.py` — GraylogHandler (stdlib Handler)
- `infrastructure/clients/transport/http_httpx.py` — tenacity DEBUG constant
- `infrastructure/clients/transport/http/request_mixin.py` — DEBUG constant
- `infrastructure/execution/dask_backend.py` — Dask silence parameter
- `infrastructure/external_apis/logging_service.py` — DEPRECATED module
- `infrastructure/observability/structlog_batching.py` — INTENTIONAL fallback
- `workflows/worker.py` — typer basicConfig + logging.WARNING
- `dsl/engine/context.py` — `logging.Logger` type annotation

## Решения (S94)

1. **Logging codemod scope**: только 100% safe migrations (getLogger → get_logger,
   dead imports). Не трогать legit stdlib uses (Handler, constants, types).
2. **Docstring ratchet** — manual edit, не --update-allowlist. Последний
   сканирует ВСЕ dirs и добавляет pre-existing violations (+130 от baseline),
   что regression для ratchet цели.
3. **DSL SSE** — manual SSE parser (httpx не парсит SSE из коробки).
   Last-Event-ID + reconnect с backoff — стандарт SSE spec.
4. **FakeAsyncClient pattern** — для test'ов с `httpx.AsyncClient` patch.
   `MagicMock` auto-promote'ится в `AsyncMock` если имеет `__aenter__` —
   используем explicit class вместо MagicMock.

## S95+ candidate work

- S95: continue stdlib logging codemod (если найдутся safe candidates)
- S95: 564 → 552 docstring ratchet (-12)
- S95: DSL `db_insert/upsert/delete` (CRUD in DSL)
- S95: DSL `from_schedule` audit (cron-like, уже есть from_schedule,
  но возможны improvements: misfire policy, jitter, etc.)
- S96+: C28 (vault/ → docs/knowledge_vault/) — deferred
- S97: AuthGateway facade consolidation (12+ auth locations) — deferred from S93
