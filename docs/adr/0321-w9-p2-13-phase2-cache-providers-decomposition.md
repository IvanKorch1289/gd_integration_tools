# ADR-0321 — W9 P2-13 Phase 2: `core/di/providers/cache.py` god-module → domain split + duplicate audit

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W9 (god-objects); V15 forbidden pattern «God-modules
  (>500 LOC)»; ADR-0320 (W9 P2-13 protocols split); S38 P1.2c (history);
  M2-#11 batch 7-19 (misattributed additions).

## Контекст

`src/backend/core/di/providers/cache.py` (868 LOC, top-2 god-module после
`dsl/builders/base/_protocols.py`) — содержит **89 функций** в 26 разных
concern-категориях, хотя имя говорит только о cache.

### История (per `__init__.py` docstring)

- Wave 6.2 (pre-split): один файл `providers.py` с 114 функциями.
- S38 P1.2b: `providers.py` → `providers/_impl.py` + `__init__.py` (re-exports).
- **S38 P1.2c: `_impl.py` → 6 domain files** (`cache.py` 20 funcs, `db.py` 15,
  `http.py` 31, `ai.py` 12, `auth.py` 6, `workflow.py` 30).
- S36-W23: + `storage.py` (3 funcs).
- **M2-#11 batch 7-19 + accelerated batches** (S72-S87): НОВЫЕ providers
  добавлялись в `cache.py` вместо proper domain files → drift до 89 funcs.

### Audit дубликатов (Phase 2 discovery)

Сравнение с другими domain-файлами обнаружило **4 пары функций с ДУБЛИКАТАМИ**:

| Функция | `cache.py` реализация | `domain.py` реализация | Где правильная |
|---|---|---|---|
| `get_object_storage_provider` | `resolve_module("cache").get_object_storage()` | `resolve_module("storage.factory").get_object_storage()` | `storage.py` |
| `get_ai_sanitizer_provider` | `resolve_module("security.ai_sanitizer").get_ai_sanitizer` (no feature flag) | `feature_flags.PRESIDIO_PII_ENABLED` switch + `PresidioSanitizerAdapter`/`AIDataSanitizer` | `ai.py` |
| `get_smtp_client_provider` | `resolve_module("...").get_smtp_client` | `resolve_module("http").get_smtp_client` (HTTP домен) | `http.py` |
| `get_stream_client_provider` | `resolve_module("...").get_stream_client` | `resolve_module("http").get_stream_client` (HTTP/streaming) | `http.py` |

### Последствия дублей (runtime bug)

Каждый domain-модуль имеет свой **`_overrides: dict[str, Any] = {}`** (per
domain isolation per `__init__.py` docstring). Это означает:

1. `set_object_storage_provider(mock)` через `storage.set_object_storage_provider`
   → пишет в `storage._overrides`.
2. `get_object_storage_provider()` через `cache.get_object_storage_provider`
   → читает `cache._overrides` (пустой!) → резолвит через `cache` module →
   возвращает РЕАЛЬНЫЙ объект вместо mock.

**Test-injection broken** в любом тесте, который использует import-paths
через `cache` для функций, которые там дублируются.

**Feature-flag bypass** для `ai_sanitizer`: `cache.get_ai_sanitizer_provider`
не проверяет `PRESIDIO_PII_ENABLED` → Presidio sanitizer НЕ активируется,
даже если feature flag = True (для всех consumers, импортирующих через cache).

### Кто использует cache.py напрямую

`grep -rE "from src.backend.core.di.providers.cache"` → **142 import sites**
в `src/`, `tests/`, `extensions/`. Из них значительная часть для дубликатов:

```
src/backend/dsl/engine/processors/ai/sanitizepii_processor.py:103:
    from src.backend.core.di.providers.cache import get_ai_sanitizer_provider
                                              ↑ использует WRONG impl (no Presidio)
```

## Решение

### Phase 2A: Split на proper domains + back-compat shim

Переместить функции из `cache.py` в правильные domain-файлы. `cache.py`
остаётся как **back-compat re-export hub** (аналогично W2 P0-3 SagaLRA
Variant A pattern — ADR-0316).

**Target domain mapping**:

