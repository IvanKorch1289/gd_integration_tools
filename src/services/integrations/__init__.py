"""Сервисный слой интеграций.

W24 добавил :mod:`import_service` — orchestration над ImportGateway.
"""

from src.services.integrations.import_service import ImportService, get_import_service

__all__ = ("ImportService", "get_import_service")
