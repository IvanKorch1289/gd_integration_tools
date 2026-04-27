"""
Conftest для unit-тестов.

Unit-тесты не используют реальные БД или сетевые сервисы.
Все зависимости мокируются через pytest-mock или svcs_container из root conftest.
"""

from __future__ import annotations
