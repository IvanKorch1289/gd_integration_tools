"""Wiring-модули для компонентов W26.

Модули внутри пакета регистрируют реальные backend'ы в
``ResilienceCoordinator`` вместо stub'ов из ``registration.py``.

Структура:
    * ``audit_chain``       — ClickHouse → PG audit → JSONL  (W26.3)
    * ``antivirus_chain``   — ClamAV → HTTP-AV → skip+warn  (W26.3)
    * ``mq_chain``          — Kafka → Redis Streams → memory_mq  (W26.3)
    * ``cache_chain``       — Redis → Memcached → memory  (W26.4)
    * ``object_storage_chain`` — MinIO → LocalFS  (W26.4)
    * ``database_chain``    — PG → SQLite RO  (W26.4)
    * ``secrets_chain``     — Vault → .env+keyring  (W26.4)
    * ``mongo_chain``       — Mongo → PG jsonb  (W26.4)
    * ``search_chain``      — ES → SQLite FTS5  (W26.4)
    * ``smtp_chain``        — SMTP → file-mailer  (W26.4)
    * ``express_chain``     — Express → Email → Slack  (W26.4)
"""

from __future__ import annotations

__all__ = ()
