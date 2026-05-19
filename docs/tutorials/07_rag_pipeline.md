# Tutorial 07 — RAG pipeline с Qdrant + reranker + freshness

> **Prerequisites:** Qdrant запущен (см. `docker-compose.yml`). ~50 минут.

## Цель

Построить RAG pipeline: upload документов → векторизация → search
top_k → augment prompt с freshness-фильтрацией → LLM ответ.

## Шаги

### 1. Upload документ

```bash
curl -X POST http://localhost:8000/api/v1/rag/upload \
  -F "file=@policy.pdf" \
  -F "namespace=docs" \
  -F 'metadata_json={"source": "policy"}'
```

### 2. Search top-k

```bash
curl -X POST http://localhost:8000/api/v1/rag/search \
  -H "Content-Type: application/json" \
  -d '{"query": "rate limits", "top_k": 5, "namespace": "docs"}'
```

### 3. Augment prompt с freshness

```bash
curl -X POST http://localhost:8000/api/v1/rag/augment \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is rate limit?",
    "top_k": 5,
    "namespace": "docs",
    "max_staleness_hours": 72
  }'
```

Response:

```json
{
  "prompt": "...",
  "citations": [
    {"doc_id": "policy.pdf", "chunk_idx": 3, "freshness": "fresh"},
    {"doc_id": "policy.pdf", "chunk_idx": 7, "freshness": "stale"}
  ],
  "freshness_distribution": {"fresh": 1, "stale": 1, "expired": 0},
  "worst_freshness": "stale",
  "skipped_expired": 0
}
```

### 4. DSL processor — rag_query

```yaml
steps:
  - rag_query:
      query_field: question
      top_k: 5
      namespace: docs
      max_staleness_hours: 72
      output_property: rag_result
  - llm_call:
      model: gpt-4o-mini
      prompt: ${properties.rag_result.prompt}
```

### 5. Проверить в UI

Открыть `pages/22_RAG_Console` → секция "Augment". Будет показан
freshness badge (FRESH/STALE/EXPIRED), distribution metrics,
skipped_expired counter.

## What's next?

* Tutorial 11 — ClickHouse audit (логирование retrieval запросов).
* Runbook `clickhouse-flush-tuning.md` — bulk writer тюнинг.
* GAP-AI-3.3 — freshness indicator (Sprint 9 K4 W3).
