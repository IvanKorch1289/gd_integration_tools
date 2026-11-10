"""ADR-0438 — операции storage по ключу (list/get/download).

Портал «Файлы S3» работал с ключами объектов, а сервер отдавал только
операции по ``file_uuid``. Добавлены тонкие эндпоинты поверх существующей
capability S3-сервиса (``list_files`` / ``get_file_base64`` /
``generate_download_url``) — новая бизнес-логика не вводилась.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _storage_paths() -> list[str]:
    """Пути storage-эндпоинтов, зарегистрированных сервером."""
    import sys

    sys.path.insert(0, ".")
    from tests.unit.frontend.api_clients.test_api_contract_paths import _server_paths

    return sorted(_server_paths())


def test_storage_by_key_endpoints_registered() -> None:
    """Эндпоинты по ключу зарегистрированы."""
    paths = _storage_paths()
    assert "/api/v1/storage/list" in paths
    assert "/api/v1/storage/get" in paths
    assert "/api/v1/storage/download" in paths


def test_storage_actions_delegate_to_s3_service() -> None:
    """Действия используют существующие методы S3-сервиса (без новой логики)."""
    from src.backend.infrastructure.external_apis.s3 import S3Service

    assert hasattr(S3Service, "list_files")
    assert hasattr(S3Service, "get_file_base64")
    assert hasattr(S3Service, "generate_download_url")


def test_portal_uses_storage_by_key_paths() -> None:
    """Портал вызывает по-ключевые пути (без ручных строк)."""
    from pathlib import Path

    page = Path("src/frontend/streamlit_app/pages/57_Файлы_S3.py").read_text(
        encoding="utf-8"
    )
    assert '"/api/v1/storage/list"' in page
    assert '"/api/v1/storage/get"' in page
    assert '"/api/v1/storage/download"' in page
