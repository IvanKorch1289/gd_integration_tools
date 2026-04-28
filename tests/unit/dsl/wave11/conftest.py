"""Bootstrap для unit-тестов DSL Wave 11 (audit + scan_file).

Общий env-bootstrap (включая REDIS_*) вынесен в ``tests/unit/conftest.py``.
Специфики нет: lazy-импорты ``ImmutableAuditStore`` / ``create_antivirus_backend`` /
``s3_client`` мокаются в самих тестах через ``patch`` на module-level.
"""

from __future__ import annotations
