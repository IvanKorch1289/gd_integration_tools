# ADR-0073 — RAGAS evaluation gate

* Статус: **Accepted** (S29 W3, 2026-05-26, gap-ai-6 closure).
* Связано с: ADR-0074 (RAG hybrid retrieval), ADR-0072 (PII production enforcement), PLAN.md S29 w3.
* Память: [[feedback_sprint29_ai_waves]].

## Контекст

Качество RAG-цепочек проекта (RAGService + HybridRAGSearch) не проверяется
автоматически при изменениях. Без CI-gate регрессии в retrieval / augment
остаются незамеченными до production.

Требования к evaluator:
1. Четыре метрики: faithfulness / answer_relevancy / context_precision / context_recall.
2. Threshold gating — faithfulness < 0.8 блокирует CI (fail on regression).
3. Async wrapper — ragas sync API не должна блокировать event loop.
4. Graceful degradation — при отсутствии ragas/datasets evaluation пропускается
   (не падает CI).
5. Synthetic dataset 15-30 QA-пар.

## Решение

### Реализация

* `services/ai/eval/ragas_evaluator.py::RAGASEvaluator` — основной batch-evaluator.
* `services/ai/eval/ragas_evaluator.py::RAGASRecord` — входной dataclass
  (question, answer, contexts, ground_truth).
* `services/ai/eval/ragas_evaluator.py::DEFAULT_THRESHOLDS` — пороговые значения:
  * faithfulness ≥ 0.8
  * answer_relevancy ≥ 0.75
  * context_precision ≥ 0.7
  * context_recall ≥ 0.7

### CLI / CI gate

* `Makefile::ai-rag-eval` target — запуск evaluation локально.
* `.github/workflows/ai-rag-eval.yml` — nightly cron (ежедневно 03:00 UTC).
* PR-gate при изменениях `services/ai/` или `ai_policies/`.

### Async wrapper

`RAGASEvaluator.aevaluate()` оборачивает sync `ragas.evaluate()` через
`asyncio.to_thread()` — non-blocking для event loop.

### Graceful degradation

Если `ragas` или `datasets` недоступны (ImportError) — evaluator логирует
warning и возвращает пустой отчёт, не падая. Exit code = 0.

### Synthetic dataset

Synthetic dataset 15-30 QA-пар генерируется один раз и хранится в
`artifacts/ragas/` (首期). Refresh — вручную или отдельным make target.

## Альтернативы (отвергнуто)

* **Inspect AI вместо RAGAS** — Inspect AI специализирован на LLM judge, но
  RAGAS имеет специализированные RAG-метрики (context_precision/recall) и
  проще интегрируется. Inspect AI используется параллельно в
  `services/ai/eval/inspect_runner.py`.
* **DEEP-Eval** — SaaS-only, нарушает on-prem requirement.

## Verification

```bash
# Локально
make ai-rag-eval

# Ожидаемый результат: faithfulness ≥ 0.8, answer_relevancy ≥ 0.75,
# context_precision ≥ 0.7, context_recall ≥ 0.7 — PASS
# При ImportError: skip с warning, exit 0
```

## Consequences

### Positive

* CI-gate предотвращает регрессии RAG-качества в PR.
* Nightly evaluation даёт early-warning о degradation.
* Graceful degradation не блокирует CI при missing dependencies.

### Negative

* `ragas` + `datasets` — тяжёлые dependencies (~2 GB). Запускаются только
  в nightly или при explicit trigger, не на каждом commit.
* Synthetic dataset быстро устаревает при смене схемы данных — нужен
  periodic refresh workflow.

## Связи с другими ADR

* ADR-0074 — RAG hybrid retrieval (Block 3.4 Ragas CI gate как carryover).
* ADR-0072 — PII production enforcement (evaluation dataset не содержит PII).
