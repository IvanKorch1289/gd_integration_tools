"""TDD: Cert file watcher + hot-reload (S171 M16).

При изменении/добавлении/удалении .pem/.crt файла в cert_watch_path
CertStore автоматически обновляется + уведомляет подписчиков.

Pattern (D237, D238 TDD discipline): RED → fix → GREEN.
"""
# ruff: noqa: S101
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCertFileWatcher:
    def test_instantiates(self) -> None:
        """CertFileWatcher создаётся с path + store."""
        from src.backend.infrastructure.security.cert_store.hot_reload import (
            CertFileWatcher,
        )
        with tempfile.TemporaryDirectory() as tmp:
            mock_store = MagicMock()
            watcher = CertFileWatcher(path=Path(tmp), store=mock_store)
            assert watcher.path == Path(tmp)
            assert watcher.store is mock_store

    def test_handles_pem_extension(self) -> None:
        """Watcher фильтрует только .pem и .crt файлы."""
        from src.backend.infrastructure.security.cert_store.hot_reload import (
            CertFileWatcher,
        )
        with tempfile.TemporaryDirectory() as tmp:
            watcher = CertFileWatcher(path=Path(tmp), store=MagicMock())
            # Метод _should_handle должен фильтровать
            assert watcher._should_handle(Path("test.pem")) is True
            assert watcher._should_handle(Path("test.crt")) is True
            assert watcher._should_handle(Path("test.txt")) is False
            assert watcher._should_handle(Path("test.key")) is False


class TestCertFileEvents:
    @pytest.mark.asyncio
    async def test_on_add_calls_store_set(self) -> None:
        """При добавлении .pem файла вызывается store.set()."""
        from src.backend.infrastructure.security.cert_store.hot_reload import (
            CertFileWatcher,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mock_store = AsyncMock()
            watcher = CertFileWatcher(path=tmp_path, store=mock_store)
            cert_path = tmp_path / "test.pem"
            cert_path.write_text("---PEM CONTENT---")
            await watcher._on_file_event(cert_path, "add")
            # store.set() должен быть вызван с cert_id = filename
            assert mock_store.set.await_count >= 1

    @pytest.mark.asyncio
    async def test_on_delete_calls_store_delete(self) -> None:
        """При удалении .pem файла вызывается store.delete()."""
        from src.backend.infrastructure.security.cert_store.hot_reload import (
            CertFileWatcher,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mock_store = AsyncMock()
            watcher = CertFileWatcher(path=tmp_path, store=mock_store)
            await watcher._on_file_event(tmp_path / "test.pem", "delete")
            assert mock_store.delete.await_count >= 1
