# Фаза G3 — Hardening + observability final

* **Статус:** done (scaffolding + PII filter)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** G2

## Выполнено

- `src/infrastructure/observability/__init__.py` — public API.
- `pii_filter.py` — `redact_for_observability()`: email/phone/card/
  passport/inn замена перед отправкой в metrics/logs/traces.
- Уже существующие модули: correlation, metrics, otel_auto,
  sentry_init, tracing.

SLO-definitions, alertmanager rules, runbooks — уже в `docs/alerts/`
и `docs/grafana/`. OTLP OTEL, Sentry — интегрированы (pyproject).

## Definition of Done

- [x] PII filter для всех observability streams.
- [x] Correlation + tracing + metrics + sentry уже существуют.
- [x] `docs/phases/PHASE_G3.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (G3 → done).
