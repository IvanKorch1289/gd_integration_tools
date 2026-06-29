**Scope: Project-wide recommendations для будущих спринтов**

**S171 M20 SHIPPED** (commit c06d487):
- D252 — FallbackCertBackend integration (CertStoreSettings.fallback_enabled)
- D254 — docs/security/cert_loading.md (comprehensive onboarding-гайд)
- P1 cleanup — fallback.py dead code removed
- P1 YAML profiles — watch_enabled/watch_path добавлены в base/prod/staging
- D253 — Lifespan wiring example (docs/security/cert_hot_reload.md)

**S171 M21 SHIPPED** (commits 6753e79, +):
- D255 — Vault AppRole/K8s auth (4/4 sync tests GREEN)
- D256 — list_expiring admin endpoint (3/3 tests GREEN)

**S171 M22 SHIPPED** (latest):
- D257 — RedisCertTransport (Pub/Sub, 5/5 tests GREEN)
- D258 — CertBackendRegistry (plugin pattern, 6/6 tests GREEN)

**S171 M23 SHIPPED** (latest):
- D259 — CertPrometheusExporter (4/4 tests GREEN)
- D260 — CertRotationWatcher (4/4 tests GREEN)

**SPRINT 171 COMPLETE** (M10-M23): 14 D-rules, 49+ atomic commits, 95+ tests added, 415 routes


## Часть 1: Sprint 171 итоги (M10-M17)

| M | Что | Failures fixed | BUG fixes | New tests |
|---|-----|----------------|------------|-----------|
| **M10** | P0-P3 (Worker Versioning, ContinueAsNew, CompensateWorkflow, EnvelopeEncryption, Schema-registry) | 8 tasks | 0 | 0 |
| **M11** | Pre-existing failures R1-R7 | 41 → 0 | 0 | 0 |
| **M12** | R4 refactor with TDD+review | 7 → 0 | 1 (correlation_id) | 7 |
| **M13** | R5/R6/R3 refactor | 10 → 0 | 1 (metrics m.__all__) | 5 |
| **M14** | Helpers audit (scaffold, LSP, docs) | 0 | 1 (scaffold paths) | 5 |
| **M15** | Docs accuracy (323 .md files) | 0 | 0 | 0 |
| **M16** | SSL/cert hot-reload (D245) | 0 | 0 (new feature) | 4 |
| **M17** | DSL audit (OCR/cache/CRUD/CDC) | 0 | 0 | 0 |
| **TOTAL** | | **76** | **3** | **21** |

## Часть 2: Состояние проекта (на 2026-06-26)

- **Production readiness**: 92-95% (Sprint 36 + M10-M17)
- **Test baseline**: 4207 passed (+1434 vs pre-S171), 51 skipped (deferred with reason)
- **Bugs known (P0-P3 backlog)**: ~15 (security + infrastructure)
- **Auto-rebuild detection**: 415 routes, app launches, vault warning known
- **Push status**: BLOCKED per AGENTS.md (95+ commits ready на master)

---

## Часть 3: Рекомендации — Библиотеки/Функционал (10+)

Per user directive + проектная философия (4-layer, async-first, Pydantic v2, capability-checked facades):

### P0 — Critical security gaps (D236)

1. **DSPy (≥2.5.0)** — компиляция и оптимизация промптов для AI agents.
   - **Why**: Текущие агенты используют статические промпты. DSPy позволит auto-optimization
     на real production data → лучше качество, меньше manual prompt tuning.
   - **Where**: `services/ai/dspy/optimizer.py` (уже есть scaffold, 0 production usage per ARCHITECTURAL_AUDIT_V2.md)
   - **Risk**: MEDIUM (нужны training data + метрики)

2. **guardrails-ai (≥0.6.0)** — структурированный LLM output + policy enforcement.
   - **Why**: `AgentToolPolicy` (S171 R169) default-deny, но **DENY не audit'ится**
     (agent 5: tool whitelist bypass CRITICAL). guardrails-ai добавит typed validation + audit.
   - **Where**: `core/ai/policy/` + `services/ai/guardrails/`
   - **Risk**: LOW (Pydantic-native, integration straightforward)

3. **ProcessPoolSandbox (или E2B default)** — заменить `InProcessAgentSandbox` (zero-isolation).
   - **Why**: Per D236 P0 security. Агент может escape через vulnerabilities.
   - **Where**: `core/ai/sandbox.py` (default), `services/ai/agent_sandbox.py`
   - **Risk**: MEDIUM (нужна sandbox infrastructure)

### P1 — High impact

