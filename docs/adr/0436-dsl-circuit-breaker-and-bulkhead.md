# ADR-0436 — Circuit breaker + bulkhead для внешних вызовов DSL-процессоров

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0163 (CB-middleware), ADR-0383 (breaker policy), ADR-0429 (громкий провал)
* Затрагивает: `src/backend/dsl/engine/processors/_resilience.py`, `httpcallprocessor.py`, `sink_publish/{protocols,messaging}.py`

## Контекст

Фасады устойчивости существовали, но DSL-процессоры внешних вызовов
(`http_call`, `soap_call`, `grpc_call`, `ws_publish`, `mq_publish`) их не
использовали: отказ внешнего сервиса держал worker на полном таймауте шага,
конкурентные вызовы не ограничивались, каскад отказов не гасился.

## Решение

`guarded_external_call(name, call)`:
* **Circuit breaker** — именованный (`dsl:<processor>`) в общем реестре; пороги
  из HTTP-настроек (`circuit_breaker_max_failures`,
  `circuit_breaker_reset_timeout`); при открытом breaker'е вызов падает сразу
  (`CircuitOpen`). Отказом считается и **транспортное исключение, и HTTP 5xx**
  (ответ 5xx — валидный ответ API, поэтому он возвращается вызывающему, но
  учитывается breaker'ом; иначе CB не открывался бы на «upstream отвечает
  503»).
* **Bulkhead** — лимит одновременных вызовов (`DSL_BULKHEAD_MAX_CONCURRENT`,
  `DSL_BULKHEAD_WAIT_TIMEOUT`), при исчерпании — `BulkheadExhausted`.

## Последствия

* Отказ внешнего сервиса не блокирует пул воркеров: вызовы отклоняются быстро.
* Поведение деградирует корректно (fail-closed с явной причиной).
