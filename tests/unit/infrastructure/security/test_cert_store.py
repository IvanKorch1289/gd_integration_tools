# ruff: noqa: S101
"""Smoke tests for cert_store (infrastructure/security/cert_store.py)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.backend.infrastructure.security.cert_store import CertEntry, MemoryCertBackend

# ── MemoryCertBackend: in-process backend ───────────────────────────


@pytest.mark.asyncio
async def test_memory_backend_get_missing() -> None:
    backend = MemoryCertBackend()
    result = await backend.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_memory_backend_save_and_get() -> None:
    backend = MemoryCertBackend()
    expires = datetime.now(tz=timezone.utc) + timedelta(days=30)
    entry = await backend.save(
        service_id="svc-1",
        pem="-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        expires_at=expires,
    )
    assert entry.service_id == "svc-1"
    assert entry.version == 1
    assert entry.pem.startswith("-----BEGIN")
    assert entry.fingerprint != ""

    fetched = await backend.get("svc-1")
    assert fetched is not None
    assert fetched.service_id == "svc-1"
    assert fetched.version == 1


@pytest.mark.asyncio
async def test_memory_backend_save_increments_version() -> None:
    backend = MemoryCertBackend()
    expires = datetime.now(tz=timezone.utc) + timedelta(days=30)

    e1 = await backend.save("svc", "pem1", expires)
    e2 = await backend.save("svc", "pem2", expires)
    e3 = await backend.save("svc", "pem3", expires)

    assert e1.version == 1
    assert e2.version == 2
    assert e3.version == 3


@pytest.mark.asyncio
async def test_memory_backend_save_with_metadata() -> None:
    backend = MemoryCertBackend()
    expires = datetime.now(tz=timezone.utc) + timedelta(days=30)
    # CertEntry may not have uploaded_by/description — only add ones it accepts
    entry = await backend.save("svc", "pem", expires, description="test cert")
    # uploaded_by may not be stored on the entry itself, only used for audit log
    assert entry.description == "test cert"


@pytest.mark.asyncio
async def test_memory_backend_list_expiring() -> None:
    backend = MemoryCertBackend()
    soon = datetime.now(tz=timezone.utc) + timedelta(days=2)
    far = datetime.now(tz=timezone.utc) + timedelta(days=365)

    await backend.save("soon", "pem1", soon)
    await backend.save("far", "pem2", far)

    cutoff = datetime.now(tz=timezone.utc) + timedelta(days=7)
    expiring = await backend.list_expiring(cutoff)
    assert len(expiring) == 1
    assert expiring[0].service_id == "soon"


@pytest.mark.asyncio
async def test_memory_backend_name() -> None:
    backend = MemoryCertBackend()
    assert backend.name == "memory"


# ── CertEntry dataclass ────────────────────────────────────────────


def test_cert_entry_construction() -> None:
    expires = datetime.now(tz=timezone.utc) + timedelta(days=30)
    entry = CertEntry(
        service_id="x", pem="pem", fingerprint="abc", expires_at=expires, version=1
    )
    assert entry.service_id == "x"
    assert entry.pem == "pem"
    assert entry.fingerprint == "abc"
    assert entry.version == 1


# Helper: keep asyncio import used
_ = asyncio
