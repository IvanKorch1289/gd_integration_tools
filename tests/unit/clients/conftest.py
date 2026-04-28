"""Bootstrap для unit-тестов внешних клиентов.

Общий env-bootstrap вынесен в ``tests/unit/conftest.py``. Специфики нет.

``BaseExternalAPIClient`` импортирует ``HttpClient``, который использует
``http_base_settings`` (yaml) — покрывается восстановлением ROOT_DIR
в общем conftest. Прямого обращения к Redis при импорте нет.
"""

from __future__ import annotations
