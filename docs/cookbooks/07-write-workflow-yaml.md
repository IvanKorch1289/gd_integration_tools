# Cookbook 07: Как написать workflow на YAML

**ADR**: [ADR-0424](../adr/0424-workflow-template-catalog.md) (каталог шаблонов),
[ADR-0433](../adr/0433-workflow-spec-linter-and-internal-activities.md) (линтер спецификаций),
[ADR-0398](../adr/) (activity-имена = зарегистрированные actions ядра)
**Статус**: Production-ready
**Время**: ~10 минут от шаблона до запуска

## Use Case

Нужно описать бизнес-процесс (сага, HITL, pipeline с LLM, polling внешнего API)
декларативно, без Python-кода: шаги, порядок, таймауты, SLA, компенсации.

## Solution

Workflow = YAML-файл `*.workflow.yaml` + шаблон из каталога
`src/backend/dsl/workflow/templates/` (18 готовых стартовых точек).

## Recipe

### Step 1. Возьмите шаблон

```bash
ls src/backend/dsl/workflow/templates/
# agent_pipeline.workflow.yaml        — LLM-агент + guardrail + reflection
# saga_compensation_map.workflow.yaml — сага с картой компенсаций
# hitl_approval_chain.workflow.yaml   — согласование человеком
# sla_retry_policy.workflow.yaml      — SLA + политика повторов
# checkpoint_continue_as_new.workflow.yaml — чекпойнт + continue_as_new
# call_function_ingest.workflow.yaml  — вызов функции по контракту
```

### Step 2. Скопируйте в свой плагин

```bash
mkdir -p extensions/<plugin>/workflows
cp src/backend/dsl/workflow/templates/saga_compensation_map.workflow.yaml \
   extensions/<plugin>/workflows/my_flow.workflow.yaml
```

Файл авто-регистрируется при старте приложения (`workflow_setup.py`): роут
`routes/<plugin>/<имя_файла>`. Битый файл **логируется как ERROR** с путём и
причиной (ADR-0434) и виден в `get_workflow_load_failures()`.

### Step 3. Проверьте спецификацию (до запуска!)

```bash
python tools/check_workflow_specs.py
# Workflow-спецификации: OK (проверено 22)
```

Линтер ловит: невалидные поля шага, опечатки в именах activity, незарегистрированные
compiler-activity (`memory.reflect`, `workflow.checkpoint.put`). В CI — шаг
`Workflow specs lint gate` в `.github/workflows/lint.yml`.

### Step 4. Проверьте компиляцию (dry-run)

```bash
.venv/bin/python manage.py workflow dryrun \
    --file extensions/<plugin>/workflows/my_flow.workflow.yaml
```

Dry-run компилирует спеку и резолвит activity **без** запуска workflow: видно
ранние ошибки (неизвестный шаг, отсутствующий activity).

### Step 5. Ключевые элементы спецификации

```yaml
name: my_flow
version: "1.0"
description: "Заявка → проверка → оплата"

steps:
  # activity: имя ЗАРЕГИСТРИРОВАННОГО action'а ядра (ADR-0398)
  - type: activity
    name: orders.create
    args:
      payload: "{{body}}"
    timeout_s: 30          # обязательный таймаут шага
    output_key: order      # результат доступен как {{order}}

  # call_function: 'module:fn' — прямая функция без action-реестра
  - type: call_function
    ref: src.backend.services.ai.usage_meter:estimate_usage
    args:
      messages: ["{{order}}"]
    timeout_s: 10
    output_key: usage

  # guardrail: сравнивает ТОЛЬКО число → нужен явный target (ADR-0429)
  - type: guardrail
    rule: max_cost_usd
    threshold: 0.5
    target: usage.cost_usd
    on_exceed: fail
    output_key: cost_guard

  # saga: forward-шаги + шаги компенсации (позиционный маппинг,
  # откатываются только ВЫПОЛНЕННЫЕ шаги — ADR-0431)
  - type: saga
    forward:
      - type: activity
        name: orders.create
        timeout_s: 30
        output_key: order
      - type: activity
        name: billing.charge
        timeout_s: 60
        output_key: charge
    compensate:
      - type: activity
        name: billing.refund
        timeout_s: 60
      - type: activity
        name: orders.cancel
        timeout_s: 30
    output_key: saga_result

  # SLA: жёсткий бюджет инстанса (ADR-0403)
sla:
  hard_limit_s: 300
```

### Step 6. Запуск

```bash
# dev-профиль: workflow выполняется LiteTemporalBackend'ом
APP_PROFILE=dev_light .venv/bin/python manage.py run

# вызов workflow как роута
curl -X POST http://localhost:8000/api/v1/auto/routes/<plugin>/my_flow \
     -H 'Content-Type: application/json' -d '{"body": {...}}'
```

## Gotchas

| Симптом | Причина | Что делать |
|---|---|---|
| `ActivityNotRegisteredError` | activity не зарегистрирована в Worker'е | проверьте `tools/check_workflow_specs.py` и список action'ов |
| `GuardrailValueTypeError` | guardrail без `target` берёт нечисловой output | укажите `target:` (в т.ч. dot-path `usage.cost_usd`) |
| шаг завис | нет `timeout_s` | таймаут шага обязателен |
| повтор шага дублирует платёж | внешний вызов без `Idempotency-Key` | `http_call` пробрасывает ключ автоматически (ADR-0431); получатель обязан дедуплицировать по нему |
| компенсация откатывает не те шаги | разные движки | семантика выровнена (ADR-0431): откатываются только выполненные |
| файл не подхватился | битая спецификация | `workflow.auto_register FAIL` в логах (ERROR) + `get_workflow_load_failures()` |

## See Also

* ADR-0433 — линтер workflow-спецификаций и внутренние activity
* ADR-0424 — каталог из 18 шаблонов
* ADR-0429 — «громкая» семантика провала (ошибка шага = failed, а не «ok»)
* ADR-0431 — идемпотентность внешних вызовов и компенсации
* `src/backend/dsl/workflow/templates/` — каталог шаблонов