4. **InProcessAgentSandbox → ProcessPoolSandbox** — процессная изоляция для LLM-агентов.
   - **Why**: Banking-домен требует hard isolation. ProcessPoolSandbox через
     `multiprocessing` или `subprocess` + restricted filesystem.
   - **Where**: `core/ai/sandbox.py` — `InProcessAgentSandbox` сейчас default
   - **Risk**: MEDIUM (overhead + lifecycle)

5. **opentelemetry-instrumentation-confluent-kafka** — Kafka tracing (D236 P1).
   - **Why**: `infrastructure/messaging/dlq/kafka_writer.py` использует aiokafka,
     но нет OTel instrumentation для distributed traces через Kafka.
   - **Where**: `infrastructure/observability/otel_auto.py` (M5 уже instrumented aiokafka)
   - **Risk**: LOW

6. **httpx-retries + hishel** — retry policies + HTTP caching (D236 P1).
   - **Why**: `outbound_http.py` уже использует httpx, но без auto-retry и HTTP caching.
     Это ускорит повторяющиеся upstream calls (особенно для AI providers).
   - **Where**: `core/net/outbound_http.py`
   - **Risk**: LOW (opt-in через feature flags)

7. **instructor (≥1.7.0)** — structured LLM output (Pydantic-native).
   - **Why**: `core/ai/pydantic_ai_client.py` использует pydantic-ai, но
     structured output через `instructor` даст typed responses + better error handling.
   - **Where**: `services/ai/llm/` (уже declared в `ai-2026` extra, 2 imports)
   - **Risk**: LOW

8. **cachetools + redis — многоуровневый кэш для file_search** (M17.1 GAP).
   - **Why**: M17.1 audit выявил GAP — нет `FileSearchProcessor`. `cachetools.TTLCache`
     для in-process, Redis для distributed. Используется в 4+ местах (audit).
   - **Where**: NEW `dsl/engine/processors/file_search.py`
   - **Risk**: LOW (cachetools уже в deps)

### P2 — Medium priority

9. **PdfExtractProcessor (pypdf + pdfplumber)** — PDF text extraction.
   - **Why**: Banking docs (statements, contracts) часто PDF. Нет DSL processor
     для извлечения текста. `pypdf>=4.0` + `pdfplumber>=0.10` (легковесные).
   - **Where**: NEW `dsl/engine/processors/pdf_extract.py`
   - **Risk**: LOW

10. **BatchAggregator (windowed aggregation)** — Apache Flink-style session windows (D198 GAP).
    - **Why**: Текущий `windowed_dedup.py` поддерживает только dedup, нет real aggregation.
      Event bus → real-time analytics требует windowed aggregations.
    - **Where**: NEW `dsl/engine/processors/eip/collection/aggregator.py`
    - **Risk**: MEDIUM (нужны state-management hooks)

11. **memray (memory profiling)** — production memory leak detection.
    - **Why**: `app.state_singleton` + `lifespan` могут leaks через closures. memray
      интегрируется в pytest fixtures для автоматического detection.
    - **Where**: `tests/conftest.py` + `make test` target
    - **Risk**: LOW

### P3 — Low priority / Future

12. **Faust-streaming (Kafka windowed)** — если Kafka pipeline масштабируется.
    - **Why**: Сейчас `infrastructure/messaging/` имеет raw aiokafka, но нет stream processing.
    - **Where**: `infrastructure/messaging/faust_backend.py` (NEW)
    - **Risk**: MEDIUM (YAGNI пока нет Kafka production load)

13. **LSP server (pygls)** — IDE/editor integration для DSL authoring.
    - **Why**: `tools/dsl_lsp/schema_completion.py` уже есть, но **не подключён к LSP server**.
      Нужен full pygls-based server с hover, diagnostics, jump-to-def.
    - **Where**: NEW `tools/dsl_lsp/server.py`
    - **Risk**: MEDIUM (LSP protocol complexity)

14. **hishel (HTTP cache)** — RFC 9111 compliant cache для upstream HTTP.
    - **Why**: 26 httpx imports, много upstream calls (AI providers, S3). Cache снизит
      latency + cost для AI calls.
    - **Where**: `core/net/outbound_http.py` (interceptor pattern)
    - **Risk**: LOW

15. **Redis Streams как cache backend** — sorted sets для leaderboard/timeline caching.
    - **Why**: Текущий cache = только KV. Sorted sets — для rate-limit sliding window,
      real-time metrics aggregation.
    - **Where**: `infrastructure/cache/redis_streams.py` (NEW)
    - **Risk**: LOW

---

## Часть 4: Backlog из S63 + M17 GAPs

