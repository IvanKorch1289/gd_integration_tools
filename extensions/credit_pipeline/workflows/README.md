# AI Workflow Examples (Sprint 12 K4 W1)

Три production-ready примера workflow для extensions/credit_pipeline:

| Workflow | Файл | Назначение |
|---|---|---|
| RAG-augmented Saga | `rag_augmented_saga.workflow.yaml` | Credit risk decision с RAG (legal docs) + saga compensation. |
| Multi-Agent Supervisor | `multi_agent_supervisor.workflow.yaml` | Loan approval через supervisor LLM + 3 параллельных specialist agents. |
| Code-Interpreter Loop | `code_interpreter_loop.workflow.yaml` | Data analysis цикл LLM → e2b sandbox → eval → repeat. |

## Развёртывание

```bash
# Импорт всех 3
for f in extensions/credit_pipeline/workflows/*.workflow.yaml; do
    python manage.py workflow import "$f"
done

# Dry-run проверка
python manage.py workflow dryrun --file extensions/credit_pipeline/workflows/rag_augmented_saga.workflow.yaml
```

## Feature flags

* `ai_workflow_examples_enabled` (default-OFF; зависит от `extensions_credit_workflow=True`).
* `ai_workflow_cost_estimation_enabled` (default-ON) — позволяет
  cost-estimator анализировать LLM-стоимость activities (`model_id` +
  `estimated_tokens`).
* `workflow_yaml_round_trip` (default-OFF) — для импорта YAML декларации.

## Стоимость (estimated через K4 W2 cost estimator)

| Workflow | Total tokens | Models | Estimated USD |
|---|---|---|---|
| RAG saga | ~6000 | sonnet-4-6 + embed | $0.018 |
| Multi-agent | ~22500 | opus-4-7 ×2 + sonnet ×3 + haiku | $0.190 |
| Code-interpreter loop | ~10000 | opus-4-7 + sonnet | $0.067 |

Стоимости пересчитываются автоматически через `LLMModelPricing` registry
+ env override.

## Activity binding

Все activities ссылаются на functions в `services.ai.*`. Реализация
функций — отдельный wave (вне S12 K4 W1 scope). Workflow YAML — это
**декларация**, она не требует физического кода для парсинга и dry-run.

При фактическом запуске Temporal вернёт ``UnknownActivity`` для
несуществующих handler'ов — для S12 это OK (декларативный пример).
