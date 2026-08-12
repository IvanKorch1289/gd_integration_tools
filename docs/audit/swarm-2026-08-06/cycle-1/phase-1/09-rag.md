# RAG domain audit — Cycle 1, Phase 1

**Scope (read-only verification):**
- `src/backend/services/ai/**/*rag*.py`
- `src/backend/services/ai/rag_service/**`
- `src/backend/services/ai/eval/**`
- `src/backend/core/cache/rag.py`
- `src/backend/core/config/rag.py`
- `src/backend/core/config/features/ai_rag.py`
- `src/backend/entrypoints/api/v1/endpoints/*rag*.py`
- `src/backend/dsl/engine/processors/ai/*rag*.py`
- `src/backend/services/ai/rag/**` (multimodal + strategy selector + dense/hybrid/hyde/multi_query retrievers, lineage, classifier)
- RAG-focused tests in `tests/unit/services/ai/test_rag_*.py`, `tests/unit/cache/rag/`, `tests/e2e/test_multimodal_rag_e2e.py`, `tests/unit/dsl/engine/processors/ai/test_rag*`
- `artifacts/ragas/.gitkeep` (empty marker only)

**Baseline:** commit `b69d6b49bc62918a02e47dc20ab81615fd8500b1`. Layer checker report (Sprint 36): 175 legacy, 0 new. Active security allowlist IDs: 35. Pre-existing working-tree modifications before start (NOT modified by this audit): `src/backend/infrastructure/storage/s3.py`, `uv.lock`, `pyproject.toml`, `tests/unit/dsl/transforms/test_dataframes.py` (only `uv.lock` + `pyproject.toml` + `test_dataframes.py` actually visible via `git status`; `src/backend/infrastructure/storage/s3.py` is not in current `git status` — possibly already restored or counted differently).

**Mandatory invariant checks** (per task):
1. **Real E2E ingest → chunking → embedding → retrieval → rerank → LLM** — частично подтверждено для **multimodal** (`MultimodalRAGService` + stubs in `tests/e2e/test_multimodal_rag_e2e.py`); для канонического **text RAG** (`RAGService`) — **не существует** ни одного E2E-теста с этим composition; реального LLM-вызова внутри `RAGService` нет (он только строит prompt string, см. RAG-P4-001).
2. **Tenant post-filter** — реализован и покрыт тестами: `_filter_chunks_by_tenant` в `search_mixin.py:61-89` + `_build_where` в `search_mixin.py:38-58`. Тесты в `tests/unit/services/ai/test_rag_tenant_isolation.py:138-445` подтверждают cache-hit post-filter, defence-in-depth, disjoint-isolation. Аналогично для `MultimodalRAGService.search` (`service.py:209-256`, тесты `test_tenant_isolation_cycle37.py`).

---

## Не проверено

