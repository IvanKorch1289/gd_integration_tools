# Волна 27 (2026-11-09) — повторный аудит: «тихий успех» вместо отказа

Повторный аудит вехи «воркфлоу / DSL / отказоустойчивость / удобство»:
три агента (движок workflow, эргономика DSL, отказоустойчивость) + целевые
тесты. Найден системный класс: **ошибка фиксировалась, но не влияла на исход** —
шаг/маршрут выглядели успешными.

ADR: `docs/adr/0429-fail-loud-semantics.md`.

---

## 1. Что закрыто кодом (ADR-0429)

| Дефект | Было | Стало |
|---|---|---|
| Ошибка процессора DSL (117 процессоров) | `exchange.set_error()` без смены статуса → движок перетирал в `completed`; trace «ok», SLO `is_error=False` | `exchange.fail()` → статус `failed`, статус не перетирается |
| Неуспешная публикация (все sink-процессоры: MQ/HTTP/S3/file/NATS/MQTT/gRPC/SOAP/e-mail/SMS/webhook/WS) | `ok=False` уходил в свойства exchange'а, маршрут завершался успешно, сообщение терялось без DLQ | `_store_result` проваливает шаг (`exchange.fail` + `stop`) |
| Retry в sink'ах | broad `except Exception → ok=False` внутри `@with_retry` → 3–5 попыток не выполнялись ни разу; для HTTP `retry_on` не покрывал `httpx.TransportError` | transient-ошибки пробрасываются в retry-декоратор; `httpx.TransportError` добавлен в `retry_on` |
| Workflow-runner | неожиданное исключение только логировалось → инстанс навсегда `running`, backup-poll по кругу, DLQ/компенсация не срабатывали | инстанс переводится в `failed` с текстом ошибки (если БД недоступна — подхватит backup-poll) |
| Шаблон `guardrail_cost_budget` | падал с `GuardrailValueTypeError` (guardrail брал нечисловой output агента) | числовой источник `usage_meter:estimate_usage` + явные `target: usage.tokens` / `usage.cost_usd`; гейт «у guardrail-шага есть `target`» |
| Теги шаблонов | `WorkflowTemplateRegistry` читал маркер ``Template tags:`` из description, а ADR-0424 перенёс теги в YAML → у всех 18 шаблонов теги пусты, поиск по тегам не работает | теги читаются из YAML-поля `tags:` (fallback на маркер сохранён) |
| ruff-гейт `src/` | 5 pre-existing ошибок → `make lint` красный | зелёный |

Новые тесты: `tests/unit/dsl/engine/test_fail_loud_semantics_adr0429.py` (2),
`tests/unit/infrastructure/workflow/test_runner_unexpected_error_adr0429.py` (2),
гейт guardrail-`target` в `test_workflow_templates_catalog.py`,
контракт retry в `test_http_sink.py`, контракт `ok=False` в `test_sink_publish.py`.

## 2. Что осталось открытым

Реестр — `docs/roadmap/OWNER_TASKS.md` §16 (10 пунктов). Ключевые:

1. `memory.reflect` и `workflow.checkpoint.put` не зарегистрированы как activity
   → 2 шаблона падают в рантайме (high).
2. Компенсация откатывает разные шаги в Temporal- и pg-runner'е (индекс в
   списке **выполненных** vs **всех** forward-шагов) — high, нужно решение
   владельца по семантике.
3. `idempotency_key` не доходит до внешнего вызова → падение worker'а после
   успешного внешнего эффекта может продублировать платёж/событие — high,
   нужно решение владельца (политика idempotency на стороне получателя).
4. Линтер `*.workflow.yaml` отсутствует; `workflow_setup.py` глотает ошибку
   загрузки workflow; `bulkhead`/`CB` не подключены к DSL-процессорам;
   `core/api` не экспортирует примитивы устойчивости (в AGENTS.md заявлены
   «17 primitives»); нет cookbook'а «как написать workflow YAML».

## 3. Регрессия

| Прогон | Результат |
|---|---|
| `tests/unit` (волна 27, полный) | см. лог `.run/wave13-logs/reg_final_27.txt` |
| `tests/unit/dsl/engine/` | 2929 passed (после фикса статуса exchange) |
| `tests/unit/infrastructure/sinks/` | 137 passed (после разблокировки retry) |
| `tests/unit/infrastructure/workflow/` | 243 passed (после терминального перехода runner'а) |
| `tests/unit/dsl/workflow/` (каталог шаблонов) | 27 passed (включая гейт guardrail-`target`) |
| ruff `src/` | All checks passed |
