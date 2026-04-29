# TaskIQ worker — runbook

## Что это

`InvocationMode.ASYNC_QUEUE` пушит сериализованный `InvocationRequest`
в TaskIQ-очередь. Исполнение задач происходит **отдельным
процессом-воркером**, который слушает очередь и для каждой задачи
вызывает `Invoker.invoke` в режиме `SYNC` с публикацией результата
в указанный `reply_channel`.

## Конфигурация

| Переменная | Default | Назначение |
|---|---|---|
| `TASKIQ_BACKEND` | `memory` | `memory` (`InMemoryBroker`) \| `redis` (`ListQueueBroker` + `RedisAsyncResultBackend`) |
| `TASKIQ_REDIS_URL` | `redis://localhost:6379/0` | URL для backend=redis. Берётся также из `settings.taskiq.redis_url` или `settings.redis.url`. |
| `TASKIQ_ENABLED` | `true` | Полностью отключить broker startup (для unit-тестов). |

## Режимы запуска

### 1. dev_light / unit-тесты — `InMemoryBroker`

Worker не нужен. Брокер запускается автоматически в FastAPI lifespan
(`setup_infra._taskiq_startup`). `kiq()` исполняет задачу inline в
текущем процессе, результат сразу публикуется в reply-канал.

Ничего настраивать не нужно — это поведение по умолчанию.

### 2. Локальная разработка с Redis — отдельный worker-процесс

```bash
# 1. Запустить Redis (например, docker run -p 6379:6379 redis:7-alpine).
# 2. Включить Redis backend:
export TASKIQ_BACKEND=redis
export TASKIQ_REDIS_URL=redis://localhost:6379/0

# 3. Запустить FastAPI-приложение (как обычно):
uv run python -m app.main

# 4. В отдельном терминале — TaskIQ worker:
uv run taskiq worker src.infrastructure.execution.taskiq_broker:broker
```

Worker слушает Redis, исполняет задачи, публикует результаты.

### 3. Prod / Docker compose — отдельный сервис

```yaml
# docker-compose.prod.yml (фрагмент)
services:
  taskiq-worker:
    build: .
    command: uv run taskiq worker src.infrastructure.execution.taskiq_broker:broker --workers 4
    environment:
      TASKIQ_BACKEND: redis
      TASKIQ_REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped
```

Масштабируется горизонтально (несколько контейнеров). Каждый worker
обрабатывает задачи независимо; Redis-очередь распределяет нагрузку.

## Мониторинг

### Метрики worker'а

Worker логирует через `logger="infrastructure.execution.taskiq_broker"`.
Полезные сообщения:

- `ASYNC_QUEUE: reply_channel=... не найден (id=...)` — ошибка
  конфигурации reply-канала.
- `ASYNC_QUEUE: ReplyChannel.send failed (id=...)` — не удалось
  доставить результат (см. trace в логах).

### Health-check Redis-broker

```bash
redis-cli LLEN taskiq                # длина очереди
redis-cli KEYS "taskiq:result:*"     # незабранные результаты
```

## Известные ограничения

- **DEFERRED режим** Invoker'а использует APScheduler, а не TaskIQ
  (см. `_invoke_deferred`). Они независимы.
- **Reply-канал `api`** (memory polling-store) **не виден** другим
  процессам — если worker и API-сервер раздельны, используйте
  `reply_channel=queue` с durable broker'ом.
- Сериализация `InvocationRequest` через `_serialize_request` →
  JSON-friendly dict; поля `payload` и `metadata` должны быть
  JSON-сериализуемы.

## Траблшутинг

| Симптом | Причина | Решение |
|---|---|---|
| `kiq` возвращается, но задача не выполняется | Backend=redis, worker не запущен | См. раздел 2 или 3 |
| `Reply channel 'api' is not configured` (worker logs) | Worker и API в разных процессах, нет shared state | Использовать `reply_channel=queue` или внешний broker для polling-store |
| `TaskIQ unavailable: ...` (Invoker logs) | `taskiq` не установлен | `uv add taskiq taskiq-redis` |
| Задача висит "in flight" после рестарта worker'а | Сетевые таймауты, Redis недоступен | Проверить `redis-cli ping`; задачи переотправятся согласно retry-политике |
