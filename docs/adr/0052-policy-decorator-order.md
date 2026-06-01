# ADR-0052 — Каноничный порядок композиции в `@policy`

* Статус: Accepted (Wave [s1/k2-2-policy-decorator], 2026-05-12)
* Связано с: ADR-0051, PLAN.md V16 §S1 К2.

## Контекст

DoD Sprint 1 К2 требует декоратор `@policy(circuit_breaker, rate_limit,
retry, cache)`, который применяет четыре resilience-патерна одновременно.
Порядок применения существенно влияет на семантику:

* кеш-хит должен короткозамыкать всё остальное (не тратить retry-/breaker-
  бюджет на повторное обращение к backend'у);
* retry должен сидеть **внутри** breaker'а — иначе breaker увидит логически
  «один и тот же» вызов как N отказов и быстро откроется;
* rate-limit должен предшествовать circuit-breaker'у, чтобы breaker не
  считал отбитые лимитером запросы как «нагрузку» на backend.

## Решение

Канонический порядок (outer → inner): **`cache → rate_limit →
circuit_breaker → retry → fn`**.

В коде это эквивалентно

```python
wrapped = cache(rate_limit(circuit_breaker(retry(fn))))
```

Композиция выполняется в `core/resilience/decorators.py::policy()` через
последовательное оборачивание (от inner к outer).

## Альтернативы

1. **`cache → retry → circuit_breaker → rate_limit → fn`** —
   retry внутри cache но снаружи breaker'а. Минусы: breaker открывается
   мгновенно при первой ошибке, теряем покрытие транзиентных сетевых
   глитчей retry-логикой.

2. **`circuit_breaker → cache → rate_limit → retry → fn`** —
   breaker снаружи кеша. Минусы: breaker open закрывает доступ даже к
   кешу. Семантически неверно: при отказе backend'а мы должны отдавать
   stale из кеша.

3. **Произвольный порядок по AST-конфигу** — slot-builder из YAML.
   Минусы: усложняет mental model, debug, и автоматический реестр
   декораторов в /docs.

## Последствия

* Каждый из четырёх wrap'ов опционален: `circuit_breaker=None` исключает
  слой полностью (не платим за no-op обёртку).
* При cache-hit retry/cb/rl не выполняются — это hot-path оптимизация.
* При rate-limit-exceeded `RateLimitExceeded` пробрасывается наверх и
  не «травит» breaker (rate-limit срабатывает раньше CB).
* `RetryPolicy.retry_on=()` (default) запускает retry на любую `Exception`,
  но `CircuitOpen` не должен попадать в retry — breaker уже разорвал цепь.
  В текущей `with_retry` это контролируется опцией `retry_on=` (см. tests).

## Проверка

* Unit-тесты `tests/unit/core/resilience/test_policy_decorator.py`:
  * cache-hit → fn не вызывается;
  * retry внутри breaker (3 attempts → 1 logical call для breaker'а);
  * rate-limit-exceeded → `RateLimitExceeded` без обращения к backend;
  * breaker open → `CircuitOpen` сразу, без retry;
* ADR должен поддерживаться синхронно с реализацией `policy()` —
  при изменении порядка обновить и ADR, и тесты.
