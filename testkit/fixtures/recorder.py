"""Pytest-фикстура для HAR-рекордера с включённым маскированием секретов.

Назначение:
    Предоставляет ``har_recorder`` — готовый :class:`HARRecorder` с
    ``mask_secrets=True``. Также возвращает ``har_cassette_path`` —
    путь во временном каталоге pytest, куда тест может вызвать
    ``recorder.cassette.save(path)``. Каталог уникален для каждого
    теста и автоматически удаляется pytest после прогонa.

Пример::

    async def test_external_api(har_recorder, har_cassette_path, httpx_async_client):
        async with har_recorder.async_session(httpx_async_client) as recorder:
            await httpx_async_client.get("https://api.example.com/health")
        recorder.cassette.save(har_cassette_path)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from testkit.recorder import HARRecorder


@pytest.fixture
def har_recorder() -> HARRecorder:
    """Возвращает HAR-рекордер с маскированием секретов по умолчанию."""
    return HARRecorder(mask_secrets=True)


@pytest.fixture
def har_cassette_path(tmp_path: Path) -> Path:
    """Путь до файла кассеты в уникальном временном каталоге теста."""
    return tmp_path / "cassette.har.json"
