# AI Workflow Examples (Sprint 12 K4 W1)

Три примера workflow для extensions/credit_pipeline (декларации — с
привязкой к реальным actions, см. §Activity binding):

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

## Activity binding (ADR-0403, волна 21)

Activity-имена приведены к **реально существующим** targets: либо
зарегистрированный action ядра (`ai.chat`, `ai.run_agent`, `rag.search`,
`export.to_pdf`, `webhook.schedule`/`webhook.cancel`), либо
`module:fn`-ссылка на функцию расширения
(`extensions.credit_pipeline.services.clients.skb:fetch_result`,
`extensions.credit_pipeline.agents:scoring_agent`,
`extensions.credit_pipeline.agents:document_parser_agent`,
`extensions.credit_pipeline.agents:decision_agent`,
`extensions.credit_pipeline.functions.normalize:apply_rules`).

До ADR-0403 шаги ссылались на несуществующие activity (`receive_dataset`,
`llm_propose_code`, `execute_code_sandboxed`, `evaluate_results`,
`format_final_report`, `collect_loan_inputs`, `supervisor_dispatch`,
`risk_agent`, `compliance_agent`, `scoring_agent`, `consolidate_results`,
`final_decision`, `fetch_credit_data`, `rag_query_legal_policies`,
`llm_credit_decision`, `fund_account`, `refund_account`). После ADR-0398
build-time резолв (`collect_activities(declarations, validate=True)`)
роняет подъём Temporal-Worker'а со списком неизвестных имён.

Функции `services.ai.*`, на которые ссылались исходные декларации, в
репозитории не существуют — соответствующие шаги переведены на реальные
actions ядра. Точное соответствие «старое имя → новый target» — в шапке
каждого YAML-файла.

**Что осталось за реализацией** (owner-задачи, ADR-0403 §Открытое):
e2b-sandbox (код-интерпретатор), выделенные risk/compliance-агенты,
ledger-операции кредитного конвейера (fund/refund).
