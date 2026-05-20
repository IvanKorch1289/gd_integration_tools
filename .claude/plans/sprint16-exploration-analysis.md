# Sprint 16 GAP-Closure 2 — Детальный анализ P0 задач

**Дата**: 2026-05-20  
**Статус**: Plan Only (Exploration Complete)  

---

## РЕЗЮМЕ АНАЛИТИКИ

Sprint 16 закрывает **7 P0 + 5 P1 задач**. Все 6 P0 находятся в реальном коде. **Ни одна не требует крупной архитектурной переделки** — это технический долг и узкие фиксы.

**Объём**: ~1500–2000 LOC  
**Сложность**: 🟡 СРЕДНЯЯ (5 простых + 1 требует аудита)  
**Parallelizable**: ✅ 5 из 6 P0 независимы  

---

## P0 ЗАДАЧИ: ДЕТАЛЬНЫЙ АНАЛИЗ

### L1-P0-1 DEADLOCK FIX: schema_registry async-lock migration

#### Файл & Метрика  
- **Путь**: `src/backend/services/schema_registry/registry.py` (116 LOC)
- **Проблема**: `threading.RLock()` → `asyncio.Lock()` + 5 методов → async

#### Lock-блоки (все 5 методов)
```python
Линия 77:  def register(entry: SchemaEntry) → with self._lock:
Линия 83:  def get(kind, name) → with self._lock:
Линия 88:  def list_kind(kind) → with self._lock:
Линия 93:  def summary() → with self._lock:
Линия 98:  def clear(kind) → with self._lock:
```

#### Импортёры (9 файлов) — RISK ASSESSMENT
| Файл | Метод | Context | Риск |
|------|-------|---------|------|
| `services/schema_registry/populator.py` | `register()` | **Sync** (lifespan) | 🟢 Low |
| `services/schema_registry/exporter_asyncapi.py` | `list_kind()` | **Sync** (export) | 🟢 Low |
| `services/schema_registry/exporter_openapi.py` | `list_kind()`, `get()` | **Sync** (export) | 🟢 Low |
| `services/schema_registry/exporter_jsonschema.py` | `list_kind()`, `get()` | **Sync** (export) | 🟢 Low |
| `services/schema_registry/event_schemas.py` | `register()`, `get()` | **Sync** (schema def) | 🟢 Low |
| `infrastructure/clients/messaging/event_bus.py:120` | `get(SchemaKind.EVENT)` | **Async** (publish) | 🔴 **HIGH** |
| `dsl/engine/processors/llm_structured.py:215` | `get(SchemaKind.PROCESSOR)` | **Async** (processor) | 🔴 **HIGH** |
| `entrypoints/api/v1/endpoints/admin_schemas.py` | `list_kind()`, `summary()` | **Sync** (FastAPI) | 🟢 Low |
| `plugins/composition/lifecycle.py:810` | `register()` | **Sync** (lifespan) | 🟢 Low |

**РИСК**: 2 async call-sites (event_bus, llm_structured) вызывают registry синхронно в async-контексте → потенциальный deadlock.

#### Решение
1. Строка 68: `self._lock = threading.RLock()` → `asyncio.Lock()`
2. Все 5 методов: `async def` + `async with self._lock:`
3. Найти call-sites, добавить `await`

#### Оценка усилий
- **registry.py**: 10 строк правок
- **Call-sites**: ~40 строк (2 async + 1-2 sync обёртки)
- **Итого**: ~50 LOC

#### DoD критерий
✅ `asyncio.Lock` в registry; grep verify 0 `threading.RLock` в async-коде

---

### L1-P0-2/3: SFTP + FTP Connection Pooling через asyncssh/aioftp

#### Файлы & Метрика
| Файл | LOC | Статус |
|------|-----|--------|
| `infrastructure/clients/transport/ftp.py` | 188 | ⚠️ NO POOLING + SSL BUG |
| `infrastructure/clients/transport/sftp.py` | 163 | ⚠️ NO POOLING |
| `infrastructure/clients/transport/pool.py` | NEW | Требуется |

#### Текущие баги
1. **FTP SSL (строки 53–54, 84–85)**:
   ```python
   ssl_context.check_hostname = False      # ← V1 VIOLATION
   ssl_context.verify_mode = ssl.CERT_NONE # ← V1 VIOLATION
   ```
   Должно: `ssl.create_default_context()`

2. **Pooling**: 0 переиспользования соединений (на каждый call — новое)

3. **Reliability**: Нет retry, reconnect, health-checks

#### Зависимости в pyproject.toml
```
Строка 563: "aioftp"       ✅ уже есть
Строка 566: "asyncssh"     ✅ уже есть
```

#### Решение (архитектурное)
1. **Новый файл**: `infrastructure/clients/transport/pool.py` (~200 LOC)
   - `SFTPConnectionPool`: asyncssh.SSHClientConnection pool с idle-timeout 60s
   - `FTPConnectionPool`: aioftp Client pool
   - Auto-reconnect, health-checks (ping/stat)