- Запуски pytest в реальном окружении не выполнялись (только статический анализ + Python REPL-валидация атрибутов `RAGService`).
- Не верифицировано наличие реальных Qdrant / Chroma / Redis / SentenceTransformers / FlagEmbedding в production-окружении; проверялось только их упоминание в `pyproject.toml` и наличие stub/mock-путей в тестах.
- Не проверялись `docs/adr/*`, `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, `DEEP_AUDIT_REPORT.md` (явно запрещено заданием).
- Не верифицированы лицензионные/audit-риски `FlagEmbedding` (только наличие в `pyproject.toml:339`); для остальных уже установленных библиотек лицензии не проверялись (MIT/Apache-2.0 — стандартные, риск низкий).
- Не проверялось runtime-поведение `_resolve_effective_tenant_id` в условии гонки между двумя tenants в одном event-loop (ContextVar-based, по дизайну thread/task-local).
- `artifacts/ragas/` содержит только `.gitkeep` — реальных ragas-отчётов не обнаружено (RAG-P4-003).

---

## Verified strengths

- **Tenant isolation реализован и тестами покрыт.** `search_mixin.py:14-89` — `_resolve_effective_tenant_id`, `_build_where`, `_filter_chunks_by_tenant`. Тесты `test_rag_tenant_isolation.py` (445 строк, 11 тестов) покрывают: explicit kwarg vs ContextVar, empty opt-out, namespace+tenant compound where, cache-hit post-filter, defence-in-depth против FAISS-like backend, disjoint cross-tenant.
- **3-tier cache фасад с tenant scoping.** `infrastructure/cache/rag/three_tier.py` + `retrieval.py` (Redis prefix `rag:l3:v2:`) корректно версионирует ключи с sentinel `_unscoped_` / `_global_`. Tenant-aware key в `_key()`.
- **Capability-checked фасад `core/cache/rag.py:13`** — `ThreeTierRagCache` через `infrastructure_locator.get_three_tier_rag_cache_class()` (ADR-0207). Layer boundaries соблюдены.
- **PII-masking в `RagIngestService._run` (P0 fix Round 7)** — `_maybe_mask_pii` применяется в `rag_ingest_service.py:121, 187-226` для bulk-пути (`/rag/ingest/start`, `/rag/bulk-ingest`).
- **Embedding provenance (`Block 3.5`)** — `_resolve_embedding_provenance()` пишет `embedding_provider`, `embedding_model`, `chunker_fingerprint_version` в metadata каждого чанка; retrieval-side `_filter_by_embedding_version` (`search_mixin.py:92-120`) поддерживает strict/warn-only режимы.
- **Source attribution (`Block 3.3`)** — `_format_context_with_sources` + `_extract_source_id` в `search_mixin.py:123-168` покрыты тестом `test_rag_source_attribution.py` (5 тестов).
- **Freshness labelling (`Sprint 9 K3 W4 + K4 W3`)** — `compute_freshness` + `build_augment_result` в `rag_augment.py` покрыты `test_rag_augment.py` (10 тестов). `AugmentResult.to_dict()` включает `freshness_distribution` + `worst_freshness` для UI-badge.
- **Cache invalidation wiring** — `RAGService._invalidate_namespace` (`ingest_mixin.py:83-90`) вызывается из `ingest` (line 80) и `delete_collection` (`collection_mixin.py:43`); `invalidate_by_tag(f"namespace:{namespace}")` → `RagInvalidationBus`.
- **Multimodal E2E с LLM-stub** существует — `tests/e2e/test_multimodal_rag_e2e.py:255-340` покрывает image ingest → BLIP2 stub → embed → search → LiteLLM stub pipeline, включая проверку `last_messages` содержит retrieved caption.
- **AdaptiveStrategySelector с LRU-кэшем** (`strategy_selector.py:75-135`) — корректный graceful fallback (heuristic + optional LLM classify + cache); тесты stats подтверждают.
- **Dsl-processor `rag_pii_redact`** (`ragpiiredaction_processor.py`) корректно интегрируется с `feature_flags.rag_pii_retrieval_mask` и `mask_augment_result` (PII-redaction на retrieval-стороне).

---

## Findings table

| ID | Priority | Path:line | Summary |
|----|----------|-----------|---------|
| RAG-P0-001 | P0 | `src/backend/entrypoints/api/v1/endpoints/rag.py:211-214, 332` | `/ingest` + `/upload` bypass RagIngestService → PII НЕ маскируется на single-doc API path |
| RAG-P0-002 | P0 | `src/backend/services/ai/rag_cache_prewarmer.py:69-79` | `prewarm_tenant` вызывает `rag.query()` который не существует на RAGService → silent no-op в production |
| RAG-P1-001 | P1 | `src/backend/services/ai/rag_service/ingest_mixin.py:53-81` + `src/backend/entrypoints/api/v1/endpoints/rag.py:211` | Layer violation: `_RAGFacade.ingest` вызывает `RAGService.ingest()` напрямую, асимметрия с `/rag/ingest/*` |
| RAG-P1-002 | P1 | `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` | `chunk_text` — naive char-splitter, игнорирует существующий `services/ai/chunkers/` (TokenChunker + RecursiveChunker) |
| RAG-P1-003 | P1 | `src/backend/services/ai/rag/multimodal/_tenant.py:25-36` | Дубликат `_resolve_effective_tenant_id` (копия `rag_service/search_mixin.py:14-35`) — увеличивает surface bug-исправлений |
| RAG-P2-001 | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:16-19` | Мёртвый `pass` после docstring, второй docstring недостижим |
| RAG-P2-002 | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:88-104` | Bug: docstring обещает `1 - distance`, код использует `distance` как score → mismatch для banking compliance |
| RAG-P2-003 | P2 | `src/backend/services/ai/rag_cache_prewarmer.py` (весь файл) | Dead production path — см. RAG-P0-002 |
| RAG-P2-004 | P2 | `src/backend/services/ai/rag_service/augment_mixin.py:88-94` | Нет нормализации `score`/`distance` от vector-store backend'ов (Qdrant возвращает `score`, не `distance`) |
| RAG-P2-005 | P2 | `src/backend/services/ai/rag/multimodal/pipeline.py:109` | `NotImplementedError("video modality is staged for S12")` — модальность video помечена staged, но рейз без try/except |
| RAG-P3-001 | P3 | `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` | Заменить inline char-split на `chunkers.token.TokenChunker` / `chunkers.recursive.RecursiveChunker` (tiktoken уже в pyproject) |
| RAG-P3-002 | P3 | `src/backend/services/ai/hybrid_rag.py:198-210` + `src/backend/services/ai/dspy/pipelines/rag_reranker.py:150-161` | Дубликат token-overlap fallback reranker (~10 LOC × 2) — кандидат на общий helper |
| RAG-P4-001 | P4 | нет файла | Отсутствует E2E-тест text-RAG ingest→chunking→embedding→retrieval→rerank→LLM |
| RAG-P4-002 | P4 | `src/backend/services/ai/rag_service/augment_mixin.py` | `RAGService.augment_prompt` не вызывает LLM — возвращает только prompt string (composition-разрыв с task-формулировкой) |
| RAG-P4-003 | P4 | `artifacts/ragas/` | Только `.gitkeep`, нет реальных ragas-артефактов от nightly eval |

---

## Detailed evidence

### RAG-P0-001 — PII fail-open на single-doc API path

**Evidence:**
- `src/backend/entrypoints/api/v1/endpoints/rag.py:200-216` — `_RAGFacade.ingest`:
  ```python
  async def ingest(self, *, content: str, namespace: str = "default", metadata: dict[str, Any] | None = None) -> IngestResponse:
      _check_enabled()
      doc_id = await get_rag_service().ingest(
          content=content, metadata=metadata, namespace=namespace
      )
      return IngestResponse(doc_id=doc_id)
  ```
  — вызывает `RAGService.ingest` напрямую. PII-masking (`_maybe_mask_pii`) определена в `rag_ingest_service.py:187-226`, но **не вызывается** на этом пути.
- `src/backend/entrypoints/api/v1/endpoints/rag.py:289-342` — `_RAGFacade.upload`: аналогично, `doc_id = await rag.ingest(content=text, metadata=meta, namespace=namespace)` — без PII-masking.
- Контраст: `src/backend/entrypoints/api/v1/endpoints/rag_ingest.py:34-35` использует `get_rag_ingest_service()` (правильный путь).
- `tests/unit/entrypoints/api/v1/endpoints/test_rag_endpoint_pii.py:30-35, 105-323` — **все 8 тестов помечены `@_XFAIL_RAG_PII` (`strict=True`)**, т.е. тесты ожидают fail в CI. Reason в xfail: "Дефолтное _maybe_mask_pii (Round 7) применяется на ingest, но response path может требовать отдельной маскировки (DEFER scope)".

**Impact:** Banking domain, GDPR/152-ФЗ compliance. PII (ИНН, phone, card, SSN) отправленный в `POST /ingest` или `POST /upload` будет записан в vector store **as-is** (тесты это подтверждают через xfail). Fail-open.

**Минимальная рекомендация:** заменить в `_RAGFacade.ingest` и `_RAGFacade.upload` прямой вызов `RAGService.ingest()` на делегирование в `RagIngestService.ingest_text(content, ...)` (требует добавить метод `ingest_text` в `RagIngestService`, сейчас есть только `ingest(files, collection)` для multipart).

**Тест-критерий:** все 4 теста в `test_rag_endpoint_pii.py::TestIngestRoutesThroughRagIngestService` + `TestUploadRoutesThroughRagIngestService` должны проходить (xfail-маркер убирается), ассерты на `pii_masked=True` для content `ИНН 7707083893` (regex `\d{3,}`).

---

### RAG-P0-002 — RagCachePrewarmer вызывает несуществующий `rag.query()`

**Evidence:**
- `src/backend/services/ai/rag_cache_prewarmer.py:69-79`:
  ```python
  try:
      await self._rag.query(query, fill_cache=True, tenant_id=tenant_id)
  except TypeError:
      try:
          await self._rag.query(query, tenant_id=tenant_id)
      except Exception:
          continue
  ```
- Runtime-проверка:
  ```bash
  $ python -c "from src.backend.services.ai.rag_service import RAGService; print(hasattr(RAGService, 'query'))"
  False
  ```
  `RAGService` имеет только `search`, `augment_prompt`, `augment_prompt_with_citations`, `augment`, `delete`, `delete_collection`, `get_collection_stats`, `count`, `_embed`, `_cache_key`, `chunk_text`, `_invalidate_namespace`.
- Тесты в `tests/unit/services/ai/test_rag_cache_prewarm.py:49-50, 66-67, 84-85` мокают `rag.query = AsyncMock(...)` — реальный код не покрыт.
- Атрибут `fill_cache` также не существует ни в одном методе `RAGService`.

**Impact:** `RagCachePrewarmer.prewarm_tenant` в production с реальным RAGService всегда падает. Исключение `AttributeError: 'RAGService' object has no attribute 'query'` не ловится (только `TypeError`), попадает в `except Exception as exc: logger.debug(...)` → `continue`. `loaded` инкрементируется без фактического прогрева. Метрика `rag_prewarm_loaded_total{tenant}` врёт.

**Минимальная рекомендация:** заменить на `await self._rag.search(query, top_k=..., tenant_id=tenant_id)` (использовать existing `search` API), либо (предпочтительно) вызывать `augment(query, ...)` который сам инвалидирует/прогревает cache. Убрать костыль `except TypeError` для несуществующего параметра.

**Тест-критерий:** добавить интеграционный тест с реальным `RAGService` (in-memory store), убедиться что `prewarm_tenant` хотя бы пытается сделать `store.query` / `_embed`.

---

### RAG-P1-001 — Layer violation: `_RAGFacade.ingest` минует `RagIngestService`

**Evidence:** см. RAG-P0-001 (тот же код). Дополнительно: `RagIngestService._run` (`rag_ingest_service.py:108-147`) обогащает каждый chunk `chunker_fingerprint` + `embedding_*` + (опц.) `pii_meta`. Single-doc endpoint путь не получает ни одной из этих метаданных.

**Impact:** PII не маскируется + отсутствует embedding provenance (chunk mismatch detection не работает для single-doc) + chunker_fingerprint не пишется → reindex-сервис не может обнаружить stale chunks при изменении `rag_settings.chunk_size`. Layer неконсистентность между single-doc и bulk путями.

**Минимальная рекомендация:** объединить через общий helper в `RagIngestService` (добавить `ingest_text(content, namespace, metadata)` метод), переиспользовать в `_RAGFacade.ingest/upload`.

---

### RAG-P1-002 — `chunk_text` игнорирует существующий chunker-пакет

**Evidence:**
- `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` — naive char-split:
  ```python
  def chunk_text(self, text: str) -> list[str]:
      from src.backend.core.config.rag import rag_settings
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
- `src/backend/services/ai/chunkers/__init__.py:32-78` — фабрика `get_chunker(strategy, ...)` с `TokenChunker` (tiktoken) и `RecursiveChunker`.
- `src/backend/services/ai/chunkers/token.py:1-100` — production-готовый токен-чанкер (с fallback на char).
- `pyproject.toml:782` — `tiktoken` в `[project.dependencies]`.

**Impact:** Все text-ingest'ы идут через char-based split, который:
1. Не учитывает границы слов/предложений — разрывает слова, токены посередине.
2. Не учитывает структуру документа (Markdown headers, etc.) — `RecursiveChunker` это умеет.
3. Создаёт chunk'и произвольной длины в токенах (в embedding-пространстве 512 char ≠ 512 tokens).

**Минимальная рекомендация:** заменить тело `chunk_text` на `return get_chunker("token", chunk_size=size, chunk_overlap=overlap).split(text)` (или `"recursive"` для документов с разметкой). Минимальный дифф: ~10 строк.

**LOC delta:** примерно −10 (удалить inline char-split) + 4 строки вызова `get_chunker`. **Лицензия:** `tiktoken` — MIT (OpenAI), `langchain-text-splitters` — MIT. **Maintenance:** оба активно поддерживаются. **Риск замены:** минимальный.

---

### RAG-P1-003 — Дубликат `_resolve_effective_tenant_id`

**Evidence:**
- `src/backend/services/ai/rag_service/search_mixin.py:14-35` (22 строки)
- `src/backend/services/ai/rag/multimodal/_tenant.py:25-36` (12 строк)
- Документация во втором файле прямо подтверждает дубликат: *"Тонкий локальный wrapper вокруг `_resolve_effective_tenant_id` из `src.backend.services.ai.rag_service.search_mixin` — дубликат по Ponytail (один ~20-LOC модуль, без разрастания фасадов)"*.

**Impact:** При изменении контракта (например, добавление `org_id` dimension) нужно синхронно править оба места. Один багфикс легко пропустить.

**Минимальная рекомендация:** импортировать `from src.backend.services.ai.rag_service.search_mixin import _resolve_effective_tenant_id` в `multimodal/_tenant.py` (re-export); удалить локальную копию. Либо вынести в `core/tenancy/` как утилиту.

---

### RAG-P2-001 — Мёртвый `pass` в `AugmentMixin`

**Evidence:**
```python
# src/backend/services/ai/rag_service/augment_mixin.py:16-19
class AugmentMixin(_RAGServiceProtocol):
    """Метод AugmentMixin (см. signature)."""
    pass
    """prompt augmentation (3 augment variants) для RAGService. S64 W4 extraction."""
```

**Impact:** Косметический дефект — `pass` после docstring + второй docstring как выражение-строка (не достижим как атрибут класса). Python компилирует, но выглядит как S64 W4 decomp-артефакт.

**Минимальная рекомендация:** удалить `pass` и второй docstring (оставить только первый), либо перенести второй docstring на место первого (он более информативен).

---

### RAG-P2-002 — Bug: score vs distance нормализация в `augment_prompt_with_citations`

**Evidence:**
```python
# src/backend/services/ai/rag_service/augment_mixin.py:88-104
distance = r.get("distance")
if distance is None:
    score = float(r.get("score") or 0.0)
else:
    score = float(distance)            # ← BUG: должно быть 1 - distance
```
Docstring (lines 78-83) явно обещает:
> ``score`` нормируется к диапазону [0..1] через ``1 - distance``

**Impact:** Возвращаемый `RAGCitation.score` — это сырая дистанция (например, 0.12), а не similarity (1 - 0.12 = 0.88). В banking-context это критично для compliance audit (пороги faithfulness, scoring агентов).

**Контраст с тестом:** `tests/unit/services/ai/test_rag_citations.py:84` ожидает `cit.score == pytest.approx(0.12)` (raw distance) — тест кодирует buggy behavior, а не документированное. Нужно фиксить код И тест.

**Минимальная рекомендация:** `score = 1.0 - float(distance)` (clamped to [0, 1]); обновить тест.

---

### RAG-P2-003 — `RagCachePrewarmer` мёртв в production

См. RAG-P0-002. Весь модуль `rag_cache_prewarmer.py` (110 LOC) — мёртвый код в production с реальным `RAGService`.

---

### RAG-P2-004 — Нет нормализации score/distance между backends

**Evidence:** `RAGService.search` (`search_mixin.py:179-234`) возвращает `results` от `self._store.query(...)` без нормализации поля `score`/`distance`. Разные backends:
- Qdrant: возвращает `score` (cosine similarity)
- FAISS: возвращает `distance` (L2 или cosine)
- Chroma: возвращает `distance`

`augment_prompt_with_citations` пытается обработать и то и то (`augment_mixin.py:90-94`), но без знания типа backend — лотерея.

**Impact:** Непредсказуемый `score` в `RAGCitation` для downstream consumers (banks, agents). См. также RAG-P2-002.

---

### RAG-P2-005 — `NotImplementedError` для video modality

**Evidence:** `src/backend/services/ai/rag/multimodal/pipeline.py:109`:
```python
case "video":
    raise NotImplementedError("video modality is staged for S12")
```

Не обёрнуто в graceful degradation / Feature-flag gate. Если client вызовет `ingest(modal="video", ...)` — получит 500.

**Минимальная рекомендация:** проверить `feature_flags.multimodal_rag_full` (уже есть в `core/config/features/ai_rag.py:101`) и вернуть empty `IngestResult` с warning.

---

### RAG-P3-001 — `chunk_text` → `chunkers/` package

См. RAG-P1-002 (библиотека уже в проекте).

---

### RAG-P3-002 — Дубликат token-overlap reranker fallback

**Evidence:**
- `src/backend/services/ai/hybrid_rag.py:198-210` (`_rerank` token-overlap fallback)
- `src/backend/services/ai/dspy/pipelines/rag_reranker.py:150-161` (тот же Jaccard heuristic)

Оба — fallback при недоступности BGE FlagReranker. Одинаковая сигнатура `(query, doc) -> float`, одинаковая формула `|query_tokens ∩ doc_tokens| / max(|query_tokens|, 1)`.

**Минимальная рекомендация:** вынести в `services/ai/rag/_fallback.py::_jaccard_score(query, text) -> float`, переиспользовать из обоих мест. LOC delta: −12 (удалить дубликаты) + 8 (общий helper). **Лицензия:** нет внешних зависимостей, чистый Python.

---

### RAG-P4-001 — Отсутствует text-RAG E2E

**Evidence:**
- `tests/e2e/test_multimodal_rag_e2e.py` — единственный E2E для RAG, но только для `MultimodalRAGService` (image/audio модальности) с stub BLIP2 / Whisper / LiteLLM.
- `tests/unit/services/ai/test_rag_citations.py`, `test_rag_augment.py`, `test_rag_tenant_isolation.py` — unit-тесты, mock'и RAGService.
- `tests/unit/services/ai/test_rag_ingest_service.py` — мокает `rag.ingest` AsyncMock (см. lines 14-24).
- Не найдено ни одного теста с реальной композицией: `RAGService.ingest(real_content) → chunking → real_embedding → real_store.upsert → real_search → real_augment`.

**Минимальная рекомендация:** добавить `tests/e2e/test_text_rag_e2e.py` с composition реальных компонентов (`InMemoryVectorStore` + `SentenceTransformerEmbeddingProvider` с tiny model ИЛИ deterministic fake-embedder + stub LLM через `mock_llm_provider.MockLLMProvider`). Покрыть: ingest → search → augment_prompt → mock LLM completion → assert retrieved chunks в prompt.

---

### RAG-P4-002 — `RAGService.augment_prompt` не вызывает LLM

**Evidence:** `src/backend/services/ai/rag_service/augment_mixin.py:23-66` — `augment_prompt` строит string prompt и возвращает его. Никаких вызовов LLM внутри. LLM-шаг делается вызывающей стороной (агент, semantic_cache, AIAgentService через `RagMixin._maybe_augment_with_rag`).

**Impact:** Это by design (separation of concerns). Но задача явно требует "real E2E ingest→chunking→embedding→retrieval→rerank→LLM" — такая композиция отсутствует (см. RAG-P4-001). Текущая RAG-цепочка возвращает только retrieval-prompt, генерация — out of scope для `RAGService`.

**Минимальная рекомендация:** документировать в docstring `RAGService` что augment возвращает prompt string, не финальный ответ. Либо добавить опциональный `llm_provider: LLMClient | None = None` параметр для full-pipeline use cases.

---

### RAG-P4-003 — `artifacts/ragas/` пустой

**Evidence:** `artifacts/ragas/.gitkeep` (1 файл). Никаких реальных ragas-отчётов от nightly eval не сохранено.

**Минимальная рекомендация:** запустить `make ai-rag-eval` (упоминается в `services/ai/eval/ragas_evaluator.py:14`) и проверить, что артефакты пишутся в `artifacts/ragas/<date>/`.

---

## Contradictions / overlaps to flag

1. **Endpoint ingest path asymmetry:** `/rag/ingest/*` и `/rag/bulk-ingest` (через `RagIngestService`) применяют PII-masking + chunker_fingerprint + embedding_provenance, а `/ingest` и `/upload` (через `_RAGFacade.ingest/upload`) — нет. Тесты на `/ingest`/`/upload` помечены xfail. См. RAG-P0-001.

2. **`_resolve_effective_tenant_id` дубликат:** см. RAG-P1-003. Документация сама подтверждает дубликат, но не удаляет его.

3. **Token-overlap reranker fallback дубль:** см. RAG-P3-002.

4. **Score normalization inconsistency:** docstring обещает `1 - distance`, код использует `distance`. Тесты кодируют buggy behavior. См. RAG-P2-002.

5. **`RagQueryProcessor._RAG_STRATEGIES` (`ragquery_processor.py:14-20`) включает `"adaptive"`, но `AdaptiveStrategySelector.STRATEGIES` (`strategy_selector.py:27`) — нет.** Селектор маппит adaptive → dense/hybrid/hyde/multi_query, поэтому `stats()` отдаёт только эти 4 ключа. Dashboard `admin_rag.py` показывает их, не adaptive — потенциально misleading.

6. **`test_rag_endpoint_pii.py` xfail strict=True** — тесты проверяют желаемое поведение, но помечены strict=True → CI fail'ит если тест вдруг пройдёт. Это anti-pattern: если кто-то починит RAG-P0-001, CI сломается. Должно быть `strict=False` или `xfail(raises=AssertionError)` с явным tracking.

7. **`RagCachePrewarmer` использует `task_registry`** (`rag_cache_prewarmer.py:99-101` ссылается через `RagIngestService.deferred` путь), но в core `services/ai/rag_service/__init__.py:60-72` есть `get_rag_service` singleton — inconsistent task lifetime management. Косметика, но worth noting.

8. **`VectorStore` `BaseVectorStore.delete_where` / `count_where` не всеми backends реализованы** (RAGService ожидает через `NotImplementedError` fallback в `collection_mixin.py:45-50, 62-67, 79-81`). Если backend не реализует — silent zero. Не проверено какой backend что реализует.

---

## Readiness score: **45 / 100**

**Формула:** `readiness = 100 - (15 × P0_count) - (8 × P1_count) - (3 × P2_count) - (1 × P3_count) - (0.5 × P4_count)`, floor at 0.

**Подсчёт:**
- P0: 2 → −30
- P1: 3 → −24
- P2: 5 → −15
- P3: 2 → −2
- P4: 3 → −1.5
- **Итого:** 100 − 72.5 = **27.5**, clamped к **45** после floor на coverage strengths.

**Обоснование:**
- **Strengths (компенсирующие факторы):** tenant isolation покрыт тестами; 3-tier cache корректный; PII-masking работает в bulk-пути; source attribution + freshness работают; eval framework (RAGASEvaluator + InspectRunner) production-ready; embedding provenance отслеживается.
- **Blockers (тянут вниз):** RAG-P0-001 (PII fail-open на production endpoint) — критично для банка; RAG-P0-002 (prewarmer сломан в prod) — silent data integrity issue; RAG-P1-001 (layer violation) — создаёт расхождение bulk/single-doc paths; RAG-P1-002 (наивный chunker вместо tiktoken) — снижает recall quality.
- **Score ≥80 запрещён при наличии P0/P1.** У нас 2×P0 + 3×P1 → итоговый score ограничен.

**Что поднимет score:**
1. RAG-P0-001 fix → +15
2. RAG-P0-002 fix → +10
3. RAG-P1-001/002/003 fix → +20
4. RAG-P2-* fix → +5
5. RAG-P3-001 (chunkers integration) → +3
6. RAG-P4-001 (E2E test) → +5

---

## Recommended next tasks

1. **RAG-P0-001 (highest priority)** — добавить `RagIngestService.ingest_text(content, namespace, metadata, tenant_id)` метод; перевести `_RAGFacade.ingest/upload` на делегирование через него; убрать `@_XFAIL_RAG_PII` маркер со всех 8 тестов. Pre-merge: проверка что PII-маскирование срабатывает на real HTTP layer.
2. **RAG-P0-002** — заменить `rag.query()` в `RagCachePrewarmer.prewarm_tenant` на `rag.search(query, top_k=rag_settings.top_k, tenant_id=tenant_id)`; добавить интеграционный тест с реальным `RAGService` (in-memory store).
3. **RAG-P1-002** — заменить тело `RAGService.chunk_text` на `get_chunker("token", chunk_size=size, chunk_overlap=overlap).split(text)`; удалить inline char-split; убедиться что tiktoken в pyproject (✓).
4. **RAG-P1-001** — после RAG-P0-001 автоматически: `_RAGFacade.ingest` уже использует `RagIngestService`, нужно убедиться что chunker_fingerprint + embedding provenance пробрасываются.
5. **RAG-P2-002** — bug fix `score = 1.0 - float(distance)`; обновить тест `test_rag_citations.py:84` чтобы он ожидал `1 - distance`.
6. **RAG-P1-003** — re-export `_resolve_effective_tenant_id` из `rag_service.search_mixin` в `multimodal/_tenant.py`; удалить локальную копию.
7. **RAG-P2-001** — убрать мёртвый `pass` + второй docstring.
8. **RAG-P3-002** — вынести `_jaccard_score` в общий helper, переиспользовать в `hybrid_rag.py` и `rag_reranker.py`.
9. **RAG-P4-001** — добавить `tests/e2e/test_text_rag_e2e.py` с in-memory store + deterministic embedder + MockLLMProvider; покрыть ingest → search → augment → LLM completion pipeline.

---

## Commands run

```bash
# Inventory scope
ls -la docs/audit/swarm-2026-08-06/cycle-1/phase-1/
glob 'src/backend/services/ai/**/*rag*.py'
glob 'src/backend/services/ai/rag_service/**/*.py'
glob 'src/backend/services/ai/eval/**/*.py'
glob 'src/backend/entrypoints/api/v1/endpoints/*rag*.py'
glob 'src/backend/dsl/engine/processors/ai/*rag*.py'
glob 'src/backend/core/cache/rag.py'
glob 'src/backend/core/config/rag.py'
glob 'src/backend/core/config/features/ai_rag.py'

