# Extensions Guide

Документация к новым опциональным фичам, добавленным после v17.

## Новые процессоры (21+ добавлено в v18)

### Enrichment
- `.geoip(ip_field, output_property)` — MaxMind GeoLite2 lookup
- `.jwt_sign(secret_key, expires_in_seconds)` — подписать JWT
- `.jwt_verify(secret_key, header)` — проверить JWT
- `.compress(algorithm="gzip|brotli|zstd")` — сжатие body
- `.decompress(algorithm="auto")` — распаковка
- `.webhook_sign(secret, header)` — HMAC-SHA256 для outgoing
- `.deadline(timeout_seconds)` — cross-processor deadline tracking

### ML / Inference
- `.onnx_infer(model_path, input_key, output_property)` — CPU ONNX inference
- `.streaming_llm(provider, session_header)` — streaming LLM через Redis stream
- `.embedding(provider, model)` — унифицированные embeddings (OpenAI/ST/Ollama)
- `.outbox(topic, table_name)` — transactional outbox для exactly-once

### Storage
- `.neo4j_query(cypher, params_from_body)` — Cypher queries
- `.timeseries_write(table, tags, field, backend)` — TimescaleDB / InfluxDB
- `.priority_enqueue(queue_name, priority_field)` — Redis ZSET priority queue

## AI провайдеры

Теперь поддерживаются 6 LLM провайдеров через ai_agent fallback chain:
- `perplexity` (web-grounded search)
- `huggingface` (OSS models)
- `open_webui` (локальный WebUI)
- `anthropic` / `claude` (Anthropic Claude)
- `gemini` / `google` (Google Gemini)
- `ollama` / `local` (локальные модели)

Активация новых провайдеров через env:
```bash
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
OLLAMA_URL=http://localhost:11434
```

## Performance

### msgspec for hot paths
```python
from app.utilities.fast_json import encode, decode

# 40x faster than Pydantic для simple dict serialization
data = encode({"id": 1, "items": [...]})  # bytes
restored = decode(data)
```

**Важно:** Pydantic v2 schemas НЕ заменяются — msgspec используется только
для internal hot paths (audit log, Redis payloads, internal messaging).

### OpenTelemetry auto-instrumentation
```python
# main.py
from app.infrastructure.observability.otel_auto import init_otel
init_otel(app=fastapi_app)
```

Автоматически инструментирует: FastAPI, httpx, SQLAlchemy, Redis, Logging.
Требует `OTEL_EXPORTER_OTLP_ENDPOINT` env var.

### taskiq (async Celery)
```python
from app.core.task_queue import task_queue

@task_queue.task(retries=3)
async def process_order(order_id: int) -> dict:
    # async work
    return {"status": "ok"}

# Enqueue from anywhere:
await process_order.kiq(order_id=123)
```

## AI Features

### Semantic Cache
```python
from app.services.ai.semantic_cache import get_semantic_cache

cache = get_semantic_cache()
hit = await cache.lookup(query)
if hit:
    return hit["response"]

response = await llm_call(query)
await cache.store(query, response)
```

Кеш hit по semantic similarity (>0.95) — экономит на LLM вызовах
для парафразированных запросов.

### Content Moderation
```python
from app.services.ai.ai_moderation import get_moderation

result = await get_moderation().check(user_input)
if result.flagged:
    raise ValueError(f"Content blocked: {result.reason}")
```

### RAGAS Evaluation
```python
from app.services.ai.ai_moderation import get_ragas

scores = await get_ragas().evaluate(
    question="...", answer="...", contexts=[...],
)
# {"faithfulness": 0.95, "answer_relevancy": 0.88, ...}
```

## Secrets Management

### Vault
```python
# settings.py
from app.core.secrets_sources import VaultSettingsSource

class MySettings(BaseSettings):
    db_password: str
    @classmethod
    def settings_customise_sources(cls, settings_cls, ...):
        return (
            init_settings, env_settings,
            VaultSettingsSource(settings_cls, "secret/myapp"),
        )
```

Требует `VAULT_ADDR` + `VAULT_TOKEN` env vars + библиотеку `hvac`.

### AWS Secrets Manager
```python
from app.core.secrets_sources import AwsSecretsManagerSource

AwsSecretsManagerSource(settings_cls, "prod/gd_integration")
```

Требует `AWS_REGION` + IAM credentials + boto3.

## DI via svcs

Для background tasks и CLI, когда FastAPI `Depends()` недоступен:
```python
from app.core.svcs_registry import register_factory, get_service

# At startup:
register_factory(RedisClient, lambda: get_redis_client())

# In background task:
redis = get_service(RedisClient)
```

## Testing

### Smoke tests
```bash
pytest tests/smoke/ -v
```

### Benchmarks (performance regression)
```bash
pytest tests/benchmark/ --benchmark-only
# Compare with baseline:
pytest tests/benchmark/ --benchmark-compare=baseline --benchmark-compare-fail=mean:10%
```

### E2E tests (Playwright)
```bash
pip install playwright
playwright install chromium
pytest tests/e2e/
```

## VSCode Snippets

`.vscode/gd-dsl.code-snippets` содержит snippets:
- `dsl-route` — базовый RouteBuilder
- `dsl-etl` — ETL pipeline с timer + poll
- `dsl-ai-qa` — AI Q&A с RAG + PII
- `dsl-webhook` — webhook handler
- `dsl-scrape` — web scraping
- `dsl-crud` — CRUD с аудитом
- `register-action` — @register_action декоратор
