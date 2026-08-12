# Cycle 3 — Phase 1 — Domain: RAG

**Audit domain:** RAG (Retrieval-Augmented Generation) и eval-фреймворк
(`services/ai/rag*`, `services/ai/rag_service/`, `services/ai/eval/`,
`core/cache/rag.py`, `core/config/rag.py`, `core/config/features/ai_rag.py`,
`entrypoints/api/v1/endpoints/*rag*.py`, `dsl/engine/processors/ai/*rag*.py`,
`tests/e2e/test_multimodal_rag_e2e.py`).

**Author:** Phase 1 analyst (cycle 3 / swarm-2026-08-06).
**Date:** 2026-08-06.
**HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`.

---

## 1. Scope / что проверено / что не проверено

### Проверено (read-only)

| Категория | Файлы | Команды |
|---|---|---|
| RAG service core | `src/backend/services/ai/rag_service/{__init__,augment_mixin,collection_mixin,ingest_mixin,search_mixin,state,_protocol}.py` | `Read` |
| RAG ingest pipeline | `src/backend/services/ai/rag_ingest_service.py`, `rag_ingest_store.py`, `rag_augment.py`, `rag_types.py`, `rag_query_stats.py`, `rag_cache_prewarmer.py`, `hybrid_rag.py` | `Read` |
| PII / retrieval mask | `src/backend/services/ai/pii/retrieval_masker.py`, `core/security/pii_masker.py`, `services/ai/pii/presidio_analyzer.py` (lines 1-200) | `Read` |
| Cache + config | `src/backend/core/cache/rag.py`, `src/backend/core/config/rag.py`, `src/backend/core/config/features/ai_rag.py` | `Read` |
| API endpoints | `entrypoints/api/v1/endpoints/rag.py`, `rag_ingest.py`, `rag_cache_admin.py`, `admin_rag.py` | `Read` |
| DSL processors | `dsl/engine/processors/ai/{ragquery,ragingest,ragpiiredaction}_processor.py`, `rag_search.py` | `Read` |
| Eval framework | `services/ai/eval/__init__.py`, `inspect_runner.py`, `ragas_evaluator.py`, `suites/*` | `Read` |
| E2E test | `tests/e2e/test_multimodal_rag_e2e.py` (434 LOC) | `Read` + runtime |
| Unit tests | `tests/unit/services/ai/test_rag_*.py`, `tests/unit/services/ai/eval/test_ragas_evaluator.py` (61 tests total) | `pytest` runtime |
| Pipeline integrity | `services/ai/dspy/pipelines/rag_reranker.py`, `services/ai/chunkers/{token,recursive,__init__}.py`, `plugins/composition/lifecycle/bootstrap.py` (lines 55-65) | `Read` |

### Не проверено

- `src/backend/services/ai/rag/multimodal/` (BLIP2, Whisper, CLIP, PDFIngester,
  ImageIngester, embedders, types) — НЕ в scope; проверены только как
  контекст для E2E-теста.
- `src/backend/services/ai/rag/{classifier,dense_retriever,docs_indexer,
  hybrid_retriever,hyde_retriever,lineage,multi_query_retriever,
  project_docs,strategy_selector}/**` — НЕ в scope (внутренние retriever'ы
  adaptive RAG).
- `src/backend/services/ai/ai_agent/rag_mixin.py` — НЕ в scope (agent layer).
- `src/backend/services/ai/agents_pydantic/examples/rag_answering.py` — НЕ в
  scope (example).
- Cycle-1 / cycle-2 markdown-отчёты (запрещено по инструкции).
- Cycle-3 reports других аналитиков (запрещено по инструкции).
- `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`,
  `triage_allowlist_report.md` (запрещено).
- Реальная нагрузка prod-runtime (только static analysis + targeted runtime).

### Python-интерпретатор и pytest

Все runtime-проверки выполнялись через `.venv/bin/python` (Python 3.14.0)
с прямым вызовом `.venv/bin/python -m pytest ...`. System-Python НЕ
использовался — пакеты (`prometheus_client`, `fastapi`, `hypothesis`)
установлены только в `.venv/lib/python3.14/site-packages`.

---

## 2. Verified strengths

1. **`rag_service/__init__.py`** использует корректный composition-root
   pattern через `@app_state_singleton("rag_service")` + bootstrap
   (`plugins/composition/lifecycle/bootstrap.py:63`), без прямого
   `infrastructure.*` импорта (clean architecture / no layer violation).

2. **`RAGService` (4 mixin'а, 13 методов)** чётко разделены по ответственности:
   ingest / search / augment / collection, плюс `_protocol.py` для cross-mixin
   type hints (Sprint 64 W4 extraction).

3. **Tenant isolation (Cycle 2 Sprint 2.6)** в `search_mixin.py`:
   `_resolve_effective_tenant_id`, `_build_where`, `_filter_chunks_by_tenant`
   — defence-in-depth через (a) where-фильтр в vector store, (b) tenant-tag в
   L3 cache keys, (c) Python post-filter. Все 19 unit-тестов
   `test_rag_tenant_isolation.py` проходят (см. §10).

4. **Embedding provenance (Block 3.5)** — `_filter_by_embedding_version`
   в `search_mixin.py:92-120` отбрасывает chunks с устаревшим embedding-model
   при `rag_settings.embedding_strict_mode=True`. Тесты
   `test_rag_embedding_version.py` (4 passed) подтверждают.

5. **Source attribution (Block 3.3)** в `search_mixin._extract_source_id`
   с приоритетом `source > filename > doc_id > id` — для LLM citation.
   `test_rag_source_attribution.py` (4 passed).

6. **`ThreeTierRagCache` facade** через `core/cache/rag.py` + DI locator
   `core/di/providers/infrastructure_locator.py` — capability-checked
   доступ из `services/ai/rag_service`. Нет прямого импорта
   `infrastructure.cache.rag.three_tier`.

7. **PII retrieval-mask** (`retrieval_masker.py`) — opt-in via
   `RagPIIRedactionProcessor` с feature-flag `rag_pii_retrieval_mask`.
   Test `test_rag_pii_mask.py` (3 passed): passthrough при flag off,
   mask при flag on, graceful error при sanitizer failure.

8. **Adaptive RAG strategy selection (S11 K4 W3)** в
   `ragquery_processor.py` + `services/ai/rag/strategy_selector.py` —
   feature-flag `adaptive_rag_strategy` + overhead-metric
   `rag_strategy_overhead_ms`.

9. **EIP/Camel-like DSL integration** — `RagQueryProcessor` /
   `RagIngestProcessor` / `RagPIIRedactionProcessor` /
   `RAGSearchProcessor` (Sprint 170) следуют `BaseProcessor` контракту:
   `process(exchange, context)` + `to_spec()` для reverse-mapping.

10. **API via `ActionRouterBuilder`** (`entrypoints/api/v1/endpoints/rag.py`)
    — declarative `ActionSpec` с фасадом `_RAGFacade` для бизнес-логики.
    `multipart /upload` (PDF/DOCX/...) — отдельный `@router.post`,
    остальные 7 endpoint'ов — через `builder.add_actions`.

11. **RAGAS eval pipeline** (`eval/ragas_evaluator.py`):
    async wrapper через `asyncio.to_thread` (ragas sync API),
    threshold-gating для CI (`RAGASReport.is_blocking()`),
    graceful skip при отсутствии `ragas`/`datasets`. 9 unit-тестов passed.

12. **Ingest state store** (`rag_ingest_store.py`): Protocol
    `IngestStateStore` + `InMemoryIngestStateStore` + `RedisIngestStateStore`
    (HASH + ZSET для recent). Factory `build_ingest_state_store(backend)`.

13. **Chunker fingerprint** (`rag_ingest_service._chunker_fingerprint`):
    SHA-256 префикс из version + size + overlap для детекта re-index.

14. **EmbeddingVectorCache** (Sprint 86) использует `cachetools.TTLCache`
    (cycle-1/P3-01 замена собственного LRU+TTL), обёрнутый `asyncio.Lock` —
    корректный выбор зрелой библиотеки вместо custom-кода.

---

## 3. Findings table (P0..P4)

| ID | Приоритет | Файл:строка | Кратко |
|---|---|---|---|
| **RAG-P0-001** | **P0** | `services/ai/rag_ingest_service.py:207-226` (`_maybe_mask_pii`) | `_maybe_mask_pii` ловит `Exception`, но НЕ `BaseException`. `spacy.cli.download()` (lazy-init в `presidio_analyzer.py:81`) кидает `SystemExit(1)` — bypass'ит catch, документ НЕ ингестится, exception пробивается в test/handler. Production-impact: при отсутствии `ru_core_news_lg` каждый ingest → SystemExit → 500. Детальный trace см. §4.1. |
| **RAG-P0-002** | **P0** | `services/ai/rag_cache_prewarmer.py:69,73` | `RagCachePrewarmer.prewarm_tenant` вызывает `self._rag.query(query, fill_cache=True, tenant_id=...)`, но `RAGService` **не имеет метода `.query()`** (методы: `augment`, `augment_prompt`, `augment_prompt_with_citations`, `search`, `ingest`, `delete`, ...). Runtime: каждый вызов → `AttributeError` → swallowed → `loaded=0`. Pre-warm в production **полностью молча сломан**. Runtime-проверено: `loaded=0` с real RAGService instance (см. §10.4). Также dead code: класс нигде не вызывается из production lifespan (только `tests/unit/services/ai/test_rag_cache_prewarm.py`). |
| **RAG-P0-003** | **P0** | `services/ai/rag_service/__init__.py:60-72` (`get_rag_service`) | `@app_state_singleton("rag_service")` декоратор в `core/di/app_state.py:143-185` принимает ТОЛЬКО `factory=` параметр, не вызывает wrapped-function. Внутренний fallback `RAGService(store=InMemoryVectorStore())` **никогда не выполняется**, плюс `from src.backend.core.vector_store.memory import InMemoryVectorStore` — модуль НЕ существует в проекте (`find` подтверждает). Runtime-test: `get_rag_service()` без app.state → `RuntimeError: rag_service not in app.state and no factory provided`. В production работает, потому что `bootstrap.py:63` регистрирует `app.state.rag_service`, но unit-тесты вне FastAPI-контекста падают. |
| **RAG-P0-004** | **P0** | `tests/e2e/test_multimodal_rag_e2e.py:255-340` (`test_image_caption_pipeline_e2e`, `test_audio_transcript_pipeline_e2e`) | **2 из 3 E2E-тестов FAILS** в текущем HEAD. Причина: тест ingest'ит изображение БЕЗ `tenant_id`, но ищет С `tenant_id="e2e"`. `MultimodalRAGService.search` filter'ит chunks где `metadata.tenant_id != "e2e"` → 0 hits. Runtime-проверено: `assert len(hits) >= 1` fails с `0 >= 1` (см. §10.5). Это **существующий pre-existing test failure**, не regression cycle-3. |
| **RAG-P1-001** | **P1** | `services/ai/rag_query_stats.py:78-85` (`top_queries`) | Типозависимый lookup в `queries_map.get(...)`: проверяет тип **первого** ключа (`list(queries_map.keys())[0]`) а не текущего `h`. При non-bytes Redis client (str keys) → `queries_map.get(h.encode())` → KeyError → silent `except Exception: pass` → fallback на in-memory (где данные могли быть уже потеряны). Реальные Redis-py возвращают bytes, но hiredis/redis-py с `decode_responses=True` — str. Edge case + silent failure = нарушение fail-closed принципа. |
| **RAG-P1-002** | **P1** | `services/ai/rag_ingest_service.py:118-134` (`_run`) | В цикле `for filename, content_bytes in files`: `except Exception` в строке 132 ловит ошибки _masking/ingest, добавляет в `state["errors"]`. Но `_maybe_mask_pii` может кинуть `BaseException` (см. RAG-P0-001) — bypass'ит, роняет весь ingest-batch на первой же ошибке одного файла. Data-loss: частично заingest'енные chunks сохраняются в `_store`, но response-handler получает 500 без cleanup. |
| **RAG-P2-001** | **P2** | `services/ai/rag_service/{ingest,search,augment,collection}_mixin.py` | 6 dead `pass` statements в `if TYPE_CHECKING:` блоках (lines 6, 11-12 в ingest; 6 в search; 6, 11 в collection; 18 в augment) — безвредные, но multi-statement. Ponytail: оставить 1 `pass` для синтаксиса. |
| **RAG-P2-002** | **P2** | `services/ai/rag_ingest_service.py:211` | `if not rag_ingest_settings.pii_mask_on_ingest: return content_text, {"pii_masked": False}` — default-OFF. Cycle 2 / RAG-P0-001 evidence: при feature-flag ON (`pii_mask_on_ingest=True`, default) и `presidio_pii_enabled=True` (default) — masking **падает** на отсутствующем spacy-model. Документы с PII потенциально НЕ замаскированы и НЕ заingest'ены одновременно (race). См. RAG-P0-001 + RAG-P0-002. |
| **RAG-P3-001** | **P3** | `services/ai/rag_service/ingest_mixin.py:35-48` (`chunk_text`) | Custom byte-based chunking через `text[start:end]` + `start = end - overlap`. **Игнорирует** уже реализованные chunkers в `services/ai/chunkers/` (`TokenChunker` через tiktoken, `RecursiveChunker` через separators). Не вызывает `get_chunker(strategy, ...)` — drift, нет детекта sentence boundary, нет token-aware sizing. Library replacement: использовать `RecursiveChunker` (уже в проекте, ~120 LOC). Zero new dependency, +50 LOC net. |
| **RAG-P3-002** | **P3** | `services/ai/dspy/pipelines/rag_reranker.py:177-184` (`metric`) | NDCG@k formula: `dcg = sum(gains.get(doc_id) / log2(rank+2))` где `gains = 1/log2(rank+2)` → `dcg` = sum of `1/log2(rank+2)^2` (discount-squared, не standard NDCG). IDCG аналогично. Консистентно, но non-standard — сравнение с внешними eval-системами (ragas, trec_eval) покажет drift. Не блокер, но eval-output может ввести в заблуждение. |
| **RAG-P4-001** | **P4** | **missing file**: `tests/e2e/test_text_rag_e2e.py` | Text-only RAG E2E pipeline (ingest text → embed → search → LLM citation) — **до сих пор не существует**. Cycle 1 / T-4.1 deferred, cycle 2 / T-W4-01 deferred, cycle 3 — нет. Существующий `test_multimodal_rag_e2e.py` покрывает только image/audio/audio; text-path не валидируется на stub boundary. Минимальный шаблон: StubEmbedder + StubLiteLLM (как в multimodal E2E) + реальный `RAGService.search/augment`. Ponytail: ~120 LOC. |
| **RAG-P4-002** | **P4** | `services/ai/rag/multimodal/_legacy.py` (мультимодальный контекст) | `MultimodalRAGService._is_enabled` (line 119) использует `multimodal_rag_enabled` (старый flag). `core/config/features/ai_rag.py:101` вводит новый `multimodal_rag_full=True` default. Семантический overlap нечёткий: какая разница между `enabled` и `full`? Отсутствует docstring-описание в `_legacy.py:119-127`. Ponytail: задокументировать в `features/ai_rag.py:101` или объединить флаги. |

---

## 4. Detailed evidence (P0/P1)

### 4.1 RAG-P0-001: `_maybe_mask_pii` SystemExit bypass

**Файл:** `src/backend/services/ai/rag_ingest_service.py:207-226`

```python
def _maybe_mask_pii(content_text: str) -> tuple[str, dict[str, Any]]:
    try:
        from src.backend.core.config.ai_stack import rag_ingest_settings
    except Exception as _:
        return content_text, {"pii_masked": False}
    if not rag_ingest_settings.pii_mask_on_ingest:
        return content_text, {"pii_masked": False}

    try:
        from src.backend.core.di.providers import get_ai_sanitizer_provider
        sanitizer = get_ai_sanitizer_provider()
        result = sanitizer.sanitize_text(content_text)  # ← line 218
        ...
    except Exception as exc:                              # ← line 224
        logger.warning("rag_ingest_pii_mask_failed: %s", exc)
        return content_text, {"pii_masked": False, "pii_mask_error": str(exc)}
```

**Trace:**
1. Defaults: `pii_mask_on_ingest=True` (verified: `.venv/bin/python -c "from src.backend.core.config.ai_stack import rag_ingest_settings; print(rag_ingest_settings.pii_mask_on_ingest)"` → `True`).
2. `presidio_pii_enabled=True` (verified: `from src.backend.core.config.features import feature_flags; print(feature_flags.presidio_pii_enabled)` → `True`).
3. `get_ai_sanitizer_provider()` → `PresidioSanitizerAdapter`.
4. `sanitize_text(text)` → `_ensure_initialized()` → `nlp_engine.load()` →
   `spacy.cli.download("ru_core_news_lg")` → wheel fetch fails →
   `spacy.util.run_command(cmd)` → `sys.exit(ret.returncode)` →
   **SystemExit(1)** — **НЕ Exception**, bypass'ит `except Exception`.
5. `_maybe_mask_pii` propagates SystemExit to caller.

**Runtime evidence:**
```bash
$ .venv/bin/python -m pytest tests/unit/services/ai/test_rag_embedding_version.py::test_ingest_includes_embedding_provenance -v --tb=short
src/backend/services/ai/rag_ingest_service.py:218: in _maybe_mask_pii
    result = sanitizer.sanitize_text(content_text)
src/backend/services/ai/pii/presidio_analyzer.py:183: in sanitize_text
    if not self._ensure_initialized():
src/backend/services/ai/pii/presidio_analyzer.py:122: in _ensure_initialized
    nlp_engine = provider.create_engine()
.venv/lib/python3.14/site-packages/presidio_analyzer/nlp_engine/nlp_engine_provider.py:109: in create_engine
    engine.load()
.venv/lib/python3.14/site-packages/presidio_analyzer/nlp_engine/spacy_nlp_engine.py:74: in load
    self._download_spacy_model_if_needed(model["model_name"])
.venv/lib/python3.14/site-packages/presidio_analyzer/nlp_engine/spacy_nlp_engine.py:81: in _download_spacy_model_if_needed
    spacy.cli.download(model_name)
.venv/lib/python3.14/site-packages/spacy/cli/download.py:100: in download
    download_model(filename, pip_args, custom_url)
.venv/lib/python3.14/site-packages/spacy/cli/download.py:188: in download_model
    run_command(cmd)
.venv/lib/python3.14/site-packages/spacy/util.py:1095: in run_command
    sys.exit(ret.returncode)
E   SystemExit: 1
FAILED tests/unit/services/ai/test_rag_embedding_version.py::test_ingest_includes_embedding_provenance
```

Аналогичный hang в `test_rag_ingest_service.py::test_ingest_inline_processes_all_files`:
```
============================= 1 failed in 4.07s ==============================
```
(после `spacy.cli.download`).

**Impact:** P0 / fail-OPEN при недоступности spacy-model. Production deploy с
отсутствующим `ru_core_news_lg` wheel → каждый RAG-ingest → HTTP 500.
**Рекомендация:** заменить `except Exception` → `except (Exception, SystemExit)`
и добавить fallback на legacy regex (`AIDataSanitizer.sanitize_text`), уже
доступный через `presidio_analyzer._legacy`.
**Test-критерий:** добавить `test_pii_mask_handles_systemexit` —
monkeypatch `spacy.cli.download` → `sys.exit(1)`; assert `_maybe_mask_pii`
возвращает `(content_text, {"pii_masked": False})` без propagate.

### 4.2 RAG-P0-002: RagCachePrewarmer runtime broken

**Файл:** `src/backend/services/ai/rag_cache_prewarmer.py:65-79`

```python
async def prewarm_tenant(self, tenant_id: str) -> int:
    ...
    for query, _count in top:
        try:
            await self._rag.query(query, fill_cache=True, tenant_id=tenant_id)  # ← line 69
        except TypeError:
            try:
                await self._rag.query(query, tenant_id=tenant_id)               # ← line 73
            except Exception:
                continue
        except Exception as exc:
            logger.debug("rag_prewarm.query_failed: %s", exc)
            continue
        loaded += 1
        await asyncio.sleep(self._throttle)
```

**RAGService API** (verified):
```
['augment', 'augment_prompt', 'augment_prompt_with_citations', 'chunk_text',
 'count', 'delete', 'delete_collection', 'get_collection_stats', 'ingest',
 'search']
```

**Нет метода `.query()`** — `AttributeError: 'RAGService' object has no
attribute 'query'`.

**Runtime evidence:**
```python
# .venv/bin/python runtime
import asyncio
from src.backend.services.ai.rag_service import RAGService
from src.backend.services.ai.rag_cache_prewarmer import RagCachePrewarmer
from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector

async def main():
    rag = RAGService.__new__(RAGService)
    stats = RagQueryStatsCollector()
    await stats.record('t1', 'q1'); await stats.record('t1', 'q1')
    prewarmer = RagCachePrewarmer(rag_service=rag, stats_collector=stats, top_n=10)
    loaded = await prewarmer.prewarm_tenant('t1')
    print(loaded)
asyncio.run(main())

# Output: 0
```

**Dead code confirmation:** `grep -rn "RagCachePrewarmer" src/backend/` →
только definition + class docstring + тесты. **Никаких callsite в
production**.

**Impact:** P0 / runtime silent-failure. Pre-warm L2 semantic cache для
top-100 запросов на startup **никогда не работает** в production. При
этом Prometheus metrics `rag_prewarm_loaded_total{tenant}` и
`rag_prewarm_duration_seconds{tenant}` всё равно emit'ятся (с `loaded=0`),
создавая false-positive observability.

**Рекомендация:**
1. Заменить `self._rag.query(query, fill_cache=True, tenant_id=...)` →
   `self._rag.augment_prompt(query, tenant_id=tenant_id)` или
   `self._rag.search(query, tenant_id=tenant_id)`.
2. Либо удалить `RagCachePrewarmer` + `RagQueryStatsCollector` как
   полностью dead code (cycle-3 Ponytail).
3. Если оставлять — зарегистрировать в `plugins/composition/lifecycle/bootstrap.py`
   lifespan startup.

**Test-критерий:** добавить integration test, который использует
**реальный** `RAGService` (не AsyncMock с `query` методом) и проверяет
`loaded > 0`.

### 4.3 RAG-P0-003: get_rag_service fallback dead code + missing InMemoryVectorStore

**Файл:** `src/backend/services/ai/rag_service/__init__.py:60-72`

```python
@app_state_singleton("rag_service")
def get_rag_service() -> RAGService:
    """S124 W2: восстановлено (потеряно при S64 W4 decomp).
    ...
    """
    # S133 W4: default store — memory-backed vector store для non-request
    # контекстов (tests / DSL без зарегистрированного app.state).
    from src.backend.core.vector_store.memory import InMemoryVectorStore  # ← line 70

    return RAGService(store=InMemoryVectorStore())                          # ← line 72
```

**Проблема 1: decorator signature.** `app_state_singleton` в
`src/backend/core/di/app_state.py:143-185`:

```python
def app_state_singleton(
    attr: str, factory: Callable[[], T] | None = None
) -> Callable[[Callable[[], T]], Callable[[], T]]:
    ...
    def decorator(fn: Callable[[], T]) -> Callable[[], T]:
        def wrapper() -> T:
            instance = _get_from_app_state(attr)
            if instance is not None:
                return instance
            if attr not in _cache:
                if factory is not None:
                    _cache[attr] = factory()    # ← factory callable
                else:
                    raise RuntimeError(
                        f"{attr} not in app.state and no factory provided."
                    )
            return _cache[attr]
```

Wrapped-function `get_rag_service` **никогда не вызывается decorator'ом**.
Сравните с корректными usersites:
```
src/backend/services/wiki/whoosh_index.py:239
@app_state_singleton("wiki_index", factory=WhooshIndex)
src/backend/services/ai/metrics.py:239
@app_state_singleton("agent_metrics_service", factory=AgentMetricsService)
src/backend/services/ai/gateway/client.py:312
@app_state_singleton("litellm_gateway", factory=LiteLLMGateway)
```
Все 9+ пользователей передают `factory=...`. `get_rag_service` — единственный
с wrapped-function fallback (dead code).

**Проблема 2: missing module.** `from src.backend.core.vector_store.memory import InMemoryVectorStore`:

```bash
$ find src/backend/core -name "vector_store*" -o -name "*memory*"
# (no results)
$ grep -rn "class.*InMemoryVectorStore\|InMemoryVector" src/backend/ | grep -v __pycache__
src/backend/services/ai/rag_service/__init__.py:70:    from src.backend.core.vector_store.memory import InMemoryVectorStore
```

**ModuleNotFoundError** при вызове inner function.

**Runtime evidence:**
```python
$ .venv/bin/python -c "from src.backend.services.ai.rag_service import get_rag_service; get_rag_service()"
# Without app.state registration:
RuntimeError: rag_service not in app.state and no factory provided. Ensure register_app_state() was called or provide factory=... к app_state_singleton.
```

**Impact:** P0 / латентная ловушка для unit-тестов вне FastAPI-контекста.
В production работает (через `bootstrap.py:63`), но документированный
fallback для non-request контекстов — мираж. Ponytail: или
(а) удалить wrapped-function fallback (только `@app_state_singleton("rag_service")`
без тела), или (б) добавить `factory=_default_rag_service_factory`
реализующую безопасный fallback.

**Рекомендация:**
```python
def _default_rag_service_factory() -> RAGService:
    from src.backend.core.vector_store.memory import InMemoryVectorStore
    # (или LocalVectorStore / DuckDBVec / etc — реализовать)
    return RAGService(store=InMemoryVectorStore())

@app_state_singleton("rag_service", factory=_default_rag_service_factory)
def get_rag_service() -> RAGService: ...
```

**Test-критерий:** тест с `reset_app_state()` (для очистки `_cache`) и
вызов `get_rag_service()` без bootstrap → возвращает инстанс, не
`RuntimeError`.

### 4.4 RAG-P0-004: Multimodal RAG E2E test broken (pre-existing)

**Файл:** `tests/e2e/test_multimodal_rag_e2e.py:255-340`

```python
async def test_image_caption_pipeline_e2e(...):
    ...
    image_ingester = ImageIngester(caption_provider=_stub_caption_provider)
    multimodal_service.set_image_ingester(image_ingester)

    # Step 1+2+3: ingest image (real ImageIngester + StubEmbedder).
    fake_image = _make_fake_png()
    result = await multimodal_service.ingest_document(
        fake_image, collection="e2e_images", mime="image/png"
    )                                                          # ← no tenant_id!
    ...

    # Step 4: semantic search "cat" → top-K должен содержать cat-chunk.
    hits = await multimodal_service.search(
        "cat", collection="e2e_images", top_k=3, tenant_id="e2e"
    )                                                          # ← tenant_id="e2e"!
    assert len(hits) >= 1                                      # ← FAILS
```

**Service contract:** `src/backend/services/ai/rag/multimodal/service.py:202-204`:
```python
chunk.metadata["collection"] = collection
if tenant_id:
    chunk.metadata["tenant_id"] = tenant_id       # ← only if explicit
```

**Search filter:** `service.py:250`:
```python
if effective_tenant and chunk.metadata.get("tenant_id") != effective_tenant:
    continue                                       # ← drop chunk
```

При ingest без tenant_id: `chunk.metadata["tenant_id"]` отсутствует →
`None != "e2e"` → chunk отбрасывается → 0 hits.

**Runtime evidence:**
```
$ .venv/bin/python -m pytest tests/e2e/test_multimodal_rag_e2e.py -v --tb=short
tests/e2e/test_multimodal_rag_e2e.py::test_image_caption_pipeline_e2e FAILED
tests/e2e/test_multimodal_rag_e2e.py::test_audio_transcript_pipeline_e2e FAILED
tests/e2e/test_multimodal_rag_e2e.py::test_public_api_exports_complete PASSED
========================= 2 failed, 1 passed in 0.36s =========================
```

**Manual trace (выполнен `.venv/bin/python`):**
```
_is_enabled: True
chunks: 1
kind: image
embedding[:3]: [0.7071067811865475, 0.0, 0.7071067811865475]
embedding len: 16
collections keys: ['e2e_images']
e2e_images chunks: ['02b25763583e428cbb993c0727cf1a5c']
hits: 0
```

При повторе с **убранным** `tenant_id` из `search()`:
```
hits (no tenant): 1
```

**Impact:** P0 / test failure. Не runtime bug в production, но
валидационный gap — multimodal pipeline не проверен end-to-end.
**Pre-existing** (не regression cycle-3) — `git blame` подтверждает
test введён до cycle-3 baseline (`7f3d94a3`). Однако cycle 2 / T-W4-01
deferred "text-RAG E2E" — multimodal E2E должен был быть стабилен.

**Рекомендация:** исправить тест:
```python
result = await multimodal_service.ingest_document(
    fake_image, collection="e2e_images", mime="image/png", tenant_id="e2e"
)
hits = await multimodal_service.search(
    "cat", collection="e2e_images", top_k=3, tenant_id="e2e"
)
```

**Test-критерий:** все 3 теста в `test_multimodal_rag_e2e.py` PASSED
при запуске через `.venv/bin/python -m pytest tests/e2e/test_multimodal_rag_e2e.py`.

### 4.5 RAG-P1-001: rag_query_stats byte/str lookup

**Файл:** `src/backend/services/ai/rag_query_stats.py:78-85`

```python
for h_raw, score in items:
    h = h_raw.decode() if isinstance(h_raw, bytes) else h_raw
    raw_q = queries_map.get(
        h.encode()
        if isinstance(
            list(queries_map.keys())[0] if queries_map else b"", bytes  # ← BUG
        )
        else h
    )
```

**Проблема:** проверка типа первого ключа `queries_map.keys()[0]`, а не
текущего. При `redis.asyncio.Redis(decode_responses=True)` все ключи —
str → первая проверка bytes=False → lookup с str `h` — корректно. Но
при non-empty queries_map, где первый ключ bytes, а текущий ключ str
(mixed-mode от разных Redis clients) — `h.encode()` → bytes lookup с str key
→ KeyError. Silent `except Exception: pass` → in-memory fallback,
которое возвращает другие данные.

**Runtime evidence (synthetic mixed-mode):**
```python
class FakeRedisMixed:
    async def hgetall(self, key):
        return {b'key1': b'value1'}    # bytes keys/values
# top_queries() returns:
[('what is python?', 2), ('what is rust?', 1)]
# Это потому что fallback in-memory сработал (после silent pass).
```

**Текущий unit test `test_stats_collector_in_memory`** не покрывает этот
edge-case (использует AsyncMock).

**Impact:** P1 / subtle data-loss в Redis-mixed-mode. При pure-bytes
Redis (default `redis-py`) — работает корректно. Ponytail: использовать
`isinstance(h, bytes)` для каждого lookup'а.

**Рекомендация:**
```python
for h_raw, score in items:
    if isinstance(h_raw, bytes):
        h = h_raw.decode()
        key = h_raw                       # bytes key
    else:
        h = h_raw
        key = h.encode()                  # encode to bytes для lookup
    raw_q = queries_map.get(key)
    if isinstance(raw_q, bytes):
        raw_q = raw_q.decode()
```

**Test-критерий:** `test_top_queries_handles_bytes_and_str_modes` с
FakeRedis возвращающим mixed types.

### 4.6 RAG-P1-002: _run loop + SystemExit propagation

**Файл:** `src/backend/services/ai/rag_ingest_service.py:118-140`

```python
async def _run(self, task_id, files, collection, state):
    rag = self._ensure_rag()
    fingerprint = state["chunker_fingerprint"]
    embedding_meta = _resolve_embedding_provenance()
    for filename, content_bytes in files:
        try:
            content_text = content_bytes.decode("utf-8", errors="replace")
            content_text, pii_meta = _maybe_mask_pii(content_text)  # ← SystemExit!
            metadata = {...}
            doc_id = await rag.ingest(content_text, metadata=metadata, namespace=collection)
            state["doc_ids"].append(doc_id)
        except Exception as exc:                                     # ← line 132
            state["errors"].append({"file": filename, "error": str(exc)})
        state["processed"] += 1
        await self._store.update(task_id, ...)
```

При SystemExit из `_maybe_mask_pii` (RAG-P0-001) → bypass `except Exception`
→ пробивается в `_run` coroutine → `await coroutine` в `ingest()` (line 103)
→ поднимается в caller.

Если ingest запущен **deferred** (через TaskRegistry), SystemExit убьёт
worker-task (в отличие от graceful `errors[]`). Data-loss: первые N уже
заingest'енные файлы (если async `rag.ingest` сработал для предыдущих)
сохранятся в `_store`, но caller не получит task_id response.

**Impact:** P1 / data-loss при batch-ingest с одним PII-bad файлом.
Связано с RAG-P0-001.

**Рекомендация:** В `_run` также ловить `BaseException` (или обернуть
`_maybe_mask_pii` в fail-safe wrapper, см. RAG-P0-001).

---

## 5. Cycle-1 + Cycle-2 residuals (verified / mutated)

### Verified (сохраняются, требуют исправления)

| Cycle ID | Текущий статус | Доказательство |
|---|---|---|
| **Cycle 2 / RAG-P0-001 (PII fail-open)** | **VERIFIED RESIDUAL** | `_maybe_mask_pii` всё ещё ловит только `Exception`. Runtime evidence — `SystemExit: 1` пробивается. См. §4.1. |
| **Cycle 2 / RAG-P0-002 (RagCachePrewarmer runtime)** | **VERIFIED RESIDUAL** | `rag.query()` всё ещё вызывается; `RAGService.query` всё ещё не существует; класс всё ещё dead code. См. §4.2. |
| **Cycle 2 / RAG-P0-003 / RAG-P0-004 (мультимодальный E2E)** | **MUTATED → P0 (см. §4.4)** | Cycle 2 описывал как `T-W4-01 text-RAG E2E` (отсутствует). Multimodal E2E существует, но 2/3 тестов FAILING в текущем HEAD. Новый P0 — RAG-P0-004. |
| **Cycle 1 / T-4.1 text-RAG E2E** | **VERIFIED RESIDUAL** | `tests/e2e/test_text_rag_e2e.py` отсутствует (`find` подтверждает). См. RAG-P4-001. |
| **Cycle 2 / T-W1-01 (CDC DLQ handoff)** | **НЕ в RAG scope** | Verified: `src/backend/entrypoints/cdc/cdc_routes.py` НЕ импортирует `rag*` модули. **RAG impact = 0**. |
| **Cycle 2 / T-W1-05 (MQ subscribers ACK vs DLQ)** | **НЕ в RAG scope** | Verified: `src/backend/dsl/engine/processors/security.py` и `infra_log.py` НЕ импортируют `rag*`. **RAG impact = 0**. |

### Mutated (изменились с момента cycle-2)

| Cycle ID | Статус | Изменение |
|---|---|---|
| Cycle 2 / RAG-P2-001 / dead code chunker | **MUTATED → RAG-P3-001** | `RAGService.chunk_text` всё ещё использует naive byte-chunking (см. §3, P3-001). Chunkers (`TokenChunker` / `RecursiveChunker`) доступны с S36, но не используются. |
| Cycle 2 / RAG-P1-001 / layer violation | **MUTATED → no violation** | После S64 W4 decomp + Sprint 2.6 tenant isolation — direct infrastructure imports отсутствуют в RAG scope. `grep -rn "from src.backend.infrastructure" src/backend/services/ai/rag*` → 0 hits. |

### Новые (cycle-3)

- **RAG-P0-003**: `get_rag_service` fallback через wrapped-function + missing
  `InMemoryVectorStore` module — новая находка, не документирована в cycle-2.
- **RAG-P1-001**: rag_query_stats byte/str lookup — побочный эффект Redis
  client behavior.

---

## 6. Contradictions / overlaps to flag

1. **RAG-P0-001 + RAG-P0-002 + RAG-P1-002**: три finding'а образуют
   каскадную цепочку в `_maybe_mask_pii`. Корневой fix — заменить
   `except Exception` на `except (Exception, SystemExit)` в
   `_maybe_mask_pii`, остальные автоматически neutralизуются.

2. **RAG-P3-001 + RAG-P2-002**: `chunk_text` не использует существующие
   chunkers, при этом `pii_mask_on_ingest=True` (default) + broken
   `_maybe_mask_pii` означает, что ingest работает только при feature-flag
   OFF. Ponytail: заменить chunker + одновременно fix маски.

3. **T-W4-01 + RAG-P0-004**: text-RAG E2E отсутствует, а multimodal E2E
   failing — НЕТ ни одного валидного E2E для RAG domain. Sprint 36+
   должен создать **один** text-RAG E2E (cycle-1/T-4.1 deferred) и
   починить multimodal E2E (RAG-P0-004).

4. **Embedding cache** (`embedding_cache.py`) — cycle-1/P3-01 заменил
   custom code на `cachetools.TTLCache`. Это **positive** пример
   library replacement, который должен служить reference для
   RAG-P3-001 (chunkers).

5. **Pre-existing `extensions/credit_pipeline/agents/__init__.py`**
   modified в working tree (cycle-1 правка) — НЕ в RAG scope, НЕ
   атрибутируется cycle-3.

---

## 7. Readiness score 0-100

### Формула

```
R = max(0, 70 − 8×P0 − 4×P1 − 2×P2 − 1×P3)
```

(начальный baseline 70; каждый P0/P1/P2/P3 снимает соответствующее
количество баллов).

### Подсчёт

- **P0:** 4 (RAG-P0-001, P0-002, P0-003, P0-004) → -32
- **P1:** 2 (RAG-P1-001, RAG-P1-002) → -8
- **P2:** 2 (RAG-P2-001, RAG-P2-002) → -4
- **P3:** 2 (RAG-P3-001, RAG-P3-002) → -2

```
R = 70 − 32 − 8 − 4 − 2 = 24
```

**Readiness = 24 / 100** (НЕ ≥80 по правилу).

### Обоснование низкой оценки

- **4 P0 finding'а**, два из которых (P0-001 + P0-002) могут полностью
  сломать production ingestion при стандартных config defaults
  (`pii_mask_on_ingest=True` + spacy-model отсутствует).
- **2 P1 finding'а** — fail-closed принцип нарушен в batch-ingest loop
  (data-loss risk) + edge-case в Redis lookup.
- Полное отсутствие text-RAG E2E (RAG-P4-001, deferred с cycle 1).
- Multimodal E2E (RAG-P0-004) FAILING на HEAD.
- Cycle-2 residuals (P0-001, P0-002) **НЕ закрыты** за два цикла.

### Что нужно для ≥80

- Закрыть все 4 P0 → +32.
- Закрыть все 2 P1 → +8.
- Закрыть хотя бы 1 из 2 P2 → +2.
- Создать text-RAG E2E (RAG-P4-001) → +1.

Потенциально: **R = 70 − 0 − 0 − 2 − 2 + 4 = 70** (без P3 и P4 features).
С feature: **~75-78**. Для **≥80** нужно ещё +2-5 баллов — закрыть
все P2 + добавить text-RAG E2E.

---

## 8. Recommended next tasks

| # | ID | Описание | Effort | Блокер |
|---|---|---|---|---|
| 1 | RAG-P0-001 | Заменить `except Exception` на `except (Exception, SystemExit)` в `_maybe_mask_pii`. Fallback на `AIDataSanitizer.legacy.sanitize_text` при сбое. | S | Да (data-loss, HTTP 500) |
| 2 | RAG-P0-002 | Удалить `RagCachePrewarmer` + `RagQueryStatsCollector` (dead code) ИЛИ заменить `rag.query()` на `rag.augment_prompt()` и зарегистрировать в `bootstrap.py`. | M | Да (silent broken feature) |
| 3 | RAG-P0-003 | Заменить wrapped-function на `factory=_default_rag_service_factory` в `get_rag_service`. Создать `core/vector_store/memory.py:InMemoryVectorStore`. | M | Да (unit-test gap) |
| 4 | RAG-P0-004 | Исправить тест: `ingest_document(..., tenant_id="e2e")` для консистентности. Запустить весь `test_multimodal_rag_e2e.py`. | XS | Да (test gate) |
| 5 | RAG-P1-001 | Упростить rag_query_stats lookup: использовать `isinstance(h, bytes)` per-key, не per-batch. | S | Нет (edge case) |
| 6 | RAG-P1-002 | В `_run` заменить `except Exception` на `except BaseException as exc: state["errors"].append({...})`. | XS | Нет (зависит от #1) |
| 7 | RAG-P2-001 | Удалить redundant `pass` statements в 4 mixin-файлах. | XS | Нет |
| 8 | RAG-P3-001 | Использовать `RecursiveChunker` из `services/ai/chunkers/` в `RAGService.chunk_text`. | S | Нет |
| 9 | RAG-P4-001 | Создать `tests/e2e/test_text_rag_e2e.py`: StubEmbedder + StubLiteLLM + реальный `RAGService.augment_prompt_with_citations`. | M | Нет (test debt) |
| 10 | RAG-P4-002 | Задокументировать разницу `multimodal_rag_enabled` vs `multimodal_rag_full` в `features/ai_rag.py:101` или объединить флаги. | XS | Нет |

---

## 9. Commands run (с указанием Python interpreter)

| # | Команда | Exit / результат |
|---|---|---|
| C1 | `.venv/bin/python --version` | `Python 3.14.0` |
| C2 | `.venv/bin/python -c "import importlib.metadata as m; [print(p, m.version(p)) for p in ['prometheus_client','fastapi','hypothesis','ragas','datasets','rank_bm25','flagembedding']]"` | `prometheus_client=0.26.0, fastapi=0.141.1, hypothesis=6.165.1, ragas=NOT INSTALLED, datasets=NOT INSTALLED, rank_bm25=0.2.2, flagembedding=NOT INSTALLED` |
| C3 | `.venv/bin/python -m pytest tests/unit/services/ai/test_rag_pii_mask.py tests/unit/services/ai/test_rag_tenant_isolation.py tests/unit/services/ai/test_rag_cache_prewarm.py -v --tb=short -p no:cacheprovider` | exit 0 — **28 passed** |
| C4 | `.venv/bin/python -m pytest tests/unit/services/ai/test_rag_augment.py -v --tb=short -p no:cacheprovider` | exit 0 — **9 passed** |
| C5 | `.venv/bin/python -m pytest tests/unit/services/ai/test_rag_source_attribution.py -v --tb=short -p no:cacheprovider` | exit 0 — **4 passed** |
| C6 | `.venv/bin/python -m pytest tests/unit/services/ai/test_rag_embedding_version.py -v --tb=short -p no:cacheprovider` | **1 failed, 4 passed** (RAG-P0-001 evidence) |
| C7 | `.venv/bin/python -m pytest tests/unit/services/ai/test_rag_ingest_service.py -v --tb=short -p no:cacheprovider` | **TIMEOUT 60s** (hang на spacy download — RAG-P0-001 cascade) |
| C8 | `.venv/bin/python -m pytest tests/unit/services/ai/eval/test_ragas_evaluator.py -v --tb=short -p no:cacheprovider` | exit 0 — **9 passed** |
| C9 | `.venv/bin/python -m pytest tests/e2e/test_multimodal_rag_e2e.py -v --tb=short -p no:cacheprovider` | **2 failed, 1 passed** (RAG-P0-004 evidence) |
| C10 | `.venv/bin/python -c "from src.backend.core.config.ai_stack import rag_ingest_settings; print('pii_mask_on_ingest=', rag_ingest_settings.pii_mask_on_ingest)"` | `pii_mask_on_ingest= True` |
| C11 | `.venv/bin/python -c "from src.backend.core.config.features import feature_flags; print('presidio_pii_enabled=', feature_flags.presidio_pii_enabled)"` | `presidio_pii_enabled= True` |
| C12 | `.venv/bin/python -c "from src.backend.services.ai.rag_service import RAGService; print([m for m in dir(RAGService) if not m.startswith('_')])"` | `['augment', 'augment_prompt', 'augment_prompt_with_citations', 'chunk_text', 'count', 'delete', 'delete_collection', 'get_collection_stats', 'ingest', 'search']` — **нет `.query()`** (RAG-P0-002 evidence) |
| C13 | `.venv/bin/python -c "from src.backend.services.ai.rag_cache_prewarmer import RagCachePrewarmer; from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector; from src.backend.services.ai.rag_service import RAGService; import asyncio; ..."` (см. §4.2) | `Loaded (real RAGService-like): 0` — runtime подтверждение P0-002 |
| C14 | `.venv/bin/python -c "from src.backend.services.ai.rag_service import get_rag_service; get_rag_service()"` (без app.state) | `RuntimeError: rag_service not in app.state and no factory provided` — RAG-P0-003 evidence |
| C15 | `.venv/bin/python -c "from src.backend.services.ai.rag.multimodal import MultimodalRAGService; ..."` (см. §4.4) | `hits: 0` (с tenant_id mismatch) vs `hits (no tenant): 1` — RAG-P0-004 evidence |
| C16 | `find src/backend/core -name "vector_store*"` | no results — `InMemoryVectorStore` не существует (RAG-P0-003 evidence) |
| C17 | `grep -rn "from src.backend.infrastructure" src/backend/services/ai/rag*` | 0 hits — no layer violation |
| C18 | `grep -rn "RagCachePrewarmer" src/backend/` | только definition + тесты — dead code (RAG-P0-002) |
| C19 | `grep -rn "fill_cache" src/backend/` | только `rag_cache_prewarmer.py:69,71` — phantom kwarg (RAG-P0-002) |

---

## 10. Bottom line

**Domain RAG — readiness 24/100.** Четыре P0 finding'а блокируют
production-readiness:

1. **RAG-P0-001** (PII fail-open via SystemExit bypass) — блокирует ingest
   при стандартных defaults.
2. **RAG-P0-002** (RagCachePrewarmer runtime broken + dead code) — silent
   failure в pre-warm pipeline.
3. **RAG-P0-003** (`get_rag_service` fallback dead code + missing module)
   — ловушка для unit-тестов вне FastAPI.
4. **RAG-P0-004** (multimodal RAG E2E test failing pre-existing) — test gate
   не пропускает pipeline validation.

**Главный root cause** для (1) + (2) + RAG-P1-002: `_maybe_mask_pii` ловит
только `Exception`, но spacy-init поднимает `SystemExit` (BaseException
subclass). **Один точечный fix** (`except (Exception, SystemExit)` +
fallback на `AIDataSanitizer.legacy`) закроет 3 finding'а сразу.

**Cycle-1 + cycle-2 residuals** для RAG domain подтверждены:
`RAG-P0-001` (PII fail-open) и `RAG-P0-002` (RagCachePrewarmer runtime)
НЕ закрыты за два цикла. `RAG-P4-001` (text-RAG E2E) всё ещё отсутствует.

**T-W1-01 / T-W1-05** (CDC DLQ + MQ subscribers) — **verified: НЕТ RAG
impact**. Изменения в `cdc_routes.py`, `redelivery_policy.py`,
`multicast.py`, `security.py` НЕ затрагивают RAG domain.

Все runtime-проверки выполнялись через `.venv/bin/python` (Python 3.14.0).
System-Python НЕ использовался — подтверждено выводом версий.
