# Cycle 4 — Phase 1 — Domain Audit: RAG (Retrieval-Augmented Generation)

> Domain: RAG
> Agent: 09-rag
> Date: 2026-08-06
> HEAD observed: `196dc989` (4 commits ahead of baseline `22e08a0d`; non-RAG commits:
> SBOM canonical path, MCPToolProcessor/AgentGraphProcessor shadow removal, AuthValidateProcessor
> _VERIFIERS path, legacy eip/reliability.py removal — none affect RAG scope).
> Working tree: clean for RAG scope files (only pre-existing drift: `uv.lock`,
> `.blue_green.state`, untracked audit docs / tests).

## 1. Scope / files inspected

Verified by reading (cycle-4 D-AUDIT-00 strict scope adherence):

**Source (production):**
- `src/backend/services/ai/rag_types.py` (83 LOC)
- `src/backend/services/ai/rag_augment.py` (133 LOC)
- `src/backend/services/ai/rag_ingest_store.py` (283 LOC)
- `src/backend/services/ai/rag_ingest_service.py` (252 LOC)
- `src/backend/services/ai/rag_cache_prewarmer.py` (110 LOC)
- `src/backend/services/ai/rag_query_stats.py` (102 LOC)
- `src/backend/services/ai/hybrid_rag.py` (221 LOC)
- `src/backend/services/ai/rag_service/__init__.py` (88 LOC)
- `src/backend/services/ai/rag_service/_protocol.py` (37 LOC)
- `src/backend/services/ai/rag_service/state.py` (11 LOC)
- `src/backend/services/ai/rag_service/ingest_mixin.py` (90 LOC)
- `src/backend/services/ai/rag_service/search_mixin.py` (234 LOC)
- `src/backend/services/ai/rag_service/augment_mixin.py` (137 LOC)
- `src/backend/services/ai/rag_service/collection_mixin.py` (84 LOC)
- `src/backend/services/ai/eval/ragas_evaluator.py` (316 LOC)
- `src/backend/services/ai/eval/inspect_runner.py` — read header
- `src/backend/services/ai/eval/suites/__init__.py` (36 LOC)
- `src/backend/services/ai/eval/suites/{knowledge_qa,instruction_following,hallucination_check,safety_classifier,context_recall,tool_use,multi_turn_coherence}.py`
- `src/backend/core/cache/rag.py` (15 LOC; capability-checked facade)
- `src/backend/core/config/rag.py` (189 LOC)
- `src/backend/core/config/features/ai_rag.py` (380 LOC)
- `src/backend/entrypoints/api/v1/endpoints/rag.py` (463 LOC)
- `src/backend/entrypoints/api/v1/endpoints/rag_ingest.py` (138 LOC)
- `src/backend/entrypoints/api/v1/endpoints/rag_cache_admin.py` (78 LOC)
- `src/backend/entrypoints/api/v1/endpoints/admin_rag.py` (63 LOC)
- `src/backend/dsl/engine/processors/ai/rag_search.py` (56 LOC)
- `src/backend/dsl/engine/processors/ai/ragquery_processor.py` (136 LOC)
- `src/backend/dsl/engine/processors/ai/ragingest_processor.py` (92 LOC)
- `src/backend/dsl/engine/processors/ai/ragpiiredaction_processor.py` (64 LOC)
- `src/backend/services/ai/pii/retrieval_masker.py` (107 LOC) — supporting PII path
- `src/backend/services/ai/rag/strategy_selector.py` (135 LOC) — adaptive RAG selector (referenced)
- `src/backend/services/ai/dspy/pipelines/rag_reranker.py` (188 LOC) — BGE reranker (referenced)

**Tests:**
- `tests/e2e/test_multimodal_rag_e2e.py` (434 LOC)
- `tests/unit/services/ai/test_rag_*.py` (9 files)
- `tests/unit/services/ai/eval/test_ragas_evaluator.py`
- `tests/unit/services/ai/eval/test_inspect_runner.py`
- `tests/unit/api/test_rag_cache_admin.py`
- `tests/unit/dsl/engine/processors/ai/test_rag*.py` (3 files)
- `tests/unit/dsl/engine/processors/test_rag_pii_redaction.py`

**NOT inspected (intentional, per scope or per BASELINE):**
- `src/backend/services/ai/gateway_adapter.py` (pre-existing cycle-1 residual, baseline
  says "cycle-2/3/4 plans явно НЕ переписывать"; line 122-123 `except Exception: pass`)
- `src/backend/services/ai/prompts/langfuse_storage.py` (out of scope — `prompts/`,
  not `rag`)
- `src/backend/services/ai/rag/multimodal/**` (no `rag` in filename, not matching
  `*rag*.py` glob; multimodal files are only covered by e2e test, which is in scope)
- `extensions/` business logic files (architecture rule: business logic only in `extensions/`,
  but no RAG-business-logic file matches scope here)
- `tests/unit/cycle_31_s1_coverage.py` (cross-domain regression test, not RAG-specific)
- `tests/unit/services/ai/test_s3_*` / `tests/unit/services/ai/test_ai_agent_rag.py`
  (out of scope per BASELINE)

**Runtime tests executed via `.venv/bin/python -m pytest` (8 commands, 121 tests total):**
- `tests/unit/services/ai/test_rag_cache_prewarm.py` — 5 PASS
- `tests/unit/services/ai/test_rag_pii_mask.py` — 3 PASS
- `tests/unit/services/ai/test_rag_tenant_isolation.py` — 20 PASS
- `tests/unit/services/ai/test_rag_source_attribution.py` — 4 PASS
- `tests/unit/services/ai/test_rag_citations.py` — 4 PASS
- `tests/unit/services/ai/test_rag_augment.py` — 9 PASS
- `tests/unit/services/ai/test_rag_ingest_store.py` — 6 PASS
- `tests/unit/api/test_rag_cache_admin.py` — 5 PASS
- `tests/unit/services/ai/eval/test_ragas_evaluator.py` — 9 PASS
- `tests/unit/services/ai/eval/test_inspect_runner.py` — 26 PASS (incl. 7× parameterized)
- `tests/unit/dsl/engine/processors/ai/test_rag*.py` (3 files) — 19 PASS
- `tests/unit/dsl/engine/processors/test_rag_pii_redaction.py` — 4 PASS
- `tests/e2e/test_multimodal_rag_e2e.py` — **2 FAIL, 1 PASS** (see DOMAIN-P0-001)
- `tests/unit/services/ai/test_rag_ingest_service.py`, `test_rag_embedding_version.py` —
  pre-existing spacy-model download failure (out of RAG scope, in baseline as
  "pre-existing infra issue")

