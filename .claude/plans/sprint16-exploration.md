# Sprint 16 GAP-Closure 2 — Exploration Report

**Дата**: 2026-05-20  
**Назначение**: Локализация 6 P0-задач перед реализацией  
**Статус**: READ-ONLY EXPLORATION

---

## L1-P0-1: DEADLOCK FIX (threading.RLock → asyncio.Lock)

### Местоположение
- **Файл**: `src/backend/services/schema_registry/registry.py`
- **Строки**: 68 (self._lock), 77/83/88/93/98 (with self._lock:)

### Текущая реализация
```python
# Строка 68
self._lock = threading.RLock()
# Строки 77, 83, 88, 93, 98: with self._lock: (5 методов)
```

### Требуемые изменения
1. Удалить `import threading` (строка 16)
2. Добавить `import asyncio`
3. Строка 68: `threading.RLock()` → `asyncio.Lock()`
4. Все 5 методов (register, get, list_kind, summary, clear) должны быть async
5. `with self._lock:` → `async with self._lock:`

### Импортёры (8 файлов)
```
- exporter_asyncapi.py, exporter_openapi.py, exporter_jsonschema.py
- event_schemas.py, populator.py, admin_schemas.py
- llm_structured.py, event_bus.py, lifecycle.py
```

### Оценка
- **Риск**: ВЫСОКИЙ (публичный контракт меняется на async)
- **Инвазивность**: 8 файлов требуют await-обновления
- **Часов**: 3-4
- **DoD**: async методы, no deadlock, tests pass

---

## L1-P0-2/3: SFTP + FTP Connection Pooling

### Текущая реализация
**Файл**: `src/backend/infrastructure/clients/transport/ftp.py`

- Клиент: aioftp
- SSL: `ssl.CERT_NONE` + `check_hostname=False` ❌ (V1 violation)
- Pooling: отсутствует (каждый call → новое соединение)
- SFTP: отсутствует

### Требуемые изменения
1. Заменить aioftp на asyncssh (`asyncssh` уже в pyproject.toml)
2. Реализовать SSHClientPool (max_size, idle_timeout, health_check)
3. Добавить SFTP-поддержку
4. Исправить SSL: `ssl.create_default_context()` + `CERT_REQUIRED`

### Оценка
- **Риск**: СРЕДНИЙ (замена клиента)
- **Инвазивность**: 1 файл + вызывающий код
- **Часов**: 4-5
- **DoD**: asyncssh pool, SFTP работает, SSL валиден

---

## L2-P0-1: Transactional Outbox

### Местоположение
```
- dispatcher.py (271 строк)
- core/messaging/outbox.py (Protocol)
- infrastructure/repositories/outbox.py
- infrastructure/database/models/outbox.py
```

### Текущее состояние
- Polling-based dispatcher
- Retry-loop per-event
- ❌ НЕ atomic: outbox event ≠ business data в одной transaction

### Требуемые изменения
- Advanced-Alchemy unit_of_work pattern
- Atomicity: business-entity + outbox event в одной session.begin()
- Обновить все call-sites (repositories)

### Оценка
- **Риск**: ВЫСОКИЙ (затрагивает DB transactions)
- **Инвазивность**: 3-4 файла
- **Часов**: 5-6
- **DoD**: atomic DB, E2E test, no dual-write inconsistencies

---

## L3-P0-1: OTel OTLP Metrics Exporter

### Файл
`src/backend/infrastructure/observability/otel/setup.py`

### Текущее состояние
- ✅ Spans (OTLPSpanExporter)
- ❌ Metrics (отсутствует MeterProvider, OTLPMetricExporter)

### Требуемые изменения
- Добавить MeterProvider + OTLPMetricExporter
- Регистрировать метрики: workflow activities, REST latency, business events

### Оценка
- **Риск**: НИЗКИЙ (additive)
- **Инвазивность**: 1-2 файла
- **Часов**: 2-3
- **DoD**: OTLP metrics видны в collectorе, tests pass

---

## L4-P0-1: pygls LSP Server

### Состояние
- pygls 2.0.0 уже в pyproject.toml
- Linter: `src/backend/dsl/cli/linter.py`
- LSP server: отсутствует

### Требуемые изменения
1. Создать `tools/dsl_lsp/server.py` (LanguageServer)
2. Validators.py (diagnostics + hover)
3. Handlers.py (did_open, did_change, did_save)

### Оценка
- **Риск**: НИЗКИЙ (новая функциональность)
- **Инвазивность**: 3 новых файла
- **Часов**: 3-4
- **DoD**: diagnostics work, hover+completion, VSCode integration

---

## L5-P0-1: Adaptive RAG Classifier

### Файл
`src/backend/services/ai/rag/strategy_selector.py`

### Текущее состояние (Sprint 11 K4 W3)
- ✅ AdaptiveStrategySelector реализирована
- ✅ Heuristic fallback + LRU cache
- ✅ Optional LLM classifier callback

### Требуемые расширения
1. Создать QueryClassifier (LLM-based, claude-3-haiku)
2. Интегрировать с AdaptiveStrategySelector
3. Feedback loop для dashboard (page 81)

### Оценка
- **Риск**: НИЗКИЙ (feature-flag + graceful fallback)
- **Инвазивность**: 1 новый + 1 обновить
- **Часов**: 2-3
- **DoD**: LLM classifier работает, feedback logируется, tests pass

---

## Summary

| P0 | Модуль | Файлы | Риск | Часов |
|---|---|---|---|---|
| L1-P0-1 | schema_registry | 8 | ВЫСОКИЙ | 3-4 |
| L1-P0-2/3 | FTP transport | 1+N | СРЕДНИЙ | 4-5 |
| L2-P0-1 | Outbox | 3-4 | ВЫСОКИЙ | 5-6 |
| L3-P0-1 | OTel metrics | 1-2 | НИЗКИЙ | 2-3 |
| L4-P0-1 | LSP | 3 новых | НИЗКИЙ | 3-4 |
| L5-P0-1 | RAG classifier | 1-2 | НИЗКИЙ | 2-3 |

**Итого**: ~20–25 часов

**Порядок**: L3 → L4 → L5 → L1 → L2 (риск возрастает)
