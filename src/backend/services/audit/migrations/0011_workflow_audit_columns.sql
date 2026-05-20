-- Sprint 12 K1 W1 — расширение workflow_audit под полный event-set.
--
-- Добавляет 3 колонки для admin-инвентаря и SLA-аналитики:
--   * actor — User-Agent / Tenant API-key fingerprint / "manage.py" /
--             "dsl.cancel_workflow" и т.п. Помогает в audit-trail
--             отвечать "кто запросил cancel/signal".
--   * duration_ms — для SLA dashboard (S12 K2 W1). На событии
--             workflow.complete заполняется фактическое running-time.
--   * parent_workflow_id — для child-workflow / saga compensation
--             tree-view (S12 K3 W6).
--
-- skip-index по event_type (по плану) ускоряет агрегации вида
-- `countIf(event_type='workflow.complete')` в SLA query.
--
-- Idempotency: ALTER TABLE ADD COLUMN IF NOT EXISTS — повторное
-- применение миграции безопасно.

ALTER TABLE workflow_audit
    ADD COLUMN IF NOT EXISTS actor Nullable(String);

ALTER TABLE workflow_audit
    ADD COLUMN IF NOT EXISTS duration_ms Nullable(UInt64);

ALTER TABLE workflow_audit
    ADD COLUMN IF NOT EXISTS parent_workflow_id Nullable(String);

-- skip-index по event_type — ускоряет агрегацию по типам событий
-- (event_type уже LowCardinality, но skip-index добавляет coarse
-- block-skipping на больших партициях).
ALTER TABLE workflow_audit
    ADD INDEX IF NOT EXISTS idx_event_type event_type
    TYPE set(100) GRANULARITY 4;
