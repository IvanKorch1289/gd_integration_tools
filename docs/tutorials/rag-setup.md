# Tutorial — RAG Setup

Цель: загрузить документы в RAG и проверить семантический поиск.

## Что вы узнаете
- Как настроить vector backend.
- Как загрузить документы (REST + multipart).
- Как использовать augmented-prompt.

## Шаги

1. Включите RAG в `.env`:
   ```env
   RAG_ENABLED=true
   RAG_VECTOR_BACKEND=qdrant   # или faiss / chroma
   ```
2. Ingest текста:
   ```bash
   curl -X POST /api/v1/rag/ingest \
        -H 'Content-Type: application/json' \
        -d '{"content":"Hello world","namespace":"docs"}'
   ```
3. Multipart-upload PDF:
   ```bash
   curl -X POST -F file=@manual.pdf -F namespace=docs /api/v1/rag/upload
   ```
4. Поиск:
   ```bash
   curl -X POST /api/v1/rag/search \
        -d '{"query":"hello","top_k":3,"namespace":"docs"}'
   ```

## Проверка
- `curl /api/v1/rag/stats?collection=docs` показывает `count > 0`.
- `/api/v1/rag/search` возвращает top-k chunks.

## Next steps
- [Multi-tenant](multi-tenant-setup.md)
- [Build search agent](build-first-action.md)
