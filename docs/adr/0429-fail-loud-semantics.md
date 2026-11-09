# ADR-0429 — «Громкая» семантика провала: ошибка не должна выглядеть как успех

* Статус: Accepted (2026-11-09, волна 27)
* Cycle: 187 (волна 27)
* Связан с:
  - ADR-0395 (идиомы вызовов в workflow-DSL),
  - ADR-0403/ADR-0408 (SLA/DLQ-политика workflow),
  - ADR-0414 (step-level audit workflow),
  - ADR-0424 (каталог шаблонов workflow),
  - ADR-0100 (прецедент: мёртвый/вводящий в заблуждение код либо удаляется,
    либо чинится)
* Затрагивает:
  - `src/backend/dsl/engine/processors/base.py` (`handle_processor_error`),
  - `src/backend/dsl/engine/execution_engine.py` (финальный статус),
  - `src/backend/dsl/engine/processors/sink_publish/generic.py` (`_store_result`),
  - `src/backend/infrastructure/sinks/{mq_sink,http_sink}.py` (retry),
  - `src/backend/infrastructure/workflow/runner.py` (`_execute_one`),
  - `src/backend/services/ai/usage_meter.py` (`estimate_usage`),
  - `src/backend/services/workflows/template_registry.py` (теги из YAML),
  - `src/backend/dsl/workflow/templates/guardrail_cost_budget.workflow.yaml`,
  - тесты: `tests/unit/dsl/engine/test_fail_loud_semantics_adr0429.py`,
    `tests/unit/infrastructure/workflow/test_runner_unexpected_error_adr0429.py`,
    `tests/unit/dsl/workflow/test_workflow_templates_catalog.py`,
    `tests/unit/infrastructure/sinks/test_http_sink.py`,
    `tests/unit/dsl/engine/processors/test_sink_publish.py`

---

## Контекст

Повторный аудит (3 агента: workflow-движок, эргономика DSL, отказоустойчивость)
нашёл системный класс дефектов: **ошибка фиксировалась, но не влияла на
исход** — маршрут/шаг выглядели успешными.

1. **Статус exchange'а.** `@handle_processor_error` (117 процессоров) ловил
   исключение и делал `exchange.set_error(...)` + `exchange.stop()` — **без**
   смены статуса. Статус оставался `processing`, а движок в финале перетирал
   его в `completed` (ветка «в trace нет записи `status=error`»). Итог: trace
   «ok», SLO-метрика `is_error=False`, `error` жил только в теле exchange'а.
2. **Неуспешная публикация.** `_store_result` (все sink-процессоры: MQ, HTTP,
   S3, файл, NATS, MQTT, gRPC, SOAP, e-mail, SMS, webhook, WS) сохраняла
   `ok=False` в свойства exchange'а, но **не проваливала шаг**: маршрут
   завершался успешно, сообщение терялось без DLQ и компенсации.
3. **Retry в sink'ах.** `HttpSink.send`/`MqSink.send` помечены
   `@with_retry(...)`, но внутри стоял broad `except Exception → ok=False`:
   исключение не доходило до retry-декоратора, поэтому 3–5 попыток не
   выполнялись **ни разу** — первая попытка теряла сообщение. Для HTTP
   дополнительно `retry_on=(ConnectionError, TimeoutError, OSError)` не
   покрывал `httpx.TransportError` (не наследует `OSError`).
4. **Workflow-runner.** Неожиданное исключение в `_execute_one` только
   логировалось: инстанс оставался в статусе `running`, backup-poll
   подхватывал его снова и снова (счётчик попыток рос), DLQ и компенсация не
   срабатывали.
5. **Шаблон `guardrail_cost_budget`** падал с `GuardrailValueTypeError`:
   guardrail без `target` брал последний output шага (строку ответа агента) —
   non-numeric → fail-closed. Шаблон нельзя было использовать как стартовую
   точку.
6. **Теги шаблонов.** `WorkflowTemplateRegistry` парсил теги из маркера
   ``Template tags:`` в description, а ADR-0424 перенёс их в YAML-поле `tags:`
   → поиск по тегам не работал (у всех 18 шаблонов теги были пусты).

---

## Решение

1. **Ошибка процессора = `failed`.** `handle_processor_error` вызывает
   `exchange.fail(...)` (статус + текст), а движок не перетирает уже
   установленный `failed` в `completed`.
2. **Неуспешная публикация = провал шага.** `_store_result` (единая точка для
   всех sink-процессоров) при `ok=False` вызывает `exchange.fail(...)` +
   `exchange.stop()` → шаг уходит в retry/DLQ, а не «успех с флагом».
3. **Transient-ошибки доходят до retry.** В `HttpSink`/`MqSink` broad-except
   разделён на retryable (`ConnectionError`/`TimeoutError`/`OSError`, для
   HTTP — ещё и `httpx.TransportError`) и остальные: retryable **пробрасываются**
   (иначе retry мёртв), остальные возвращают `ok=False`. Контракт sink'а:
   transport-ошибка → исключение после исчерпания попыток; прочие → `ok=False`.
4. **Runner переводит инстанс в `failed`** при неожиданном исключении (с
   текстом ошибки). Если и это не удалось (БД недоступна) — инстанс подхватит
   backup-poll после восстановления БД.
5. **Шаблон `guardrail_cost_budget`** получает числовой источник
   (`call_function` → `usage_meter:estimate_usage` → `{"tokens", "cost_usd"}`)
   и явные `target`-ы (`usage.tokens`, `usage.cost_usd`). Добавлен гейт:
   **каждый** guardrail-шаг шаблона обязан иметь `target`.
6. **Теги шаблонов читаются из YAML** (`tags:`), fallback на старый маркер в
   description сохранён.

---

## Последствия

* Провал шага теперь виден в статусе, trace, SLO-метрике и DLQ — «тихого»
  успеха больше нет. Поведение маршрутов с падающим процессором меняется с
  «200 + тело с ошибкой» на явную ошибку маршрута (проверено тестами).
* Retry в HTTP/MQ sink'ах действительно выполняется (3/5 попыток) — это
  увеличивает время удержания соединения при отказе внешней зависимости.
* Контракт `Sink.send` разделён: transport-ошибка → исключение, прочие →
  `ok=False`. Код, вызывающий sink напрямую (вне DSL), должен обрабатывать
  исключение (все DSL-процессоры — через `handle_processor_error`).
* `estimate_usage` — новая публичная функция `services.ai.usage_meter`
  (без optional-зависимостей, детерминированная эвристика токенов).
* Остаток аудита (owner-задачи): `memory.reflect` и `workflow.checkpoint.put`
  не зарегистрированы как activity (2 шаблона падают в рантайме); линтер
  `*.workflow.yaml` отсутствует; `workflow_setup.py` глотает ошибку загрузки
  workflow (warning вместо error); компенсация откатывает разные шаги в
  Temporal- и pg-runner'е (индекс в списке выполненных vs всех forward-шагов);
  idempotency_key не доходит до внешнего вызова (повтор после падения
  worker'а может продублировать платёж/событие); bulkhead/CB не подключены к
  DSL-процессорам.
