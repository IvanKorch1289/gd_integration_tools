-- Таблица audit_events для хранения security/business audit trail.
--
-- Движок: MergeTree с партиционированием по месяцу (toYYYYMM).
-- Сортировка: (event_type, timestamp, event_id) — оптимально для
--   запросов «все события данного типа за период».
-- TTL: автоматическое удаление строк старше 90 дней.
--
-- LowCardinality(String) для event_type и severity даёт ~3–5x ускорение
-- фильтрации по этим полям при типичном кардинальности <1000 уникальных значений.
--
-- payload хранится как JSON-строка (String) — валидация на уровне приложения,
-- ClickHouse не навязывает схему payload для гибкости audit trail.

CREATE TABLE IF NOT EXISTS audit_events
(
    event_id    String,
    timestamp   DateTime64(6, 'UTC'),
    event_type  LowCardinality(String),
    tenant_id   Nullable(String),
    user_id     Nullable(String),
    route_name  Nullable(String),
    payload     String,  -- JSON-encoded dict
    severity    LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (event_type, timestamp, event_id)
TTL toDateTime(timestamp) + INTERVAL 90 DAY DELETE;
