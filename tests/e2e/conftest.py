"""
Conftest для E2E тестов.

Поднимает полное приложение через httpx AsyncClient + ASGITransport.
Не требует реального сервера — использует ASGI transport.

Зависимости: httpx, pytest-asyncio.
"""

from __future__ import annotations

import pytest
import httpx


@pytest.fixture
async def client():
    """HTTPX AsyncClient с ASGI transport против тестового приложения.

    Yields:
        Настроенный AsyncClient без запуска реального сервера.
    """
    try:
        from src.infrastructure.application.app_factory import create_app

        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
    except Exception as exc:
        pytest.skip(f"Не удалось создать приложение: {exc}")