| Функции в cache.py | Целевой домен | Обоснование |
|---|---|---|
| `cache_invalidator`, `admin_cache_storage`, `response_cache`, `rag_cache` (8) | **остаются в `cache.py`** | canonical cache concerns |
| `redis_kv_client`, `redis_stream_client` (4) | **остаются в `cache.py`** | Redis = cache backend (по W4 P1-6) |
| `redis_client` (2) | **остаются в `cache.py`** | high-level Redis facade |
| `redis_lock_class` (2) | **новый `redis.py`** или **остаются** | lock = Redis-coordination, можно в cache |
| `slo_tracker` (2) | **новый `slo.py`** | observability/SLO concern |
| `health_aggregator` (2) | **новый `health.py`** | ops/health concern |
| `signature_builder` (2) | **новый `security.py`** или `auth.py` | HMAC signing = security |
| `httpx_client`, `http_client_typed`, `http_client_dependency` (6) | **уже в `http.py`** — удалить дубликаты | canonical HTTP |
| `reply_channel_class`, `sink_factory`, `*_sink_class` (10) | **уже в `workflow.py`** — удалить дубликаты | messaging/sinks = workflow |
| `object_storage` (2) | **уже в `storage.py`** — удалить дубликаты | canonical storage |
| `antivirus_*`, `record_antivirus_scan` (4) | **новый `security.py`** | AV = security concern |
| `immutable_audit_store_class` (2) | **новый `audit.py`** или `workflow.py` | audit = observability |
| `vault_*` (4) | **уже в `db.py` или `auth.py`** — проверить | secrets management |
| `telegram_bot`, `express_bot_*`, `record_express_message_sent` (6) | **уже в `notifications.py`** — проверить | messaging |
| `ai_sanitizer` (2) | **уже в `ai.py`** — удалить дубликат | canonical AI |
| `db_manager` (2) | **уже в `db.py`** — проверить | DB domain |
| `smtp_client` (2) | **уже в `http.py`** — удалить дубликат | HTTP/email |
| `stream`, `stream_client` (4) | **уже в `http.py`** — удалить дубликаты | streaming |
| `vector_store`, `token_registry` (4) | **уже в `ai.py`** — проверить | AI/ML |
| `dlq_*` (6) | **уже в `workflow.py`** или новый `dlq.py` | DLQ = workflow |
| `workflow_factory_module`, `notifications_module` (4) | **уже в `workflow.py`** — проверить | workflow |

### Phase 2B: Duplicate resolution strategy

Для каждой из 4 пар дубликатов:

1. **Audit runtime consumers**: определить какой import-path реально используется
   в production (через `dsl/processors`, `services/ai/...` vs `services/...`).
2. **Keep canonical** (правильная реализация), **delete wrong from cache.py**.
3. **Add re-export from cache.py** с `DeprecationWarning` для back-compat.

### Phase 2C: New domain files (if needed)

Если домен ещё не существует (slo, health, audit, security) — создать новый
файл с тем же pattern (`_overrides` per-domain + get/set_provider).

### Back-compat safety

- `from src.backend.core.di.providers.cache import get_X_provider` →
  продолжает работать через `__getattr__` или явные re-exports.
- `from src.backend.core.di.providers import get_X_provider` →
  уже работает через `__init__.py` который импортирует domain файлы.
- **Critical**: `from src.backend.core.di.providers.cache import
  get_ai_sanitizer_provider` → должно указывать на **canonical impl**
  в `ai.py`, не на buggy `cache.py` impl.

### Тесты

`tests/unit/core/di/test_w9_p2_13_phase2_cache_split.py` (новый):
- TestCacheCanonicalConcerns (5): cache-specific providers (cache_invalidator,
  response_cache, rag_cache, redis_*) остаются в cache.py.
- TestDuplicatesResolved (8): для каждой из 4 пар дубликатов — проверить
  что cache.py version идентична canonical (или удалена).
- TestAIFeatureFlag (3): `get_ai_sanitizer_provider` через cache.py должна
  respect PRESIDIO_PII_ENABLED (regression test для runtime bug).
- TestBackCompat (10): все 142 import-paths работают после split.

### Verification

```
compileall -q src/backend/core/di/providers/                        → exit 0
pytest tests/unit/core/di/                                          → все passed
pytest tests/unit/dsl/processors/ (тесты sanitizepii_processor и др.) → passed
ruff check --select F401,F841,F811,E9                               → All checks passed
```

## Альтернативы (отклонённые)

1. **Touch 142 import sites**: отклонено — большой diff, невозможно в одном
   atomic commit, high risk регрессий. Back-compat re-exports безопаснее.
2. **Keep cache.py as-is, добавить lint rule** (no new providers in cache.py):
   не устраняет existing дубликаты и runtime bugs.
3. **Auto-rename**: rename `cache.py` → `_legacy_cache.py` + alias — добавляет
   сложность без value (back-compat через __getattr__ достаточно).

## Связанные изменения

* **`src/backend/core/di/providers/cache.py`** — сокращается с 868 LOC до
  ~250 (только cache concerns + back-compat re-exports).
* **`src/backend/core/di/providers/slo.py`** — новый (SLO tracker).
* **`src/backend/core/di/providers/health.py`** — новый (health aggregator).
* **`src/backend/core/di/providers/security.py`** — новый (signature_builder +
  antivirus_*).
* **`src/backend/core/di/providers/audit.py`** — новый (ImmutableAuditStore).
* **Phase 2B**: 4 дубликата удалены из cache.py, canonical остаётся в proper
  domain (object_storage → storage.py, ai_sanitizer → ai.py, smtp_client →
  http.py, stream_client → http.py).
* **`tests/unit/core/di/test_w9_p2_13_phase2_cache_split.py`** — новый.
* **`docs/roadmap/PROGRESS_LEDGER.md`** — W9 P2-13 Phase 2 wave-memo.

Refs: MINIMAX W9, V15 forbidden pattern «god-modules», ADR-0316 (W2 P0-3
SagaLRA Variant A back-compat pattern), ADR-0320 (W9 P2-13 protocols split),
S38 P1.2c (initial split), M2-#11 batch 7-19 (drift), S24 W1 (Presidio
feature flag).