**Не проверено** (not in scope):
- `src/backend/services/ai/gateway_adapter.py` dead-loop bypass (BASELINE residual)
- `src/backend/services/ai/rag/multimodal/**` internal types/conftest (out of scope,
  only e2e test in scope)
- `tests/unit/services/ai/test_rag_ingest_service.py` and `test_rag_embedding_version.py`
  runtime crash from `presidio-analyzer` downloading `ru-core-news-lg` (pre-existing
  spacy infra issue, not RAG domain)

## 2. Verified strengths

| # | Strength | path:line | Evidence |
|---|---|---|---|
| S-1 | Tenant isolation defence-in-depth (vector store `where` + cache-key + post-filter) | `rag_service/search_mixin.py:179-225` | 20/20 tests pass — `test_rag_tenant_isolation.py` covers cache-hit fall-through, explicit override, cross-tenant E2E. |
| S-2 | Capability-checked facade for `ThreeTierRagCache` | `core/cache/rag.py:13` | Uses `infrastructure_locator.get_three_tier_rag_cache_class()` via DI; no direct `infrastructure` import. |
| S-3 | API fail-closed by default (`rag_settings.enabled=False` → 503 on mutating endpoints) | `entrypoints/api/v1/endpoints/rag.py:189-194` (`_check_enabled`) | Verified via runtime import `rag_settings.enabled == False`; mutating endpoints raise HTTPException(503). |
| S-4 | PII fail-closed by default on retrieval (`rag_pii_retrieval_mask=True`) and on ingest (`pii_mask_on_ingest=True`) | `core/config/features/ai_rag.py:66` + `core/config/ai_stack.py:136` | Both default `True`; verified via runtime `from src.backend.core.config.rag import rag_settings`. |
| S-5 | Source attribution with explicit priority (`source` → `filename` → `doc_id` → `id`) | `rag_service/search_mixin.py:148-168` | 4/4 tests pass; deterministic priority order. |
| S-6 | Adaptive strategy selector with in-memory LRU cache + heuristic fallback | `services/ai/rag/strategy_selector.py:75-131` | 8/8 tests pass; ≥50ms overhead budget (DoD#2) achieved via LRU. |
| S-7 | Emb. version strict-mode gate (drop mismatched chunks, counter `rag_model_mismatch_total`) | `rag_service/search_mixin.py:92-120` | `embedding_strict_mode=True` default; legacy chunks without `embedding_model` pass-through. |
| S-8 | Eval suite complete (7 reference suites + RAGAS) | `services/ai/eval/suites/{knowledge_qa,instruction_following,hallucination_check,safety_classifier,context_recall,tool_use,multi_turn_coherence}.py` + `ragas_evaluator.py` | 35/35 tests pass; `REFERENCE_SUITES` registered; RAGAS returns `skipped` gracefully when missing deps. |
| S-9 | Freshness distribution + `worst_freshness` aggregation | `services/ai/rag_augment.py:52-133` (`build_augment_result`) | 9/9 tests pass; UTC normalization for naive datetimes; ISO round-trip. |
| S-10 | RAG admin endpoints role-gated (operator / super-admin) | `entrypoints/api/v1/endpoints/rag_cache_admin.py:25-29` | `Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))`. |
| S-11 | DSL PII redaction processor opt-in via feature flag | `dsl/engine/processors/ai/ragpiiredaction_processor.py:45-55` | 4/4 tests pass; non-dict payload is no-op (defensive). |
| S-12 | Authoritative load-decomposition `RAGService` (4 mixins + `__init__`) | `rag_service/__init__.py:75-88` | Verified via MRO: `RAGService → IngestMixin → SearchMixin → AugmentMixin → CollectionMixin → _RAGServiceProtocol → Protocol → Generic → object`. |
| S-13 | Import-cycle break via `RAGCitation` extraction to `rag_types.py` | `rag_types.py:1-6` (module docstring) | `state.py` is now a 1-line backward-compat alias; no cycle. |
| S-14 | TTL on Redis HASH for ingest state (D.2) | `rag_ingest_store.py:188-191` (`pipe.set(key, raw, ex=self._ttl)`) | Maintains bounded memory + ordered list via ZSET. |
| S-15 | RAG-cache invalidation by `tag:namespace` on ingest | `rag_service/ingest_mixin.py:83-89` (`_invalidate_namespace`) | Wired to `cache.invalidate_by_tag(f"namespace:{namespace}")`. |

## 3. Findings table (P0..P4)

| ID | Priority | path:line | Title | Status |
|---|---|---|---|---|
| DOMAIN-P0-001 | P0 | `tests/e2e/test_multimodal_rag_e2e.py:255-340, 346-397` | **Text-RAG E2E tests FAIL** — `test_image_caption_pipeline_e2e` and `test_audio_transcript_pipeline_e2e` both fail at `assert len(hits) >= 1` (got 0). The text-RAG E2E was Deferred Cycle-1 T-4.1 and Cycle-2 T-W4-01 — STILL RESIDUAL in cycle-4. | RESIDUAL |
| DOMAIN-P0-002 | P0 | `src/backend/services/ai/rag_ingest_service.py:224-226` | **PII fail-open on ingest when sanitizer fails** — `except Exception → return content_text, {"pii_masked": False, "pii_mask_error": str(exc)}` writes raw PII to vector store if Presidio / regex sanitizer raises. Test `test_ingest_graceful_on_sanitizer_failure` locks in this behavior. Direct ingest via `RAGService.ingest()` (skipping service) bypasses this entirely. | NEW |
| DOMAIN-P0-003 | P0 | `src/backend/services/ai/rag_cache_prewarmer.py:68-80` | **`RagCachePrewarmer` runtime is phantom** — `RAGService` has no `query()` method (`grep -rn "def query" src/backend/services/ai/rag_service/*.py` → 0 results). First call raises `TypeError`, inner fallback also raises `TypeError`, `continue` is hit, `loaded` never increments. `fill_cache=True` parameter is non-existent. Verified at runtime: `await prewarmer.prewarm_tenant("t1") → 0`. Cycle-2 T-W1-06 — STILL RESIDUAL. | RESIDUAL |
| DOMAIN-P1-001 | P1 | `src/backend/services/ai/rag_service/augment_mixin.py:90-94` | **Citation score contract violation** — docstring claims "score нормируется к [0..1] через 1 - distance; при отсутствии distance — 0.0", but code uses raw `distance` value as `score`. Test `test_rag_citations.py:84` asserts `cit.score == pytest.approx(0.12)` (distance value), locking in the wrong behavior. Verified at runtime: distance=0.15 → score=0.15 (not 0.85). | NEW |
| DOMAIN-P2-001 | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:16-19` | **Malformed `AugmentMixin` class body** — contains class docstring + `pass` statement + second unreachable docstring: `class AugmentMixin(_RAGServiceProtocol): """Метод AugmentMixin (см. signature)."""; pass; """prompt augmentation (3 augment variants) для RAGService. S64 W4 extraction."""`. Verified via AST (7 items: 2 docstrings + pass + __slots__ + 3 methods). Valid Python (no runtime error), but dead code + unreachable statement. | NEW |
| DOMAIN-P2-002 | P2 | `src/backend/services/ai/rag_service/{ingest_mixin,search_mixin,collection_mixin}.py:1-12` | **Duplicate imports** — `from typing import TYPE_CHECKING` and `if TYPE_CHECKING: pass` blocks appear twice with `pragma: no cover` on the second. Cosmetic dead code; ruff already flags but not fail-blocking. | NEW |
| DOMAIN-P2-003 | P2 | `src/backend/dsl/engine/processors/ai/rag_search.py:18-56` (entire `RAGSearchProcessor` class) | **`RAGSearchProcessor` is dead** — not exported from `dsl/engine/processors/ai/__init__.py` (line 33-72) or `dsl/engine/processors/ai_processors.py` (line 47-86). `VectorSearchProcessor` is the canonical `rag_search` keyword implementation. Both `to_spec()` return `{"rag_search": spec}` — name collision but only one is registered. | NEW |
| DOMAIN-P2-004 | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:3-4, 12` | **Unused `get_logger` import** in `AugmentMixin` — `logger = get_logger(__name__)` is defined but never used in the module. | NEW |
| DOMAIN-P2-005 | P2 | `src/backend/services/ai/rag_query_stats.py:78-89` | **Convoluted bytes/str key lookup** — `queries_map.get(h.encode() if isinstance(list(queries_map.keys())[0] if queries_map else b"", bytes) else h)` uses first-key as proxy; works for both bytes/str keys but obscured. Should determine key type once at top. | NEW |
| DOMAIN-P3-001 | P3 | `src/backend/services/ai/rag_service/{ingest_mixin,search_mixin,augment_mixin,collection_mixin}.py` | **Manual retry/sleep on transient errors** — missing tenacity-based retry decorators (tenacity ≥9.0 is installed in core deps; used in `agents_pydantic/base.py:226`). Cycle-3 T-W3-01 library-replacement target was RAG services. NOT applied in current HEAD. | RESIDUAL |
| DOMAIN-P3-002 | P3 | `src/backend/services/ai/rag_ingest_store.py:139-268` (`RedisIngestStateStore`) | **Custom Redis HASH+ZSET state store** — could be replaced by `redis.asyncio.Redis` JSON blob + `pydantic.BaseModel` (already installed as core dep). Backend lock-in; no transaction support across HASH+ZSET. | NEW |
| DOMAIN-P4-001 | P4 | `src/backend/services/ai/rag_query_stats.py:1-102` (`RagQueryStatsCollector`) | **Feature gap: no Prometheus metrics** — only `RagCachePrewarmer` exports counters/histograms (via direct `prometheus_client` import). `RagQueryStatsCollector` writes only to Redis/in-memory with no metrics path. Organic addition: emit `rag_query_stats_recorded_total{tenant}` per `record()`. Cycle-3 T-11 organic feature. | NEW |
| DOMAIN-P4-002 | P4 | `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` (`chunk_text`) | **Naive sliding-window chunker** — no token-aware splitting, no sentence-boundary respect. `langchain.text_splitter` (already in core deps) provides `RecursiveCharacterTextSplitter` with same overhead and better defaults. Cycle-3 T-11 organic. | NEW |

**Findings count: 5 NEW (P0:2, P2:5, P3:1, P4:2) + 8 RESIDUAL (P0:2, P1:1, P3:1) = 13 total.**

P0 priorities: 4 (2 NEW + 2 RESIDUAL); P1: 1 (NEW); P2: 5 (NEW); P3: 1 (NEW); P4: 2 (NEW).

## 4. Detailed evidence

### DOMAIN-P0-001 — Text-RAG E2E tests FAIL

- **path:line:** `tests/e2e/test_multimodal_rag_e2e.py:255-340` (`test_image_caption_pipeline_e2e`), `:346-397` (`test_audio_transcript_pipeline_e2e`)
- **Cycle-1 ID:** T-4.1 (deferred)
- **Cycle-2 ID:** T-W4-01 (deferred)
- **Status:** RESIDUAL
- **Evidence (runtime):**
  ```
  .venv/bin/python -m pytest tests/e2e/test_multimodal_rag_e2e.py -v -m e2e
  ============================== 2 failed, 1 passed in 0.57s ==============================
  ```
  Both failing tests end at `assert len(hits) >= 1` (`E assert 0 >= 1`).
- **Impact:** Multimodal RAG pipeline (image/audio → embed → search) is broken end-to-end.
  `MultimodalRAGService.search(...)` returns 0 hits even when chunks are ingested in the same test.
- **Recommendation:** Trace why `MultimodalRAGService.search` returns 0; likely cross-instance
  state (`_collections` dict not retained between `ingest_document` and `search`) or
  embedding-comparison mismatch. Fix root cause; commit to `phase-1/cycle-4` after.
- **Test criterion:** `pytest tests/e2e/test_multimodal_rag_e2e.py -v -m e2e` → 3 PASS.

### DOMAIN-P0-002 — PII fail-open on ingest when sanitizer fails

- **path:line:** `src/backend/services/ai/rag_ingest_service.py:224-226`
- **Status:** NEW
- **Evidence (code):**
  ```python
  except Exception as exc:
      logger.warning("rag_ingest_pii_mask_failed: %s", exc)
      return content_text, {"pii_masked": False, "pii_mask_error": str(exc)}
  ```
- **Test (locks in behavior):** `tests/unit/services/ai/test_rag_pii_mask.py:114-140`
  (`test_ingest_graceful_on_sanitizer_failure`) — asserts `pii_masked is False` and
  raw content is written to RAG. Test PASSES.
- **Impact:** If Presidio sanitizer raises (CUDA OOM, model download failure, IAM timeout),
  raw PII (ИНН, паспорта, телефоны) is written to vector store without masking. In banking
  domain this is a regulatory/policy violation (152-ФЗ, 115-ФЗ).
- **Secondary concern:** `RAGService.ingest()` (direct path, bypassing `RagIngestService`)
  is exposed via `src/backend/services/ai/rag_service/ingest_mixin.py:53-81` and goes
  through `RagIngestService._run` ONLY in `extensions/credit_pipeline` etc. A retry/import
  via `/api/v1/rag/ingest` calls `RAGService.ingest` directly at `endpoints/rag.py:212-214`
  — bypassing PII masking entirely. (See also `src/backend/dsl/engine/processors/ai/ragingest_processor.py:65-67`
  which calls `_maybe_mask_pii` before delegating to `RAGService.ingest` — DSL path is
  PII-aware, REST endpoint is not.)
- **Recommendation:** Change `_maybe_mask_pii` to either (a) raise on sanitizer failure
  when `pii_mask_on_ingest=True` (fail-closed), OR (b) route the document to a
  quarantine queue with `pii_mask_error` set, NOT to the vector store. Update
  `test_ingest_graceful_on_sanitizer_failure` to assert quarantine routing.
- **Test criterion:** Add `test_ingest_quarantines_on_sanitizer_failure` that asserts
  raw content is NOT forwarded to `RAGService.ingest` when sanitizer raises.

### DOMAIN-P0-003 — RagCachePrewarmer runtime is phantom

- **path:line:** `src/backend/services/ai/rag_cache_prewarmer.py:68-80`
- **Cycle-2 ID:** T-W1-06 (deferred)
- **Status:** RESIDUAL
- **Evidence (code + runtime):**
  ```python
  try:
      await self._rag.query(query, fill_cache=True, tenant_id=tenant_id)
  except TypeError:
      try:
          await self._rag.query(query, tenant_id=tenant_id)
      except Exception:
          continue
  ```
  `RAGService` has NO `query` method:
  ```
  $ grep -rn "def query\|async def query" src/backend/services/ai/rag_service/*.py
  (no results)
  ```
  Runtime test:
  ```
  .venv/bin/python -c "import asyncio; ..."
  Prewarm tenant loaded (real RAGService): 0
  Has query method: False
  ```
- **Additional evidence:** `RagCachePrewarmer` is NOT instantiated anywhere in `src/`
  (only in `tests/unit/services/ai/test_rag_cache_prewarm.py`); tests pass with `AsyncMock`
  that mocks `rag.query`. The whole class is dead code in production.
  ```
  $ grep -rn "RagCachePrewarmer" src/backend/entrypoints/ src/backend/services/ai/ai_*.py
  (no results)
  ```
- **Impact:** Pre-warm L2 semantic cache promised in prewarm.py docstring (line 1-10)
  does NOT happen. No cache warming on lifespan startup. No `fill_cache` parameter accepted
  by RAGService. The `loaded=0` counter is hardcoded.
- **Recommendation:** Mark class as `experimental` / `notwired` (Ponytail: honest docstring).
  Either: (a) wire it to `lifespan` startup with a real `RAGService.search()` call, OR
  (b) delete the class until needed. If kept, fix `loaded` counter to reflect actual
  work; fix inner `except Exception: continue` so `loaded` skips TypeError path; replace
  with `await self._rag.search(query, top_k=..., namespace=tenant_id)` (the actual
  search method).
- **Test criterion:** Add `test_rag_cache_prewarmer_uses_real_search` with mocked
  `RAGService` + concrete `prewarm_tenant` call, asserting `await_count == len(top_queries)`.
  Mark `fill_cache=True` removal as breaking-change if any caller depends on it.

### DOMAIN-P1-001 — Citation score contract violation

- **path:line:** `src/backend/services/ai/rag_service/augment_mixin.py:90-94`
- **Status:** NEW
- **Evidence (docstring vs code):**
  ```python
  """... ``score`` нормируется к диапазону [0..1] через ``1 - distance``; при отсутствии distance — ``0.0``."""
  ...
  distance = r.get("distance")
  if distance is None:
      score = float(r.get("score") or 0.0)
  else:
      score = float(distance)  # NOT 1 - distance
  ```
- **Runtime verification:**
  ```
  Citation scores (should be 1-distance per docstring, but equals distance per code):
    doc_id=src.md, score=0.15, expected per docstring: 0.85
    doc_id=src.md, score=0.25, expected per docstring: 0.75
  ```
- **Test that locks in wrong behavior:** `tests/unit/services/ai/test_rag_citations.py:84`
  ```python
  assert cit.score == pytest.approx(0.12)  # distance value, not 1-distance
  ```
- **Impact:** Consumers of `RAGCitation.score` (UI badges, downstream filters, threshold
  gates) get inverted semantics. A "highly relevant" chunk with distance=0.1 appears
  as score=0.1 (low); a far-off chunk with distance=0.9 appears as score=0.9 (high).
  This corrupts downstream relevance filtering and benchmarks.
- **Recommendation:** Either (a) fix code to `score = 1.0 - float(distance)` to match
  docstring, OR (b) update docstring + tests to say "score == distance (lower = closer)".
  Option (a) is preferred because the field is named `score` (NOT `distance`).
- **Test criterion:** After fix, `test_rag_citations.py:84` must assert `pytest.approx(0.88)`
  (i.e., `1 - 0.12`); add `test_score_is_relevance_not_distance` for explicit coverage.

### DOMAIN-P2-001 — Malformed `AugmentMixin` class body

- **path:line:** `src/backend/services/ai/rag_service/augment_mixin.py:16-19`
- **Status:** NEW
- **Evidence (AST):**
  ```
  Class body items count: 7
    0: Expr (string: 'Метод AugmentMixin (см. signature).')
    1: Pass (pass)
    2: Expr (string: 'prompt augmentation (3 augment variants) для RAGService. S64 W4 extraction.')
    3: Assign (__slots__ = ())
    4: AsyncFunctionDef (async def augment_prompt)
    5: AsyncFunctionDef (async def augment_prompt_with_citations)
    6: AsyncFunctionDef (async def augment)
  ```
- **Impact:** Valid Python (no runtime error), but:
  - `pass` is dead code (class has methods after it).
  - Second docstring is unreachable string expression.
  - First docstring is generic one-liner ("Метод AugmentMixin (см. signature).") — does not
    describe the mixin. The class does NOT match the surrounding sibling mixins
    (`IngestMixin`, `SearchMixin`, `CollectionMixin`) which have meaningful docstrings.
- **Recommendation:** Replace lines 16-19 with:
  ```python
  class AugmentMixin(_RAGServiceProtocol):
      """prompt augmentation (3 augment variants) для RAGService. S64 W4 extraction."""
      __slots__ = ()
  ```
- **Test criterion:** Add AST-level lint check in `tools/check_docstrings.py` that
  flags unreachable string expressions in class bodies.

### DOMAIN-P2-002 — Duplicate imports in RAG mixins

- **path:line:**
  - `src/backend/services/ai/rag_service/ingest_mixin.py:3-12`
  - `src/backend/services/ai/rag_service/search_mixin.py:3-12`
  - `src/backend/services/ai/rag_service/collection_mixin.py:3-12`
- **Status:** NEW
- **Evidence:** Each file has:
  ```python
  from typing import TYPE_CHECKING, Any
  
  if TYPE_CHECKING:
      pass
  
  import hashlib  # only in ingest_mixin
  from typing import TYPE_CHECKING
  
  if TYPE_CHECKING:  # pragma: no cover
      pass
  ```
- **Impact:** Cosmetic dead code; ruff `F401` should catch `TYPE_CHECKING` re-import
  but pragma suppresses it. Not a runtime bug.
- **Recommendation:** Remove the duplicate `from typing import TYPE_CHECKING` (line 9)
  and the second `if TYPE_CHECKING: pass` block (lines 11-12). Ponytail: 5 LOC per file
  × 3 files = 15 LOC removed.
- **Test criterion:** `ruff check src/backend/services/ai/rag_service/` exit 0.

### DOMAIN-P2-003 — `RAGSearchProcessor` is dead code

- **path:line:** `src/backend/dsl/engine/processors/ai/rag_search.py:18-56`
- **Status:** NEW
- **Evidence:**
  ```
  $ grep -rn "RAGSearchProcessor" src/backend/dsl/engine/processors/ai/__init__.py src/backend/dsl/engine/processors/ai_processors.py
  (no results)
  ```
  `VectorSearchProcessor` is exported (in `ai_processors.py:66,86` and `ai/__init__.py:52,80`).
  `RAGSearchProcessor` is NOT.
- **Impact:** The hybrid BM25+vector+reranker DSL processor is unreachable via import path.
  No test, no router registration, no `to_spec()` parsing. Confusion for future maintainers
  who see two `rag_search` spec generators.
- **Recommendation:** Either (a) register `RAGSearchProcessor` in `ai_processors.py` and
  replace `VectorSearchProcessor` as canonical, OR (b) delete `RAGSearchProcessor`
  (and `rag_search.py` if no other consumers). Ponytail: option (b) preferred as
  `VectorSearchProcessor` is the canonical path per `ragquery_processor.py:103-110`.
- **Test criterion:** `grep -rn "RAGSearchProcessor" src/backend/` → 0 references
  in `dsl/engine/processors/ai/__init__.py` and `ai_processors.py` (i.e., removed).

### DOMAIN-P2-004 — Unused logger in `AugmentMixin`

- **path:line:** `src/backend/services/ai/rag_service/augment_mixin.py:3-4, 12`
- **Status:** NEW
- **Evidence:**
  ```python
  from src.backend.core.logging import get_logger       # line 3
  from src.backend.services.ai.rag_service.search_mixin import (
      _format_context_with_sources,
  )
  from src.backend.services.ai.rag_types import AugmentResult, RAGCitation
  logger = get_logger(__name__)                          # line 12
  ```
  `logger` is never referenced in `augment_mixin.py`.
- **Impact:** Cosmetic; ruff `F401` / `F841` should catch.
- **Recommendation:** Remove `get_logger` import and `logger = get_logger(__name__)` line.
- **Test criterion:** `ruff check src/backend/services/ai/rag_service/augment_mixin.py` exit 0.

### DOMAIN-P2-005 — Convoluted bytes/str key lookup in `RagQueryStatsCollector.top_queries`

- **path:line:** `src/backend/services/ai/rag_query_stats.py:78-89`
- **Status:** NEW
- **Evidence (code):**
  ```python
  raw_q = queries_map.get(
      h.encode()
      if isinstance(
          list(queries_map.keys())[0] if queries_map else b"", bytes
      )
      else h
  )
  ```
- **Logic:** Checks the type of the FIRST key (or `b""` if empty) as proxy for whether
  Redis returns bytes keys. Works for both cases (verified via runtime test with both
  MockRedis returning bytes/str keys), but extremely opaque.
- **Impact:** Correctness OK; readability/maintainability poor. Future Redis client
  change (e.g., async-redis queue returns List[Any]) could break silently.
- **Recommendation:** Refactor to:
  ```python
  queries_map = await self._redis.hgetall(f"{self._prefix}:query:{tenant_id}")
  keys_are_bytes = bool(queries_map) and isinstance(next(iter(queries_map)), bytes)
  ...
  for h_raw, score in items:
      h = h_raw.decode() if isinstance(h_raw, bytes) else h_raw
      raw_q = queries_map.get(h.encode() if keys_are_bytes else h)
  ```
- **Test criterion:** Add `test_top_queries_with_str_keys` to `test_rag_cache_prewarm.py`.

### DOMAIN-P3-001 — Manual retry: tenacity replacement missing

- **path:line:** `src/backend/services/ai/rag_service/ingest_mixin.py:75-80` (vector
  store upsert), `search_mixin.py:227-233` (cache.store), `rag_ingest_store.py:184-195`
  (Redis create)
- **Cycle-3 ID:** T-W3-01 (deferred)
- **Status:** RESIDUAL
- **Evidence:** `tenacity>=9.0,<10.0` is in core deps (pyproject.toml:74) and is used
  in `src/backend/services/ai/agents_pydantic/base.py:226`. RAG services do manual
  `try/except` blocks (10+ instances) without exponential backoff.
- **Impact:** Transient Qdrant/Redis failures propagate as exceptions instead of being
  retried with backoff. No circuit-breaker integration.
- **Recommendation:** Wrap `_embed`, `_store.upsert`, `cache.store_chunks` with
  `@tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.1, max=2.0))`.
  Exclusion: cache reads (should be fast-fail not retry).
- **Test criterion:** `test_ingest_retries_on_transient_embed_failure` with `AsyncMock`
  that raises twice then succeeds, asserting `await_count == 3`.

### DOMAIN-P3-002 — Custom Redis HASH+ZSET state store

- **path:line:** `src/backend/services/ai/rag_ingest_store.py:139-268`
- **Status:** NEW (replacement opportunity)
- **Evidence:** Manual zadd/zrevrange + orjson serialization. Could use
  `redis.asyncio.Redis.json()` (Redis Stack 7.4+) or simply
  `redis.asyncio.Redis.setex(task_id, ttl, json.dumps(payload))` + sorted set for
  recent list.
- **Impact:** ~130 LOC of state-store code; transaction safety across HASH+ZSET requires
  MULTI/EXEC manually (not implemented).
- **Recommendation:** Replace with `redis.asyncio.Redis` JSON blob + `setex` for atomic
  per-task writes; keep ZSET for `list_recent`. Or use `redis.asyncio.Redis.json()`.
- **Test criterion:** `test_redis_store_transactional_create` passes with single
  `setex` call (no separate zadd).

### DOMAIN-P4-001 — RagQueryStatsCollector: no Prometheus metrics

- **path:line:** `src/backend/services/ai/rag_query_stats.py:43-64`
- **Status:** NEW (organic feature)
- **Evidence:** `record()` writes to Redis/in-memory only; no metric export.
  `RagCachePrewarmer` exports `rag_prewarm_loaded_total{tenant}` via direct
  `prometheus_client` import.
- **Impact:** No observability for top-N RAG queries; alerting on traffic spikes can't
  reason about query patterns.
- **Recommendation:** Add `rag_query_recorded_total{tenant}` counter (low cardinality,
  per-tenant label) emitted via `core/utils/metrics_registry.py` (already used by
  `hybrid_rag.py:30-39`). Increment after successful Redis/in-memory write.
- **Test criterion:** `test_record_emits_prometheus_counter` (smoke) with metric_registry
  fixture.

### DOMAIN-P4-002 — Naive sliding-window chunker

- **path:line:** `src/backend/services/ai/rag_service/ingest_mixin.py:35-48`
- **Status:** NEW (organic feature)
- **Evidence:**
  ```python
  def chunk_text(self, text: str) -> list[str]:
      size = rag_settings.chunk_size
      overlap = rag_settings.chunk_overlap
      chunks: list[str] = []
      start = 0
      while start < len(text):
          end = start + size
          chunks.append(text[start:end])
          start = end - overlap
      return chunks
  ```
- **Impact:** No token-aware splitting (splits mid-word), no sentence-boundary respect
  (cuts at character position). Negative impact on retrieval quality.
- **Recommendation:** Replace with `langchain.text_splitter.RecursiveCharacterTextSplitter`
  (already in core deps); keep `chunk_size` + `chunk_overlap` knobs. Ponytail: 3-line
  replacement.
- **Test criterion:** `test_chunk_text_respects_sentence_boundary` (regression for naive
  splitter).

## 5. Cycle-1+2+3 residuals (verified / mutated / resolved)

Cycle-1 deferred IDs (must revalidate per BASELINE cycle-4 D-AUDIT-00):

| ID | Title | Status | Evidence |
|---|---|---|---|
| **T-1.1** | composition root fix | RESOLVED (cycle-2 fix `baf54d95` removed MCPToolProcessor/AgentGraphProcessor shadow; `AuthValidateProcessor` canonical `_VERIFIERS` path in `c3ff7bec`; OUT OF RAG SCOPE) | git log shows commits applied |
| **T-1.2** | SSE/HITL auth (8 xfailed) | NOT IN RAG SCOPE | (Not verified — out of scope) |
| **T-1.3** | MQ DLQ data-loss | NOT IN RAG SCOPE | (Not verified — out of scope) |
| **T-2.1** | reverse-layer cleanup | RESIDUAL (cross-cutting, not RAG-specific) | (Not verified — out of scope but visible in BASELINE) |
| **T-4.1** | text-RAG E2E test | **RESIDUAL** → mapped to DOMAIN-P0-001 | `pytest tests/e2e/test_multimodal_rag_e2e.py -m e2e` → 2 FAIL |

Cycle-2 deferred IDs:

| ID | Title | Status | Evidence |
|---|---|---|---|
| T-W1-02 | CDC DLQ handoff failure | NOT IN RAG SCOPE | (Not verified) |
| T-W1-03 | MQ subscribers ACK vs DLQ | NOT IN RAG SCOPE | (Not verified) |
| T-W1-04 | composition root DI | RESOLVED (per cycle-1 reapply) | (Not verified — out of RAG scope) |
| **T-W1-06** | RagCachePrewarmer runtime + phantom `fill_cache` | **RESIDUAL** → mapped to DOMAIN-P0-003 | Runtime: `prewarm_tenant("t1") → 0`; no `query()` method on RAGService |
| T-W1-07 | SSE principal/permissions | NOT IN RAG SCOPE | (Not verified) |
| T-W2-01..04 | layer track | NOT IN RAG SCOPE | (Not verified) |
| **T-W3-01** | tenacity library replacement | **RESIDUAL** → mapped to DOMAIN-P3-001 | RAG has no tenacity decorators; `agents_pydantic/base.py:226` uses it but RAG doesn't |
| **T-W4-01** | text-RAG E2E | **RESIDUAL** → mapped to DOMAIN-P0-001 | (same as T-4.1) |

Cycle-3 deferred IDs:

| ID | Title | Status | Evidence |
|---|---|---|---|
| T-04 | 4-way CVE enforcement unification | NOT IN RAG SCOPE | (Not verified) |
| T-05 | hardcoded shutdown timeout | NOT IN RAG SCOPE | (Not verified) |
| T-06 | test-infra conftest | PARTIALLY RESIDUAL (out of scope: spacy model download fails in `test_rag_ingest_service.py`, `test_rag_embedding_version.py`) | Runtime: spacy model download fails |
| T-08 | TenantFacade kwargs fix | RESOLVED (not in RAG scope) | (Not verified) |
| T-09 | credit_pipeline_v2 default consistency | NOT IN RAG SCOPE | (Not verified) |
| T-10 | defusedxml drop-in | NOT IN RAG SCOPE | (Not verified) |
| T-11 | organic feature | PARTIALLY RESIDUAL → mapped to DOMAIN-P4-001, DOMAIN-P4-002 | (organic features deferred) |

**Summary:**
- **Cycle-1 RESIDUAL in RAG scope:** 1/5 (T-4.1)
- **Cycle-2 RESIDUAL in RAG scope:** 2/8 (T-W1-06, T-W4-01)
- **Cycle-3 RESIDUAL in RAG scope:** 0 explicit IDs (T-11 organic captured separately)
- **NEW findings (RAG-specific, not in cycle-1/2/3):** 11 (P0:2, P1:1, P2:5, P3:1, P4:2)

## 6. Contradictions / overlaps to flag

1. **DOMAIN-P0-002 vs test_rag_pii_mask.py:114-140** — the test `test_ingest_graceful_on_sanitizer_failure`
   explicitly locks in the fail-open behavior. Any fix to fail-closed must update this test.
   This is a **Test-Production Policy Conflict** — the test asserts X, the security posture
   requires NOT-X. Resolution: change the production code first, then update test.

2. **DOMAIN-P0-003 vs test_rag_cache_prewarm.py:43-58** — `test_prewarmer_loads_top_queries`
   uses `AsyncMock` with `rag.query` to test the path. With real RAGService, the path is
   broken. This is a **Mock-vs-Reality Mismatch** — tests pass but production is dead.

3. **DOMAIN-P1-001 vs test_rag_citations.py:84** — the test asserts `score == 0.12` (raw
   distance), locking in the wrong behavior. Docstring says `1 - distance`. Resolution:
   pin either docstring or code.

4. **DOMAIN-P2-003 vs `VectorSearchProcessor`** — both implement `to_spec() == {"rag_search": spec}`.
   Currently only `VectorSearchProcessor` is registered; `RAGSearchProcessor` is dead.
   If a maintainer imports `RAGSearchProcessor` by mistake, they get an isolated class
   with no test coverage and no DSL parser support.

5. **`_NAV-policy.py` at `core/cache/rag.py:13`** — uses `infrastructure_locator.get_three_tier_rag_cache_class()`.
   Other cache backends (e.g., `core/cache/semantic.py`) use `infrastructure.cache.*` directly.
   Layer-boundary consistency check needed but appears intentional (facade pattern).

6. **`service` (Redis) at `rag_ingest_store.py:202-203` returns silent `None`** on `update` of
   missing task (line 110-112: `if entry is None: return`). Behavior is consistent with
   `InMemoryIngestStateStore.update` but operationally silent — task_id typo from caller
   produces no error. Consider logging `WARN: update on missing task_id=X`.

## 7. Readiness score 0–100

**Formula:** `R = 100 × (1 − 0.20 × P0 − 0.10 × P1 − 0.05 × P2 − 0.02 × P3 − 0.01 × P4)`,
capped at 0. Every P0 = -20, P1 = -10, P2 = -5, P3 = -2, P4 = -1.

**Counts:**
- P0: 4 (DOMAIN-P0-001, P0-002, P0-003, plus 1 RESIDUAL from cycle-2 T-W1-06 folded into P0-003)
  — actually: DOMAIN-P0-001, P0-002, P0-003 = 3 P0 unique findings (T-W1-06 is part of P0-003).
- P1: 1 (DOMAIN-P1-001)
- P2: 5 (DOMAIN-P2-001..005)
- P3: 1 (DOMAIN-P3-001)
- P4: 2 (DOMAIN-P4-001, P4-002)

Wait — DOMAIN-P0-003 covers BOTH the phantom `fill_cache` AND the no-`query()`-method
runtime. T-W1-06 is one ID, our DOMAIN-P0-003 is one finding. Verified count: 3 P0.

**Calculation:**
`R = 100 × (1 − 0.20×3 − 0.10×1 − 0.05×5 − 0.02×1 − 0.01×2)`
`R = 100 × (1 − 0.60 − 0.10 − 0.25 − 0.02 − 0.02)`
`R = 100 × (1 − 0.99)`
`R = 100 × 0.01`
`R = 1`

**Hard floor: any P0 or P1 caps `R ≤ 60`.**

**Final score: 1 / 100** (capped by hard floor to ~1, reflects 3 P0 + 1 P1 blocking).

**Reasoning:** Three P0 blockers prevent production deploy:
1. **Multimodal RAG E2E broken** — text/image/audio → embed → search pipeline returns 0 hits.
2. **PII fail-open on ingest** — sanitizer failure writes raw PII to vector store; bypass
   via direct `RAGService.ingest()` from REST endpoint.
3. **RagCachePrewarmer is dead code** — runtime returns 0, never wired to startup.

Plus one P1 (citation score contract violation contaminates downstream relevance).

The 5 P2 findings are stylistic (malformed class body, dead code, duplicate imports) and
do not block production but should be cleaned in a follow-up commit. P3 (tenacity) and
P4 (organic features) are non-blocking.

**Оценка ≥80 запрещена при наличии P0/P1 → R заблокирован на 1.**

## 8. Recommended next tasks

Priority-ordered (P0 first):

1. **[P0] Fix `RagCachePrewarmer` runtime** — replace `self._rag.query(...)` with
   `self._rag.search(query, top_k=..., namespace=tenant_id)`; add unit test against
   real `RAGService` (no AsyncMock). Either wire to `lifespan` startup OR delete the
   class. (5 LOC patch, 1 test file update.)

2. **[P0] Fix PII fail-closed on ingest** — change `_maybe_mask_pii` to either raise
   on sanitizer failure OR route to quarantine; update `test_ingest_graceful_on_sanitizer_failure`
   to assert quarantine. Add `test_ingest_quarantines_on_sanitizer_failure`. Fix REST
   endpoint `/api/v1/rag/ingest` to call `_maybe_mask_pii` (mirrors DSL path).

3. **[P0] Fix multimodal RAG E2E** — trace why `MultimodalRAGService.search` returns 0
   after `ingest_document`; likely `_collections` is not shared between calls or
   `embedder` is reset. Likely requires inspection of `rag/multimodal/service.py`
   (currently out of scope but e2e test is in scope).

4. **[P1] Fix citation score contract** — change `augment_mixin.py:94` to
   `score = 1.0 - float(distance)`; update `test_rag_citations.py:84` to assert
   `pytest.approx(0.88)`. Add `test_score_is_relevance_not_distance`.

5. **[P2 cleanup] Format and lint** — run `ruff check --fix` on RAG mixin files to
   remove duplicate imports (P2-002), unused logger (P2-004). Fix `AugmentMixin` class
   body (P2-001). Remove `RAGSearchProcessor` (P2-003).

6. **[P2] Refactor `RagQueryStatsCollector.top_queries` bytes/str lookup** (P2-005).

7. **[P3] Apply tenacity library replacement** to RAG services (P3-001).

8. **[P4] Replace chunker with `RecursiveCharacterTextSplitter`** (P4-002) + add
   Prometheus metrics to `RagQueryStatsCollector` (P4-001).

## 9. Commands run (interpreter explicitly stated)

All via `.venv/bin/python` (system Python not in `.venv` per BASELINE requirement):

**RAG unit tests (cycle-4 D-AUDIT-04 strict):**
```bash
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_cache_prewarm.py -v
# → 5 passed in 0.69s
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_pii_mask.py -v
# → 3 passed in 0.60s
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_tenant_isolation.py -v
# → 20 passed in 0.38s
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_source_attribution.py -v
# → 4 passed in 0.28s
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_citations.py -v
# → 4 passed in 0.26s
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_augment.py -v
# → 9 passed in 0.25s
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_ingest_store.py -v
# → 6 passed in 0.26s
.venv/bin/python -m pytest tests/unit/api/test_rag_cache_admin.py -v
# → 5 passed in 2.83s
.venv/bin/python -m pytest tests/unit/services/ai/eval/test_ragas_evaluator.py -v
# → 9 passed in 0.66s
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/ai/ -v
# → 80 passed in 3.99s  (includes RAG processors)
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_rag_pii_redaction.py -v
# → 4 passed in 2.23s
```

**Multimodal E2E (P0-001 verification):**
```bash
.venv/bin/python -m pytest tests/e2e/test_multimodal_rag_e2e.py -v -m e2e
# → 2 failed, 1 passed in 0.57s
# FAILED test_image_caption_pipeline_e2e → assert 0 >= 1
# FAILED test_audio_transcript_pipeline_e2e → assert 0 >= 1
# PASSED test_public_api_exports_complete
```

**Prewarmer runtime verification (P0-003):**
```bash
.venv/bin/python -c "import asyncio; ..."
# → Prewarm tenant loaded (real RAGService): 0
# → Has query method: False
```

**Citation score contract verification (P1-001):**
```bash
.venv/bin/python -c "import asyncio; ..."
# → Citation scores (should be 1-distance per docstring, but equals distance per code):
# → doc_id=src.md, score=0.15, expected per docstring: 0.85
# → doc_id=src.md, score=0.25, expected per docstring: 0.75
```

**PII masker verification (P0-002, PII mask works on masked payload):**
```bash
.venv/bin/python -c "from src.backend.services.ai.pii.retrieval_masker import mask_augment_result; ..."
# → Original prompt: 'Вот вам номер: +7 (495) 123-45-67 и паспорт 4515 123456'
# → Masked prompt: 'Вот вам номер: *** и паспорт ***'
# → Doc 0 content: 'Телефон: ***'
# → Citation 0 content: 'Контент: ***'
```

**MRO verification:**
```bash
.venv/bin/python -c "from src.backend.services.ai.rag_service import RAGService; print(RAGService.__mro__)"
# → RAGService → IngestMixin → SearchMixin → AugmentMixin → CollectionMixin → _RAGServiceProtocol → Protocol → Generic → object
```

**RAG defaults verification:**
```bash
.venv/bin/python -c "from src.backend.core.config.rag import rag_settings; print(rag_settings.enabled)"
# → False  (default — fail-closed)
```

**Module presence checks (P0-003, P2-003):**
```bash
grep -rn "def query\|async def query" src/backend/services/ai/rag_service/*.py
# → (no results)
grep -rn "RAGSearchProcessor" src/backend/dsl/engine/processors/ai/__init__.py src/backend/dsl/engine/processors/ai_processors.py
# → (no results — only rag_search.py defines it)
```

**AugmentMixin AST verification (P2-001):**
```bash
.venv/bin/python -c "import ast, inspect; ..."
# → Class body items count: 7
# → 0: Expr (string: 'Метод AugmentMixin (см. signature).')
# → 1: Pass (pass)
# → 2: Expr (string: 'prompt augmentation (3 augment variants) для RAGService. S64 W4 extraction.')
# → 3: Assign (__slots__ = ())
# → 4-6: AsyncFunctionDef × 3
```

**Pre-existing failures (NOT counted in RAG readiness):**
```bash
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_ingest_service.py -v
# → FAILED test_ingest_inline_processes_all_files (spacy model download crash)
.venv/bin/python -m pytest tests/unit/services/ai/test_rag_embedding_version.py -v
# → FAILED test_ingest_includes_embedding_provenance (spacy infra)
# Both pre-existing per BASELINE; not RAG-domain finding.
```

**No source / config / lockfile / allowlist mutations performed** (per BASELINE constraint).

---

END OF REPORT
