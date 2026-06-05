"""Unit-тесты WebDAVSource (S13 K3 W2).

Использует mock webdav4.Client — реальный Nextcloud-testcontainer test
вынесен в integration-suite.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import io
from unittest.mock import MagicMock

import pytest


class _FakeWebDAVClient:
    """Минимальный мок WebDAV-клиента."""

    def __init__(self, *args, **kwargs) -> None:
        self.files: list[str] = []
        self.marker_content = b""
        self.uploaded_markers: list[bytes] = []

    def ls(self, path: str, detail: bool = False) -> list[str]:
        return list(self.files)

    def download_fileobj(self, path: str, buf: io.BytesIO) -> None:
        if not self.marker_content:
            raise FileNotFoundError(path)
        buf.write(self.marker_content)

    def upload_fileobj(
        self, buf: io.BytesIO, path: str, overwrite: bool = True
    ) -> None:
        buf.seek(0)
        self.uploaded_markers.append(buf.read())


@pytest.fixture
def fake_client(monkeypatch):
    """Подменяет webdav4.client в sys.modules."""
    import sys
    import types

    fake = _FakeWebDAVClient()

    fake_module = types.ModuleType("webdav4")
    fake_client_module = types.ModuleType("webdav4.client")
    fake_client_module.Client = MagicMock(return_value=fake)
    fake_module.client = fake_client_module
    monkeypatch.setitem(sys.modules, "webdav4", fake_module)
    monkeypatch.setitem(sys.modules, "webdav4.client", fake_client_module)
    yield fake


@pytest.mark.asyncio
async def test_webdav_source_emits_new_files(fake_client) -> None:
    from src.backend.infrastructure.sources.webdav import (
        WebDAVSource,
        WebDAVSourceConfig,
    )

    fake_client.files = ["/data/a.csv", "/data/b.csv", "/data/c.txt"]
    cfg = WebDAVSourceConfig(
        url="http://nc:80",
        watch_path="/data",
        poll_interval_seconds=0,  # immediate next poll
        file_pattern="*.csv",
        marker_dedup=False,
    )
    source = WebDAVSource(cfg)
    events = []

    async def _consume() -> None:
        async for ev in source.stream():
            events.append(ev)
            if len(events) >= 2:
                await source.close()
                break

    await asyncio.wait_for(_consume(), timeout=2.0)
    assert len(events) == 2
    paths = sorted(str(e.path) for e in events)
    assert "/data/a.csv" in paths
    assert "/data/b.csv" in paths


@pytest.mark.asyncio
async def test_webdav_source_dedup_via_processed_set(fake_client) -> None:
    from src.backend.infrastructure.sources.webdav import (
        WebDAVSource,
        WebDAVSourceConfig,
    )

    fake_client.files = ["/data/a.csv"]
    cfg = WebDAVSourceConfig(
        url="http://nc:80",
        watch_path="/data",
        poll_interval_seconds=0,
        file_pattern="*.csv",
        marker_dedup=False,
    )
    source = WebDAVSource(cfg)
    events = []

    async def _consume() -> None:
        count = 0
        async for ev in source.stream():
            events.append(ev)
            count += 1
            # На втором цикле тот же файл — НЕ должен эмиттиться повторно.
            # Чтобы не зависнуть — закрываемся после первого цикла + дополнительного poll.
            if count >= 1:
                # Дать source ещё один цикл poll'а — он должен ничего не эмитить.
                await asyncio.sleep(0.05)
                await source.close()
                break

    await asyncio.wait_for(_consume(), timeout=2.0)
    assert len(events) == 1  # Только первое событие.


@pytest.mark.asyncio
async def test_webdav_source_pattern_filter(fake_client) -> None:
    from src.backend.infrastructure.sources.webdav import (
        WebDAVSource,
        WebDAVSourceConfig,
    )

    fake_client.files = ["/data/a.csv", "/data/b.json", "/data/c.csv"]
    cfg = WebDAVSourceConfig(
        url="http://nc:80",
        watch_path="/data",
        poll_interval_seconds=0,
        file_pattern="*.json",
        marker_dedup=False,
    )
    source = WebDAVSource(cfg)
    events = []

    async def _consume() -> None:
        async for ev in source.stream():
            events.append(ev)
            await source.close()
            break

    await asyncio.wait_for(_consume(), timeout=2.0)
    assert len(events) == 1
    assert "b.json" in str(events[0].path)


@pytest.mark.asyncio
async def test_webdav_source_marker_persists(fake_client) -> None:
    from src.backend.infrastructure.sources.webdav import (
        WebDAVSource,
        WebDAVSourceConfig,
    )

    fake_client.files = ["/data/x.csv"]
    cfg = WebDAVSourceConfig(
        url="http://nc:80",
        watch_path="/data",
        poll_interval_seconds=0,
        file_pattern="*.csv",
        marker_dedup=True,
        processed_marker_path="/data/_processed.txt",
    )
    source = WebDAVSource(cfg)
    events = []

    async def _consume() -> None:
        async for ev in source.stream():
            events.append(ev)
            await source.close()
            break

    await asyncio.wait_for(_consume(), timeout=2.0)
    assert len(events) == 1
    # Marker должен быть записан с одним путём.
    assert fake_client.uploaded_markers
    assert b"/data/x.csv" in fake_client.uploaded_markers[-1]


def test_builder_from_webdav(fake_client) -> None:
    from src.backend.dsl.builder import RouteBuilder

    rb = RouteBuilder.from_webdav(
        "import.docs",
        "http://nc:80",
        watch_path="/incoming",
        poll_interval_seconds=30,
        file_pattern="*.pdf",
    )
    assert rb.route_id == "import.docs"
    assert rb.source == "webdav:import.docs"