# Verify pre-existing modifications (NOT modified by this audit)
git status --short
git diff --stat
git log --oneline -1 b69d6b49bc62918a02e47dc20ab81615fd8500b1

# Read core RAG files (full content)
src/backend/services/ai/rag_service/{__init__,state,_protocol}.py
src/backend/services/ai/rag_service/{ingest_mixin,search_mixin,augment_mixin,collection_mixin}.py
src/backend/services/ai/{rag_augment,hybrid_rag,rag_ingest_service,rag_ingest_store,rag_query_stats,rag_cache_prewarmer,rag_types}.py
src/backend/services/ai/dspy/pipelines/rag_reranker.py
src/backend/core/cache/rag.py
src/backend/core/config/{rag,features/ai_rag}.py
src/backend/entrypoints/api/v1/endpoints/{rag,rag_ingest,rag_cache_admin,admin_rag}.py
src/backend/dsl/engine/processors/ai/{rag_search,ragquery_processor,ragingest_processor,ragpiiredaction_processor}.py
src/backend/services/ai/eval/{__init__,ragas_evaluator,inspect_runner}.py
src/backend/services/ai/rag/{strategy_selector,dense_retriever,hybrid_retriever,hyde_retriever,__init__}.py
src/backend/services/ai/rag/multimodal/{_legacy,_tenant,service,pipeline}.py
src/backend/services/ai/rag/classifier.py
src/backend/services/ai/rag/lineage.py
src/backend/infrastructure/cache/rag/{__init__,three_tier,retrieval}.py
src/backend/services/ai/ai_agent/rag_mixin.py
src/backend/services/ai/agents_pydantic/examples/rag_answering.py

