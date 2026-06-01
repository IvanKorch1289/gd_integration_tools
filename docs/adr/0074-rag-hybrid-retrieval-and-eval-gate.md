# ADR-0074 — RAG hybrid retrieval, embedding provenance, source attribution & eval gate

* Статус: **Accepted** (2026-05-25, Phase B Block 3 closure).
* Связано с: PLAN.md V22.4 §S26 (Prompts + Skills) и §S27 (Agent DSL + MCP);
  директива пользователя 2026-05-22 (Block 3 RAG improvements).
* Память: [[feedback_phase_a_ai_hardening]], [[feedback_sprint24_w1_presidio]].

## Контекст

Существующая RAG-инфраструктура (`RAGService` + `RagIngestService` + `RagCacheSettings`)
покрывает dense retrieval + L1/L2/L3 cache + augment_prompt, но не учитывает
пять production-критичных gap'ов из директивы пользователя 2026-05-22:

1. **Reranker — token-overlap heuristic** (`rag_reranker.py`), пропускает
   semantic match с разной лексикой. Production-grade требует cross-encoder
   (BGE-reranker v2-m3 multilingual).
2. **Dense-only retrieval** — пропускает lexical keywords (ИНН, СНИЛС, номер
   договора), которые не в embedding пространстве; нужно BM25.
3. **No source attribution** — LLM не получает явных `[источник: ...]`
   маркеров → compliance-аудит невозможен в банковском домене.
4. **Embedding version не tracked** в chunk metadata — при смене модели
   старые chunks остаются в Qdrant и retrieval возвращает несовместимые
   embeddings.
5. **Нет CI-gate качества RAG** — изменения RAG-pipeline не проверяются
   автоматически на регрессию faithfulness / answer_relevancy.

## Решение

### Block 3.1 — BGE-reranker v2-m3 как production-default

* `BGESettings.reranker_enabled: bool = False` (default-OFF в base; ON в
  staging/prod после `make pii-bootstrap` + cross-encoder weights).
* `_RagRerankerPipeline.forward()` lazy-init `FlagEmbedding.FlagReranker`
  (`BAAI/bge-reranker-v2-m3` multilingual ru/en/zh+). compute_score —
  cross-encoder relevance с FP16-half-precision (×2 memory savings).
* Graceful fallback на token-overlap при ImportError `rank-bm25` /
  init error / runtime CUDA OOM. Counter `rag_reranker_fallback_total`
  для observability.

### Block 3.2 — Hybrid Retriever (dense + BM25 + RRF)

* NEW `services/ai/rag/hybrid_retriever.py::HybridRetriever`:
  * dense_search callable + corpus list для BM25;
  * RRF formula: `score(d) = Σ_lists 1/(k + rank+1)`, k=60 default (Cormack
    et al. 2009);
  * lazy-init `rank_bm25.BM25Okapi` через extra `[rag-advanced]`;
  * graceful fallback на dense-only при unavailable BM25.
* `RAGSettings.{hybrid_enabled, rrf_k=60}`.
* `HybridResult` dataclass с provenance sources (dense/bm25/both).

### Block 3.3 — Source attribution в augmented prompt

* `RAGSettings.source_attribution_enabled: bool = True` (default-ON, не имеет
  compliance-impact).
* `_format_context_with_sources()` обогащает каждый chunk маркером
  `[источник: <source_id>]` ДО LLM-prompt.
* Priority извлечения source: `metadata.source` → `metadata.filename` →
  `metadata.doc_id` → `chunk.id`.

### Block 3.5 — Embedding provenance в chunk metadata

* `RagIngestService` добавляет в metadata 3 поля:
  `embedding_provider`, `embedding_model`, `chunker_fingerprint_version`.
* `RAGService.search` применяет `_filter_by_embedding_version()`:
  * non-strict (default): mismatch → counter inc + warn log, chunk остаётся;
  * `embedding_strict_mode=True`: mismatch → chunk фильтруется.
  * legacy chunks без provenance — пропускаются без strict-фильтра
    (backward-compat).
* Counter `rag_model_mismatch_total{chunk_model, current_model}`.

