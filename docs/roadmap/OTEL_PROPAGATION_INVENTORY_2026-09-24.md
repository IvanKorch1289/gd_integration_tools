# OTEL-context propagation inventory — Saga/Temporal (v5 P3, 2026-09-24)

> Inventory per v5 §4 P3-12 «OTEL-context propagation сквозь Saga/Temporal».
> Evidence-first: grep/AST по слоям, числа — с текущего HEAD.

## 1. Что измерено

| Слой | Файлы | OTEL-span touchpoints (`start_as_current_span`/`get_tracer`) |
|---|---|---|
| DSL Saga (canonical) | `dsl/engine/processors/saga_lra.py` | **0** |
| DSL Saga (compat) | `dsl/processors/saga_lra_processor/` | 0 (grep `trace\|span` — нет) |
| Temporal runner/worker | `infrastructure/workflow/runner.py`, `worker.py` | **0** прямых |
| Workflow executor mixins | `executor/{eval,control_flow,sub_flow}_mixin.py`, `compensating_driver.py` | есть упоминания trace/inject/extract (уточнять при реализации) |
| HTTP-слой | `entrypoints/middlewares/otel_middleware.py`, `observability_v2/propagator.py` | ✅ span + SemanticContext inject/extract |
| АИ/memory | `services/jupyter/*`, `services/ai/*` | точечные (hub_run_orchestrator и др.) |

## 2. Вывод

Span-пропагация есть на HTTP-входе (OTel middleware + observability_v2
SemanticContext), но **сквозь Saga/Temporal шаги контекст не протягивается
на уровне DSL**: SagaLRA и Temporal runner/worker не создают child-span'ов и
не прокидывают trace-context в step/activity выполнение. Разрыв: трейсы шагов
саги/temporal-воркфлоу не связаны с входным trace — поиск причины инцидента по
trace_id обрывается на границе.

## 3. Рекомендация (для волны-владельца, ADR-level)

1. Tracer-обёртка шага: в `SagaLRA._run_step_with_deadline` и Temporal
   activity wrapper — `tracer.start_as_current_span("saga.step", context=extract(headers))`
   с атрибутами step/kind/correlation_id.
2. Temporal: использовать `temporalio.contrib.opentelemetry` interception
   (если temporalio-extra установлен) вместо ручной прокидки.
3. Contract-тест: span-relation parent/child между HTTP-span и saga-step-span
   (assert `span.parent.span_id == http_span_id` через mock tracer/processor).
4. Observability_v2 SemanticContext — уже умеет inject/extract заголовков;
   переиспользовать для MQ/Temporal headers, не изобретать второй формат.

Scope: ~2-3 точки монтирования + контракт-тесты; ADR не требуется
(observability, не меняет бизнес-семантику), но согласовать с волной
наблюдаемости.
