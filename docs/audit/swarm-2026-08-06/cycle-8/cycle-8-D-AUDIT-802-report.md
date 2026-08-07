# cycle-8 / D-AUDIT-802 — WebhookRelay DLQ silent-loss (SERV-P0-003)

## Status

**DONE** — `feat(cycle-8): fix WebhookRelay DLQ silent-loss (3 вектора)`.

## Scope

`src/backend/services/integrations/webhook_relay.py` — фикс silent-loss в
DLQ по плану `cycle-4 phase-1/03-services.md` SERV-P0-003.

3 вектора атаки:

1. **unbounded `_memory_dlq`** — `list[DLQEntry] = []` рос без лимита
   при недоступности Redis.
2. **`_dlq_remove` swallows LREM errors** — `except Exception: logger.warning(...)`
   терял сбои `LREM` без видимого сигнала, записи оставались в DLQ навсегда.
3. **`dlq_retry` leaves dead entries** — `rule_not_found` записи (правило
   удалено) оставались в основной DLQ и блокировали retry-цикл.

## Fix

### (a) Bounded LRU queue

`_memory_dlq: list[DLQEntry]` → `_memory_dlq: deque[DLQEntry] = deque(maxlen=_DLQ_MAX_LEN)`.

`deque(maxlen=...)` автоматически вытесняет самые старые записи при
переполнении (FIFO eviction, не настоящий LRU, но bounded и lock-free).
Тот же cap (`_DLQ_MAX_LEN = 10_000`) что и Redis-LTRIM.

### (b) Explicit DLQ error handling + logger.error

`_dlq_remove` (Redis-branch): `logger.warning(...)` → `logger.error(...,
exc_info=True)`. Сообщение расширено — теперь явно говорит что запись
остаётся в очереди до следующей retry-попытки.

`_dlq_remove` (memory-fallback): переписан на
`self._memory_dlq = deque((e for e in self._memory_dlq if e.id != entry_id),
maxlen=_DLQ_MAX_LEN)` — сохраняет bounded cap при ребилде.

`except Exception` блоки в `_dlq_push`/`_dlq_all` НЕ тронуты — там
`logger.warning` корректен (Redis недоступен → fallback на memory).

### (c) TTL/dead-letter queue для dlq_retry

Добавлено поле `_dead_rule_dlq: deque[DLQEntry] = deque(maxlen=_DLQ_MAX_LEN)`.

`dlq_retry`: когда `rule is None` (правило удалено) — запись переносится
в `_dead_rule_dlq` и удаляется из основной DLQ через `_dlq_remove`.
Возвращаемый `dict` дополнен ключом `dead_rule_moved: int`.

`dlq_list`: добавлены `dead_rule_total` и `dead_rule_entries` для
инспекции перенесённых записей.

## Docstring marker

Все три точки помечены комментарием `# cycle-8/D-AUDIT-802:` +
docstring в class `WebhookRelay`. Русские docstrings не переводились.

## Tests

Создан `tests/unit/services/integrations/test_webhook_relay.py` — **9 tests PASSED**:

* `test_memory_dlq_is_bounded_deque` — deque(maxlen=...) контракт;
* `test_memory_dlq_evicts_oldest_on_overflow` — FIFO eviction;
* `test_memory_dlq_remove_rebuilds_bounded` — `_dlq_remove` сохраняет cap;
* `test_dlq_remove_logs_error_on_lrem_failure` — `error` + `exc_info`;
* `test_dead_rule_dlq_is_bounded_deque` — отдельная bounded очередь;
* `test_dlq_retry_rule_not_found_moves_to_dead_rule_queue` — перенос + маркер;
* `test_dlq_retry_no_dead_leaves_main_dlq_intact` — happy-path без регрессии;
* `test_dlq_list_includes_dead_rule_section` — новые поля в response;
* `test_dlq_retry_bounded_dead_rule_queue` — dead-rule eviction.

Все 30 тестов в `tests/unit/services/integrations/` PASSED (5 dadata +
16 facade + 9 webhook + и т.д.).

## Verify

* `bash tools/cycle-1-preflight.sh` → `[OK] layer checker — 0 new, 175 legacy`
  + `[OK] allowlist active IDs — 27` (gates 1-2). Docstring-gate — `0 missing
  docstrings in 0 files` (Files scanned: 840).
* `.venv/bin/python -m pytest tests/unit/services/integrations/test_webhook_relay.py -v`
  → 9 passed in 0.29s.
* `.venv/bin/python tools/check_layers.py --root src` →
  `Нарушений: 0 новых (файлов: 2278; baseline: 175 legacy)`.

## Diff stat

```
src/backend/services/integrations/webhook_relay.py | 83 +++++++++++++++++++---
tests/unit/services/integrations/test_webhook_relay.py | 246 +++++++++++++++++++++
2 files changed, 321 insertions(+), 8 deletions(-)
```

## Что НЕ тронуто

* Не модифицированы: `services/ai/gateway_adapter.py:128-129` (pre-existing residual),
  `services/ai/gateway/client.py` (modified by other agent), `s3.py`,
  `tools/blue_green.sh`, `uv.lock`, `.security/pip-audit-allowlist.txt`.
* Не удалялись `except Exception` блоки — все сохранили concrete handling
  (logger с контекстом).
* Не переписывались правки cycle 1..7 (HEAD остаётся стабильным).
* `gateway_adapter.py:128-129` — НЕ ТРОНУТ (pre-existing residual).
