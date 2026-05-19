-- Таблица workflow_audit для хранения событий жизненного цикла workflow.
--
-- Движок: MergeTree с сортировкой по (tenant_id, created_at) — оптимально
--   для типичных запросов «все события тенанта за период».
-- PARTITION BY toYYYYMM(created_at) — месячные партиции для дешёвого TTL.
-- TTL: автоматическое удаление строк старше 90 дней.
--
-- LowCardinality(String) для event_type даёт ~3-5x ускорение фильтрации
-- (кардинальность <100: workflow.start, workflow.signal, workflow.cancel,
-- workflow.complete, workflow.fail, activity.* и т. п.).
--
-- payload — JSON-строка (String), валидация на уровне приложения.

CREATE TABLE IF NOT EXISTS workflow_audit
(
    event_id     String,
    event_type   LowCardinality(String),
    workflow_id  String,
    tenant_id    Nullable(String),
    payload      String,  -- JSON-encoded dict
    trace_id     Nullable(String),
    created_at   DateTime64(6, 'UTC')
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, created_at, event_id)
TTL toDateTime(created_at) + INTERVAL 90 DAY DELETE;
