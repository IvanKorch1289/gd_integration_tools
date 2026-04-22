# Фаза D3 — RAG stack upgrade (qdrant + fastembed)

* **Статус:** done
* **Приоритет:** P1
* **ADR:** ADR-014
* **Зависимости:** D2

## Выполнено

- `src/infrastructure/ai/vector_store.py` — новый `QdrantVectorStore`
  на async qdrant-client; scaffold с upsert/search методами.
- `pyproject.toml` — ADD `qdrant-client ^1.12.0`, `fastembed ^0.4.0`.
- Существующие `services/ai/rag_service.py`, `hybrid_rag.py`,
  `ml_inference.py` — используют chromadb/sentence-transformers как
  optional-импорт; миграция на qdrant/fastembed — постепенно в
  зависимости от запросов заказчика (chromadb и sentence-transformers
  не объявлены в pyproject — это сохраняет возможность dev-среды для
  legacy-data, но в CI новая связка — дефолт).

## Definition of Done

- [x] QdrantVectorStore scaffold.
- [x] pyproject: qdrant-client, fastembed.
- [x] ADR-014.
- [x] `docs/phases/PHASE_D3.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (D3 → done).

## Follow-up

Migration script chroma → qdrant (dev-tool) — в H2 scaffolding.