2. **Обновить ftp.py**: (~50 LOC)
   - Использовать FTPConnectionPool вместо на-каждый-раз
   - Исправить SSL: только `ssl.create_default_context()`

3. **Обновить sftp.py**: (~50 LOC)
   - Использовать SFTPConnectionPool

4. **Тесты**: (~100 LOC, testcontainers)

#### Оценка усилий
- **Итого**: ~400 LOC (СРЕДНИЙ объём)

#### DoD критерий
✅ SFTP + FTP pool; reconnect auto; integration test с testcontainers

---

### L2-P0-1: Transactional Outbox (Advanced-Alchemy UoW)

#### Файл & Проблема
- **Путь**: `infrastructure/messaging/outbox/dispatcher.py` (340 LOC)
- **Проблема**: Business data write (TX1) → Outbox write (TX2) — **SEPARATE TXs** → orphan events при crash

#### Текущий код
```python
# В dispatcher'е есть logic для polling/delivery/retry
# НО: атомарность бизнес-данных + outbox event обеспечивает CALLER
```

#### Требуется
1. **Grep-audit**: Найти все places где пишутся business data + outbox event одновременно
   ```bash
   grep -rn "outbox.enqueue\|backend.enqueue\|OutboxEvent(" src/backend --include="*.py" \
     | grep -v test | grep -v "infrastructure/messaging"
   ```

2. **Обернуть в одну TX** (advanced-alchemy UoW):
   ```python
   async with session.begin():  # единая транзакция
       await orders_repo.create(order_dto)
       await outbox_repo.enqueue(OutboxEvent(...))
   ```

3. **Chaos-test**: kill DB между бизнес-write и outbox-write → 0 orphan events

#### Оценка усилий
- **Если call-sites unified**: 60–120 LOC
- **Если разбросано**: 500+ LOC

#### DoD критерий
✅ Outbox dropped-message rate = 0 в chaos-test (kill между business-write и outbox-write)

---

### L3-P0-1: OTel OTLP Metrics Export

#### Файл & Текущее состояние
- **Путь**: `infrastructure/observability/otel/setup.py` (148 LOC)
- **Текущее**: Только Traces (OTLPSpanExporter)
- **Требуется**: Добавить Metrics (OTLPMetricExporter)

#### Что нужно экспортировать
| Метрика | Тип | Назначение |
|---------|-----|-----------|
| `workflow_duration_histogram` | Histogram | Temporal activity latency |
| `rest_request_latency_histogram` | Histogram | FastAPI endpoint p95 |
| `rest_request_count_counter` | Counter | Request volume |
| `outbox_delivery_latency` | Histogram | Outbox event delivery time |

#### Решение
1. **Обновить setup.py** (~30 LOC):
   ```python
   from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
   from opentelemetry.sdk.metrics import MeterProvider
   from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
   ```

2. **Новый файл**: `infrastructure/observability/otel/metrics.py` (~50 LOC)
   - Создать instruments (histogram, counter)
   - Export функции

3. **Интеграция** (~80 LOC):
   - `entrypoints/middlewares/` → add metric collection
   - `infrastructure/workflow/` → add metric collection

#### Оценка усилий
- **Итого**: ~160 LOC

#### DoD критерий
✅ OTel Metrics visible в Grafana; workflow duration + REST p95 экспортируются

---

### L4-P0-1: pygls LSP Server для DSL

#### Файлы & Текущее состояние
| Компонент | Статус |
|-----------|--------|
| `src/backend/dsl/cli/linter.py` | ✅ Batch validator |
| `/tools/dsl_lsp/` | ❌ **НЕ СУЩЕСТВУЕТ** (требуется создать) |
| `pygls>=2.0.0` в pyproject.toml | ✅ Уже есть (строка 248) |

#### Решение
1. **Новый файл**: `/tools/dsl_lsp/server.py` (~150 LOC)
   ```python
   from pygls.server import LanguageServer
   
   server = LanguageServer("gd-dsl-lsp", "v1.0")
   
   @server.feature(TEXT_DOCUMENT_COMPLETION)
   async def completion(params):
       # Для route.toml + *.dsl.yaml
       ...
   
   @server.feature(TEXT_DOCUMENT_HOVER)
   async def hover(params):
       # Документация по процессорам
       ...
   
   @server.feature(TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
   async def diagnostics(params):
       # Вызвать linter.py → LSP diagnostics
       ...
   ```

2. **VSCode extension** (~50 LOC): `dsl-vscode-extension/extension.js` (minimal)

3. **Manage.py integration** (~30 LOC):
   ```bash
   manage.py dsl-lsp-server --port 8765
   ```

#### Оценка усилий
- **Итого**: ~230 LOC

