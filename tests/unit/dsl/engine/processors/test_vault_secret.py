"""S83 W3 — тесты для VaultSecretProcessor (vault_read DSL step).

Сценарии:
    * Happy path: backend возвращает SecretValue → exchange.properties
      содержит ``{path, value, version}``.
    * Custom output_field → только value-строка, не dict.
    * version > 0 → вызов ``get_versioned``.
    * Backend exception → exchange.fail.
    * Vault deps не установлены → exchange.fail с понятным сообщением.
    * ``to_spec()`` сериализует path/output_field/version.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.vault_secret import (
    VaultReadResult,
    VaultSecretProcessor,
)


def _exchange_with() -> Exchange[Any]:
    return Exchange(in_message=Message(body=b"", headers={}))


def _fake_secret_value(name: str, value: str, version: int) -> MagicMock:
    """Мок для ``SecretValue`` — name, value, version."""
    sv = MagicMock()
    sv.name = name
    sv.value = value
    sv.version = version
    return sv


# ─── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vault_read_default_output_field_writes_full_dict() -> None:
    """output_field="value" (default) → exchange.properties["value"] = {path, value, version}."""
    proc = VaultSecretProcessor(path="secret/data/db/password")
    ex = _exchange_with()

    fake_sv = _fake_secret_value(
        "secret/data/db/password", "super-secret", 3
    )
    fake_backend = MagicMock()
    fake_backend.get = MagicMock(return_value=fake_sv)

    with patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultConfig.from_env",
        return_value=MagicMock(),
    ), patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultBackend",
        return_value=fake_backend,
    ), patch(
        "asyncio.to_thread", new=AsyncMock(return_value=fake_sv),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.status != ExchangeStatus.failed
    result = ex.properties.get("value")
    assert result == {
        "path": "secret/data/db/password",
        "value": "super-secret",
        "version": 3,
    }


@pytest.mark.asyncio
async def test_vault_read_custom_output_field_writes_only_value() -> None:
    """output_field="db_password" → exchange.properties["db_password"] = value string."""
    proc = VaultSecretProcessor(
        path="secret/data/db/password", output_field="db_password"
    )
    ex = _exchange_with()

    fake_sv = _fake_secret_value("secret/data/db/password", "pw123", 1)

    with patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultBackend"
    ) as BackendCls, patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultConfig.from_env"
    ):
        BackendCls.return_value.get = MagicMock(return_value=fake_sv)
        with patch(
            "asyncio.to_thread", new=AsyncMock(return_value=fake_sv),
        ):
            await proc.process(ex, context=MagicMock())

    assert ex.properties.get("db_password") == "pw123"
    assert "value" not in ex.properties  # default field not written


# ─── Versioned read ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vault_read_with_version_uses_get_versioned() -> None:
    """version > 0 → get_versioned (async), не get (sync)."""
    proc = VaultSecretProcessor(path="secret/data/api/key", version=7)
    ex = _exchange_with()

    fake_sv = _fake_secret_value("secret/data/api/key", "key-v7", 7)
    fake_backend = MagicMock()
    fake_backend.get_versioned = AsyncMock(return_value=fake_sv)

    with patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultConfig.from_env",
        return_value=MagicMock(),
    ), patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultBackend",
        return_value=fake_backend,
    ):
        await proc.process(ex, context=MagicMock())

    fake_backend.get_versioned.assert_awaited_once_with(
        "secret/data/api/key", 7
    )
    assert ex.properties["value"]["version"] == 7


# ─── Failure paths ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vault_read_backend_exception_fails_exchange() -> None:
    """Любое исключение из backend → exchange.fail с понятным сообщением."""
    proc = VaultSecretProcessor(path="secret/data/missing")
    ex = _exchange_with()

    with patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultConfig.from_env",
        return_value=MagicMock(),
    ), patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultBackend"
    ) as BackendCls, patch(
        "asyncio.to_thread",
        new=AsyncMock(side_effect=RuntimeError("connection refused")),
    ):
        BackendCls.return_value.get = MagicMock(
            side_effect=RuntimeError("connection refused")
        )
        await proc.process(ex, context=MagicMock())

    assert ex.status == ExchangeStatus.failed
    assert "connection refused" in (ex.error or "")
    assert "secret/data/missing" in (ex.error or "")


@pytest.mark.asyncio
async def test_vault_read_import_error_fails_exchange() -> None:
    """Если vault backend не импортируется → exchange.fail."""
    proc = VaultSecretProcessor(path="secret/data/db")
    ex = _exchange_with()

    # Блокируем импорт vault_backend внутри process() — после ``try: from ...``
    # Мы не можем перехватить именно ImportError без сложной магии, поэтому
    # проверим более простой кейс: при попытке инстанцировать VaultBackend
    # с пустым config бросается исключение → exchange.fail.

    with patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultConfig.from_env",
        return_value=MagicMock(),
    ), patch(
        "src.backend.infrastructure.secrets.vault_backend.VaultBackend",
        side_effect=ImportError("simulated: hvac not installed"),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.status == ExchangeStatus.failed
    assert "Vault read failed" in (ex.error or "")


# ─── to_spec serialization ─────────────────────────────────────────────────


def test_vault_read_to_spec_minimal() -> None:
    """Default output_field и version=0 → только path."""
    proc = VaultSecretProcessor(path="secret/data/api")
    assert proc.to_spec() == {"vault_read": {"path": "secret/data/api"}}


def test_vault_read_to_spec_full() -> None:
    """Custom output_field и version → все три поля."""
    proc = VaultSecretProcessor(
        path="secret/data/api", output_field="api_secret", version=2
    )
    assert proc.to_spec() == {
        "vault_read": {
            "path": "secret/data/api",
            "output_field": "api_secret",
            "version": 2,
        }
    }


# ─── VaultReadResult DTO ───────────────────────────────────────────────────


def test_vault_read_result_is_dataclass() -> None:
    """VaultReadResult — dataclass c тремя полями (для downstream typing)."""
    r = VaultReadResult(path="p", value="v", version=5)
    assert r.path == "p"
    assert r.value == "v"
    assert r.version == 5