| # | Backlog | Source | Priority |
|---|---------|--------|----------|
| 1 | FileSearchProcessor (поиск в файлах) | M17.1 GAP | P2 (M18) |
| 2 | PdfExtractProcessor | M17.1 GAP | P2 (M18) |
| 3 | OfficeExtractProcessor (.docx/.xlsx) | M17.1 GAP | P3 (M19) |
| 4 | MimeDetectProcessor (magic bytes) | M17.1 GAP | P3 (M19) |
| 5 | EncodingDetectProcessor (chardet) | M17.1 GAP | P3 (M19) |
| 6 | BatchAggregator (windowed) | M17.3 GAP | P2 (M18) |
| 7 | CDC Oracle без Kafka | M17.4 GAP | P2 (M19) |
| 8 | Worker Versioning (D172) — БЫЛ M10 | DONE | - |
| 9 | ContinueAsNew handler (D169) — БЫЛ M10 | DONE | - |
| 10 | CompensateWorkflow (D173) — БЫЛ M10 | DONE | - |
| 11 | EnvelopeEncryption (D174) — БЫЛ M10 | DONE | - |
| 12 | Schema-registry R1 (D175) — БЫЛ M10 | DONE | - |
| 13 | ContinueAsNew DSL (D169) — БЫЛ M9 final | DONE | - |
| 14 | Claim Check DSL (D170) — БЫЛ M9 final | DONE | - |
| 15 | Cert hot-reload (D245) — БЫЛ M16 | DONE | - |

---

## Часть 5: 10+ рекомендаций — СВОДКА

| # | Библиотека | Use case | Priority | Risk |
|---|-----------|----------|----------|------|
| 1 | **DSPy** | Prompt optimization | P0 | MEDIUM |
| 2 | **guardrails-ai** | LLM output validation + audit | P0 | LOW |
| 3 | **ProcessPoolSandbox** | Agent process isolation | P0 | MEDIUM |
| 4 | **opentelemetry-instrumentation-confluent-kafka** | Kafka tracing | P1 | LOW |
| 5 | **httpx-retries + hishel** | HTTP retry + cache | P1 | LOW |
| 6 | **instructor** | Structured LLM output (Pydantic) | P1 | LOW |
| 7 | **cachetools + redis** для file_search | File search cache | P1 | LOW |
| 8 | **pypdf + pdfplumber** | PDF text extraction | P2 | LOW |
| 9 | **BatchAggregator** (windowed) | Stream aggregation | P2 | MEDIUM |
| 10 | **memray** | Memory leak detection | P2 | LOW |
| 11 | **Faust-streaming** | Kafka stream processing | P3 | MEDIUM |
| 12 | **pygls LSP server** | DSL IDE integration | P3 | MEDIUM |
| 13 | **hishel** (RFC 9111) | HTTP cache | P3 | LOW |
| 14 | **Redis Streams** | Sorted sets for leaderboard | P3 | LOW |
| 15 | **aiocoap / Thrift** | IoT / legacy RPC protocols | P3 (YAGNI) | MEDIUM |

---

## Часть 6: Принципы внедрения (per AGENTS.md)

- **Ponytail YAGNI** — НЕ добавлять speculative deps (EasyOCR, sse-starlette, dependency-injector)
- **Capability-checked facades** — все новые deps через `core/facades.py` (D187)
- **Pydantic v2 + async-first** — обязательно для всех новых компонентов
- **4-layer architecture** — `core → infrastructure → services → extensions`
- **TDD-first + review** — каждое внедрение: RED → GREEN → review-agent
- **Russian-only docstrings** — во всех новых комментариях + commit messages

---

## Часть 7: Заключение

**Sprint 171 + M10-M17: проект в excellent state**:
- 4207 tests passed (vs baseline 2773)
- 3 BUG fixes
- 9 новых D-rules (binding для future sprints)
- 21 новых tests
- 30+ atomic commits
- Production-ready на 92-95%

**Top 3 P0 рекомендации** для немедленной работы:
1. **ProcessPoolSandbox** (security isolation, 1 week)
2. **guardrails-ai** (DENY audit, 3 days)
3. **DSPy prompt optimization** (quality, 1 week)

**Top 5 P1 рекомендации** для ближайшего спринта:
1. instructor (structured LLM output)
2. httpx-retries + hishel (HTTP retry/cache)
3. otel-instrumentation-confluent-kafka (Kafka tracing)
4. cachetools+redis для file_search
5. pypdf + pdfplumber (PDF extraction)

**Top P3** — LSP server, Faust, memray, Redis Streams — для M19+.

Refs:
- D236 (Production readiness backlog)
- D237 (TDD + review pattern)
- D245 (Cert hot-reload opt-in)
- Sprint 36 production readiness (90%+)
- Sprint 171 M10-M17 (this sprint)
- M17.1-M17.4 audit phase
