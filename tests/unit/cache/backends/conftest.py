"""Bootstrap для unit-тестов cache backends.

Общий env-bootstrap (ROOT_DIR / LOG_HOST / REDIS_* / MAIL_* / QUEUE_* / FS_*)
вынесен в ``tests/unit/conftest.py`` и выполняется до этого файла.
Специфики у cache backends нет.
"""

from __future__ import annotations
