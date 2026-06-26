"""TDD: Cert fallback chain (S171 M18, D248).

Fallback chain: vault → file → env_inline
- vault: HashiCorp Vault KV v2 (prod primary)
- file: cert dir с .pem файлами (dev/edge)
- env_inline: ENV var CERT_INLINE_<cert_id> с inline PEM (terminal fallback)

User directive: "продумай fallback логику для SSL Cert, если Hashicorp Vault
недоступен (для настроек есть .env, а для сертификатов ничего нет)".
+.env STRICTLY forbidden (per AGENTS.md permission rules).
"""
# ruff: noqa: S101
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFileCertBackend:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_file import (
            FileCertBackend,
        )
        with tempfile.TemporaryDirectory() as tmp:
            backend = FileCertBackend(path=Path(tmp))
            assert backend.path == Path(tmp)

    @pytest.mark.asyncio
    async def test_load_pem_file(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_file import (
            FileCertBackend,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "skb_api.pem").write_text("---BEGIN CERT---\nFAKE\n---END CERT---")
            backend = FileCertBackend(path=tmp_path)
            entry = await backend.get("skb_api")
            assert entry is not None
            assert "BEGIN CERT" in entry.pem

    def test_list_certs(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_file import (
            FileCertBackend,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "a.pem").write_text("---A---")
            (tmp_path / "b.crt").write_text("---B---")
            (tmp_path / "ignored.txt").write_text("---NOT PEM---")
            backend = FileCertBackend(path=tmp_path)
            names = sorted(backend.list_all())
            assert names == ["a", "b"]

    @pytest.mark.asyncio
    async def test_set_persists_to_disk(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_file import (
            FileCertBackend,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            backend = FileCertBackend(path=tmp_path)
            await backend.set("new_cert", pem="---NEW PEM---")
            await asyncio.sleep(0)
            assert (tmp_path / "new_cert.pem").exists()
            assert "NEW PEM" in (tmp_path / "new_cert.pem").read_text()


class TestEnvInlineCertBackend:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_env import (
            EnvInlineCertBackend,
        )
        backend = EnvInlineCertBackend()
        assert backend is not None

    @pytest.mark.asyncio
    async def test_load_from_env(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_env import (
            EnvInlineCertBackend,
        )
        with patch.dict(os.environ, {"CERT_INLINE_MYCERT": "---INLINE---"}):
            backend = EnvInlineCertBackend()
            entry = await backend.get("mycert")
        assert entry is not None
        assert "INLINE" in entry.pem

    @pytest.mark.asyncio
    async def test_returns_none_if_missing(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_env import (
            EnvInlineCertBackend,
        )
        with patch.dict(os.environ, {}, clear=True):
            backend = EnvInlineCertBackend()
            entry = await backend.get("nonexistent")
        assert entry is None


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_falls_through_to_file_when_vault_fails(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_file import (
            FileCertBackend,
        )
        from src.backend.infrastructure.security.cert_store.fallback import (
            FallbackCertBackend,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "skb_api.pem").write_text("---FROM FILE---")
            failing_vault = MagicMock()
            failing_vault.get = AsyncMock(return_value=None)
            file_backend = FileCertBackend(path=tmp_path)
            fallback = FallbackCertBackend(
                primary=failing_vault, secondary=file_backend
            )
            result = await fallback.get("skb_api")
        assert result is not None
        assert "FROM FILE" in result.pem

    @pytest.mark.asyncio
    async def test_falls_through_to_env_when_file_empty(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_env import (
            EnvInlineCertBackend,
        )
        from src.backend.infrastructure.security.cert_store.backend_file import (
            FileCertBackend,
        )
        from src.backend.infrastructure.security.cert_store.fallback import (
            FallbackCertBackend,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CERT_INLINE_FALLBACK": "---ENV---"}):
                empty_file = FileCertBackend(path=Path(tmp))
                empty_env = EnvInlineCertBackend()
                fallback = FallbackCertBackend(
                    primary=empty_file, secondary=empty_env
                )
                result = await fallback.get("fallback")
        assert result is not None
        assert "ENV" in result.pem
