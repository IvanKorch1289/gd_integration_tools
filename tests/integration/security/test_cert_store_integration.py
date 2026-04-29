"""Интеграционные тесты CertStore (Wave 10.1).

Покрывает:

* :class:`PostgresCertBackend` через реальный Postgres (testcontainers).
  Если ``testcontainers`` не установлен или Docker недоступен — тесты
  пропускаются (``pytest.skip``).
* :class:`VaultCertBackend` через mock ``hvac.Client`` — реальный Vault
  не поднимается (см. решение в Wave 10.1: "только Postgres + mock Vault").
* Hot-cache + ``subscribe_updates`` уведомления.

Импорт ``cert_store`` отложенный — глобальные ``app_base_settings`` тянут
``config_profiles/dev.yml``, который при сборке тестов может быть недоступен.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


_TEST_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\n"
    "TEST-CERT-PAYLOAD-FOR-INTEGRATION\n"
    "-----END CERTIFICATE-----\n"
)


# ── Postgres fixture (testcontainers) ──────────────────────────────────────


@pytest.fixture
async def pg_session_manager(monkeypatch):
    """Поднимает Postgres через testcontainers и подменяет ``main_session_manager``.

    Создаёт минимальный набор таблиц (``certs``, ``cert_history``) через
    ``BaseModel.metadata.create_all`` для нужных моделей, чтобы не запускать
    весь alembic-стек.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers не установлен")

    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    except ImportError:  # pragma: no cover
        pytest.skip("SQLAlchemy async недоступен")

    try:
        pg = PostgresContainer("postgres:16-alpine")
        pg.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker недоступен: {exc}")

    try:
        sync_url = pg.get_connection_url()
        async_url = sync_url.replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        engine = create_async_engine(async_url, future=True)

        from src.infrastructure.database.models.base import BaseModel
        from src.infrastructure.database.models.cert import (  # noqa: F401
            CertHistory,
            CertRecord,
        )

        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: BaseModel.metadata.create_all(
                    sync_conn,
                    tables=[
                        BaseModel.metadata.tables["certs"],
                        BaseModel.metadata.tables["cert_history"],
                    ],
                )
            )

        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        from src.infrastructure.database import session_manager as sm

        monkeypatch.setattr(sm.main_session_manager, "session_maker", session_maker)
        yield sm.main_session_manager

        await engine.dispose()
    finally:
        pg.stop()


# ── Postgres tests ─────────────────────────────────────────────────────────


async def test_postgres_set_get_roundtrip(pg_session_manager) -> None:
    """``set`` сохраняет PEM, ``get`` возвращает идентичную копию."""
    from src.infrastructure.security.cert_store import PostgresCertBackend

    backend = PostgresCertBackend()
    expires = datetime.now(tz=timezone.utc) + timedelta(days=365)

    await backend.save("svc.alpha", _TEST_PEM, expires)
    entry = await backend.get("svc.alpha")

    assert entry is not None
    assert entry.pem == _TEST_PEM
    assert entry.service_id == "svc.alpha"
    assert entry.version == 1
    assert entry.fingerprint  # SHA-256 hex


async def test_postgres_history_two_versions(pg_session_manager) -> None:
    """Двойной ``set`` создаёт две записи в ``cert_history``."""
    from src.infrastructure.security.cert_store import PostgresCertBackend

    backend = PostgresCertBackend()
    expires = datetime.now(tz=timezone.utc) + timedelta(days=180)

    await backend.save("svc.beta", _TEST_PEM, expires, uploaded_by="user-a")
    await backend.save(
        "svc.beta", _TEST_PEM + "EXTRA\n", expires, uploaded_by="user-b"
    )

    entries = await backend.history("svc.beta")
    assert len(entries) == 2
    assert [e.version for e in entries] == [1, 2]


async def test_postgres_get_expiring_soon(pg_session_manager) -> None:
    """``list_expiring`` возвращает только сертификаты до дедлайна."""
    from src.infrastructure.security.cert_store import PostgresCertBackend

    backend = PostgresCertBackend()
    now = datetime.now(tz=timezone.utc)

    await backend.save("svc.expiring", _TEST_PEM, now + timedelta(days=10))
    await backend.save("svc.fresh", _TEST_PEM, now + timedelta(days=400))

    deadline = now + timedelta(days=30)
    expiring = await backend.list_expiring(deadline)
    service_ids = {e.service_id for e in expiring}
    assert "svc.expiring" in service_ids
    assert "svc.fresh" not in service_ids


# ── Vault mock tests ───────────────────────────────────────────────────────


class _FakeVaultKvV2:
    """Минимальный фейк ``hvac.Client.secrets.kv.v2``."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def read_secret_version(self, path: str) -> dict[str, Any]:
        secret = self.store.get(path)
        if secret is None:
            raise RuntimeError("InvalidPath")
        return {"data": {"data": secret}}

    def create_or_update_secret(self, path: str, secret: dict[str, Any]) -> None:
        self.store[path] = dict(secret)


class _FakeVaultClient:
    """Имитация ``hvac.Client`` без сети."""

    def __init__(self) -> None:
        self.secrets = MagicMock()
        self.secrets.kv.v2 = _FakeVaultKvV2()

    def is_authenticated(self) -> bool:
        return True


async def test_vault_backend_with_mock(monkeypatch) -> None:
    """``set`` → ``get`` → PEM идентичен через фейковый Vault."""
    from src.infrastructure.security.cert_store import VaultCertBackend

    fake = _FakeVaultClient()
    backend = VaultCertBackend(base_path="secret/certs")
    monkeypatch.setattr(backend, "_client", lambda: fake)

    expires = datetime.now(tz=timezone.utc) + timedelta(days=90)
    await backend.save("svc.gamma", _TEST_PEM, expires, uploaded_by="vault-user")

    entry = await backend.get("svc.gamma")
    assert entry is not None
    assert entry.pem == _TEST_PEM
    assert entry.version == 1

    # Повторный save → версия 2.
    await backend.save("svc.gamma", _TEST_PEM, expires)
    entry2 = await backend.get("svc.gamma")
    assert entry2 is not None
    assert entry2.version == 2


# ── CertStore facade ───────────────────────────────────────────────────────


async def test_subscribe_updates_invalidates_cache() -> None:
    """``set`` уведомляет подписчиков и обновляет hot-cache."""
    from src.core.config.cert_store import CertStoreSettings
    from src.infrastructure.security.cert_store import CertStore, MemoryCertBackend

    backend = MemoryCertBackend()
    store = CertStore(backend=backend, settings=CertStoreSettings())

    received: list[str] = []

    async def listener(service_id: str) -> None:
        received.append(service_id)

    store.subscribe_updates(listener)
    expires = datetime.now(tz=timezone.utc) + timedelta(days=30)

    await store.set("svc.delta", _TEST_PEM, expires)

    assert received == ["svc.delta"]
    pem_cached = await store.get("svc.delta")
    assert pem_cached == _TEST_PEM

    store.invalidate("svc.delta")
    pem_after_invalidate = await store.get("svc.delta")
    assert pem_after_invalidate == _TEST_PEM