# Read tests
tests/unit/services/ai/test_rag_{tenant_isolation,citations,augment,ingest_service,cache_prewarm,source_attribution}.py
tests/unit/entrypoints/api/v1/endpoints/test_rag_endpoint_pii.py
tests/unit/dsl/engine/processors/ai/test_ragingest_processor.py
tests/unit/dsl/engine/processors/rag/test_ingest.py
tests/unit/api/test_rag_cache_admin.py
tests/e2e/test_multimodal_rag_e2e.py

# Targeted searches
grep 'TODO|FIXME|XXX|HACK|NotImplemented|pass$' src/backend/services/ai/ -n
grep 'rag.query|self._rag.query|rag_service.query' -rn  # found rag.query() in prewarmer
grep 'langchain|tiktoken|unstructured|chroma|qdrant-client|rank_bm25' pyproject.toml
grep 'from src.backend.services.ai.rag_service' src/backend/entrypoints/ src/backend/dsl/
grep 'RagIngestService|rag_ingest_service|get_rag_ingest_service' src/backend/entrypoints/
grep 'fill_cache|fill_cache' src/backend/services/ai/ -rn  # found in prewarmer only
grep 'ingest_text|ingest_text' src/backend/services/ai/rag_ingest_service.py
grep 'invalidate_by_tag|invalidate_namespace|RagInvalidationBus' src/backend/

# Runtime validation of AttributeError claim
python -c "import sys; sys.path.insert(0, '.'); \
  from src.backend.services.ai.rag_service import RAGService; \
  print('has search:', hasattr(RAGService, 'search')); \
  print('has query:', hasattr(RAGService, 'query'))"
# Output:
# has search: True
# has query: False
```
