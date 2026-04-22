# ADR-014: Qdrant + fastembed как production RAG stack

* Статус: accepted
* Дата: 2026-04-21
* Фазы: D3

## Контекст

Исходная RAG-связка:
- chromadb (vector store) — local-first, но sync-API и заметные
  лимиты производительности; обёрнут в `asyncio.to_thread`.
- sentence-transformers (embeddings) — heavyweight (PyTorch стек,
  большие артефакты в Docker-образе).

Для production-нагрузки обе части требуют усиления.

## Решение

1. **qdrant-client** (async) — production-grade vector store с
   native async, HTTP/gRPC, mature filtering, distributed mode.
2. **fastembed** — ONNX-квантизованный embedder; существенно легче
   PyTorch-стэка, latency embed(512 tokens) ≈ 10x быстрее, weights
   ~80 MB вместо нескольких сотен.
3. Миграционный скрипт (chromadb → qdrant) — follow-up, выполняется
   заказчиком на своих данных; не входит в scope этой фазы.

## Альтернативы

- **Weaviate**: отвергнуто, тяжёлый deployment.
- **Milvus**: отвергнуто, requires external etcd/minio setup.
- **PgVector**: отвергнуто — для высоких нагрузок недостаточен.
- **Keep chromadb**: отвергнуто, лимиты production-load.

## Последствия

- Docker-образ уменьшается (без PyTorch).
- Vector store — внешний сервис (Qdrant), deploy вместе с приложением.
- `pyproject.toml`: ADD `qdrant-client`, `fastembed`; REMOVE
  `chromadb`, `sentence-transformers` в D3 (deps-matrix проверит).
