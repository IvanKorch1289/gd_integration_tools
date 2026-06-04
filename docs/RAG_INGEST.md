# RAG Ingest — Project Documentation

Sprint 40 W5 · v15 §10 · RAG over project documentation.

## Что это

`DocsIndexer` — компонент RAG-пайплайна, который индексирует markdown-документацию
проекта (CLAUDE.md, .claude/CLAUDE.md, docs/users/*.md, docs/devs/*.md) в Qdrant
collection `project_docs` и предоставляет семантический поиск по ней.

## Зачем

AI-ассистенты (Claude Code, Hermes Agent, чат-боты) должны иметь возможность
находить релевантные места в проектной документации по смыслу запроса, а не
по точному совпадению подстроки. RAG-поиск позволяет по вопросу "как поднять
dev среду?" находить не только буквальные вхождения, но и близкие по смыслу
разделы (setup, install, bootstrap, run locally и т.д.).

## Использование

### Базовое

```python
import asyncio
from src.backend.ai.rag.docs_indexer import DocsIndexer

async def main() -> None:
    indexer = DocsIndexer()  # qdrant_client=None → in-memory fallback
    n = await indexer.index_docs()  # discover default roots → chunk → embed → upsert
    print(f"indexed {n} chunks")
    hits = await indexer.search("как поднять dev среду?", limit=5)
    for h in hits:
        print(f"  score={h['score']:.3f}  file={h['metadata'].get('file')}")

asyncio.run(main())
```

### С реальным Qdrant

```python
from qdrant_client import QdrantClient
from src.backend.ai.rag.docs_indexer import DocsIndexer

client = QdrantClient(host="localhost", port=6333)
indexer = DocsIndexer(
    qdrant_client=client,
    collection_name="project_docs",
    embedding_model="text-embedding-3-small",
    chunk_size=512,
    chunk_overlap=50,
)
await indexer.index_docs()
```

### DI кастомного embedder

```python
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def embed_openai(texts: list[str]) -> list[list[float]]:
    resp = await client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [e.embedding for e in resp.data]

indexer = DocsIndexer().set_embedder(embed_openai)
```

## API

### `DocsIndexer`

| Метод | Описание |
|---|---|
| `__init__(qdrant_client, embedding_model, collection_name, chunk_size, chunk_overlap)` | DI: инжекция Qdrant, параметров chunking и embedder-модели |
| `discover_docs(roots)` | Поиск всех `.md` файлов в `roots` (default: CLAUDE.md, .claude/CLAUDE.md, docs/users, docs/devs) |
| `chunk_text(text, metadata)` | Split text на chunks фиксированного размера с overlap; возвращает list[dict] с `id`, `text`, `metadata` |
| `index_docs(docs)` | Async: discover → chunk → embed → upsert. Idempotent (hash-based id) |
| `search(query, *, limit)` | Async: embed query → cosine search → top-N hits |
| `set_embedder(embed_fn)` | DI: заменить offline hash-based embedder на кастомный (sync/async) |
| `collection_name` (property) | Имя Qdrant collection |
| `is_fallback` (property) | True, если используется InMemoryQdrantFallback (qdrant_client=None) |

### `InMemoryQdrantFallback`

Минимальный in-memory заменитель Qdrant для unit-тестов и dev-light режима.
API совместимо с базовыми методами `qdrant_client.QdrantClient`:
`get_collection`, `create_collection`, `upsert`, `search`.

## Idempotency

Chunk `id` = `sha256(chunk_text)[:16]`. Повторный `index_docs` с тем же
контентом → Qdrant upsert по существующему id → overwrite. Никаких дублей.

## Graceful degradation

`qdrant_client=None` → автоматически создаётся `InMemoryQdrantFallback`.
Indexer остаётся полностью функциональным (embed + chunk + cosine search),
но данные живут только в памяти процесса. Подходит для unit-тестов, dev-light
режима, smoke-проверок.

## Chunking

* **chunk_size**: 512 chars (default)
* **chunk_overlap**: 50 chars (default)
* **id**: sha256(text)[:16] (16 hex chars)
* **metadata**: `file`, `source_path`, `file_hash`, `line`, `chunk_index`, `hash`

Overlap зажат в диапазон `[0, chunk_size - 1]` автоматически (защита от
`chunk_overlap >= chunk_size`).

## Что индексируется

| Путь | Тип |
|---|---|
| `CLAUDE.md` | file (root project rules) |
| `.claude/CLAUDE.md` | file (agent-scoped rules) |
| `docs/users/*.md` | recursive (`**/*.md`) |
| `docs/devs/*.md` | recursive (`**/*.md`) |

Игнорируется: `.py`, `.json`, `.txt`, и любые не-`.md` файлы.
Несуществующие пути в `roots` тихо пропускаются.

## Verification

```bash
.venv/bin/python -c "from src.backend.ai.rag.docs_indexer import DocsIndexer; print('OK')"
.venv/bin/python -m pytest tests/unit/ai/rag/test_docs_indexer.py -q --tb=short
.venv/bin/python -m ruff check src/backend/ai/rag/docs_indexer.py tests/unit/ai/rag/test_docs_indexer.py
```

## См. также

* `src/backend/services/ai/rag/` — RAG-сервисы (retrievers, classifiers, multimodal)
* `src/backend/services/ai/rag_ingest_service.py` — general-purpose RAG ingest (non-docs)
* `src/backend/services/ai/rag_service.py` — RAG orchestration (query → answer)
* `CLAUDE.md` — v22 source of truth
* `PLAN.md` V22 — roadmap