### Block 3.4 — Ragas CI gate (carryover)

* NEW `services/ai/eval/ragas_runner.py::RagasNightlyRunner` (carryover —
  требует [ai-quality] extra + synthetic dataset 15-30 QA пар).
* `tests/nightly/test_ragas_eval.py` — faithfulness ≥ 0.8 + answer_relevancy ≥ 0.7.
* `Makefile::eval-rag` target.

## Альтернативы (отвергнуто)

* **MMR (Maximal Marginal Relevance) вместо RRF** — добавляет diversity, но
  не учитывает lexical match (BM25). RRF + diversity rerank — следующая
  итерация.
* **Cohere Rerank API** — SaaS-only, нарушает on-prem requirement (см.
  ADR-0066 единый AI Gateway).
* **Strict-mode embedding фильтр default-ON** — сломает existing chunks
  без provenance (ingested до Block 3.5). Default-OFF + warn-counter — даёт
  observability без disruption.

## Verification

```bash
# Block 3.1 BGE reranker
BGE_RERANKER_ENABLED=true uv run pytest tests/unit/services/ai/dspy/test_bge_reranker.py -v
# Expected: 4 passed

# Block 3.2 Hybrid retriever
uv run pytest tests/unit/services/ai/rag/test_hybrid_retriever.py -v
# Expected: 7 passed

# Block 3.3 Source attribution
uv run pytest tests/unit/services/ai/test_rag_source_attribution.py -v
# Expected: 4 passed

# Block 3.5 Embedding version
uv run pytest tests/unit/services/ai/test_rag_embedding_version.py -v
# Expected: 5 passed

# Block 3.4 (carryover)
make eval-rag  # после реализации Ragas runner
```

### Production observability

* `rate(rag_reranker_fallback_total[5m]) > 0` — алерт NER reranker деградация.
* `rate(rag_hybrid_fallback_total[5m]) > 0` — BM25 unavailable.
* `rate(rag_model_mismatch_total[5m]) > 0` — re-embed gap (chunks с устаревшей
  моделью).

## Migration

* default-OFF `reranker_enabled` и `hybrid_enabled` — не нарушает existing
  RAG callers.
* `source_attribution_enabled=True` default-ON, но добавляет только маркеры
  в context — LLM-output форматирование автоматически адаптируется
  (existing system_prompts уже включают "use sources" rules).
* legacy chunks без `embedding_model` — warn-counter без strict-filter
  (production переход на strict — после `make rag-reindex` job).

## Consequences

### Positive

* Cross-encoder reranker даёт +10..15% NDCG@5 на ru-domain (BGE v2-m3
  benchmarks).
* Hybrid retrieval ловит lexical match (ИНН, СНИЛС, номер договора) что
  критично для compliance audit trail.
* Source attribution разблокирует production AI в банке (152-ФЗ +
  internal audit).
* Embedding provenance даёт observability re-embed gap и предотвращает
  silently broken retrieval после смены модели.

### Negative

* BGE-reranker — +20..50ms p95 на batch 5-10 docs (CPU mode); GPU инстанс
  даёт <10ms.
* `rank-bm25` corpus held in memory — растёт линейно с количеством
  документов (mitigation: corpus snapshot обновляется при ingest, не на
  каждом запросе).
* `embedding_model` mismatch counter может быть шумным во время re-embed —
  alert threshold `> 100/min`, не `> 0`.

### Carryover

* Block 3.4 Ragas CI gate — отдельный wave с [ai-quality] extra.
* RAGService.search wiring HybridRetriever — после corpus loader.
* `make rag-reindex` job для batch re-embed существующих chunks.
* Production tuning: BGE FP16 vs FP32, RRF k=60 vs domain-specific.

## Связи с другими ADR

* ADR-0072 — PII production enforcement (RAG ingest mask + retrieval mask).
* ADR-0066 — AI Gateway facade (RAG ingest/retrieve через единый pipeline).
* ADR-0075 — UnifiedAgentMemoryGateway (RAG retrieve может быть memory
  source).
* ADR-0067 — AI Policy Spec DSL (policy.rag.sources allowlist).