#### DoD критерий
✅ pygls LSP запускается; VSCode extension подключается; completion работает на route.toml

---

### L5-P0-1: Adaptive RAG QueryClassifier (LLM-based динамический выбор strategy)

#### Файл & Текущее состояние
- **Путь**: `services/ai/rag/strategy_selector.py` (137 LOC)
- **Текущее**: Эвристическая классификация (линии 47–72)
- **Требуется**: LLM-based classifier для выбора dense/hybrid/hyde/multi_query

#### Текущая архитектура
```python
class AdaptiveStrategySelector:
    def __init__(self, cache_size=512, llm_classify=None):
        # llm_classify — optional callable для LLM-классификации
        # Если None — используется только эвристика
        self._llm_classify = llm_classify
```

#### Решение
1. **Новый класс**: `QueryClassifierLLM` в том же файле (~60 LOC)
   ```python
   class QueryClassifierLLM:
       """LLM-based query classifier через LiteLLM."""
       
       async def __call__(self, query: str) -> tuple[str, float]:
           # LiteLLM call к модели (например, claude-3-haiku)
           # Prompt: "Classify query as dense/hybrid/hyde/multi_query"
           # Extract strategy + confidence
           # Fallback на heuristics при error
   ```

2. **Lifespan integration** (~20 LOC):
   ```python
   classifier_llm = QueryClassifierLLM(
       model="claude-3-haiku-20240307",
       timeout=100  # ms per query (DoD#2)
   )
   selector = AdaptiveStrategySelector(llm_classify=classifier_llm)
   ```

3. **Benchmark script** (~50 LOC):
   - Accuracy comparison heuristic vs LLM (target +15%)

#### Оценка усилий
- **Итого**: ~130 LOC

#### Зависимость
- Требуется **LiteLLM** в pyproject.toml (проверить наличие)

#### DoD критерий
✅ Adaptive RAG QueryClassifier выбирает strategy динамически; bench accuracy +15%

---

## RISK ASSESSMENT СВОДКА

| P0 | Риск | Миграция | Parallelize |
|-----|------|----------|------------|
| L1-P0-1 | 🟢 Low | Direct + type-check | ✅ Да |
| L1-P0-2/3 | 🟡 Medium | Pool pattern + SSL fix + testing | ✅ Да |
| L2-P0-1 | 🔴 High | Requires grep-audit first | ✅ Да (after audit) |
| L3-P0-1 | 🟢 Low | Addition, not replacement | ✅ Да |
| L4-P0-1 | 🟡 Medium | New server + VSCode | ✅ Да |
| L5-P0-1 | 🟢 Low | LLM addition + fallback | ✅ Да |

---

## СУММАРНАЯ МЕТРИКА

| Аспект | Значение |
|--------|----------|
| **Общий LOC** | ~1500–2000 (все 6 P0 + 5 P1) |
| **New files** | ~6 (pool.py, metrics.py, server.py, classifier, ext.js, ...) |
| **Files modified** | ~15 |
| **Parallel teams** | 5 (K1–K5) |
| **Critical path** | L1-P0-1 → L1-P0-2/3 → L2-P0-1 → L3-P0-1 (~11–15 дней) |
| **Full sprint** | 6–8 недель (3 параллельных разработчика) |

---

## REQUIRED PRE-WORK

### 1. L2-P0-1 Grep Audit (CRITICAL)
```bash
grep -rn "outbox.enqueue\|backend.enqueue\|OutboxEvent(" \
  /home/user/dev/gd_integration_tools/src/backend --include="*.py" \
  | grep -v test | grep -v "infrastructure/messaging"
```

Результат → оценка усилий (60 vs 500 LOC)

### 2. L5-P0-1 Dependency Check
```bash
grep -n "litellm" /home/user/dev/gd_integration_tools/pyproject.toml
```

Если отсутствует → добавить в P1 список (L5-P1-1)

### 3. Backbone Commits (перед agent launches)
- L1-P0-1: Add asyncio.Lock scaffold
- L1-P0-2/3: Add pool.py + testcontainers compose
- L2-P0-1: Add unittest fixtures (after grep audit)
- L3-P0-1: Add metrics.py + setup.py skeleton
- L4-P0-1: Add tools/dsl_lsp/server.py skeleton
- L5-P0-1: Add QueryClassifierLLM scaffold

---

## ЗАКЛЮЧЕНИЕ

✅ **Все 6 P0 задач находятся в реальном коде и готовы к реализации**  
✅ **5 из 6 можно разрабатывать параллельно** (L2-P0-1 требует предварительного grep-audit)  
✅ **Архитектурный риск LOW** (узкие фиксы, не переделка)  
✅ **Объём СРЕДНИЙ** (~1500–2000 LOC всего)  

**Рекомендуемый next step**: Выполнить L2-P0-1 grep-audit и создать backbone commits для 5 команд.

