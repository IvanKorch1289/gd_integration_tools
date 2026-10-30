"""ADR-0395 — переключение движков и типовая сохранность payload'ов.

Дефект (6, medium): ``factory.create_workflow_backend`` ловил только
``RuntimeError`` — падение коннекта к Temporal-кластеру (OSError,
``temporalio`` RPCError, TimeoutError) не давало fallback'а. Тихий
downgrade на pg-runner терял replay / детерминизм / typed-query.
Дополнительно data-converter Temporal'а (``canonical_json_bytes`` +
``orjson.loads``) терял типы datetime / UUID / Decimal — семантика шага
зависела от движка.

Проверяем:
* fallback срабатывает на любой ошибке подключения, не только RuntimeError;
* downgrade логируется с перечнем потерянных гарантий;
* явный ``kind="temporal"`` не деградирует (fail-closed);
* payload round-trip сохраняет datetime / UUID / Decimal.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from src.backend.infrastructure.workflow.factory import create_workflow_backend


def _install_broken_temporal(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Подменить ``temporal_backend`` модулем, который падает на connect."""

    async def _broken_connect(**kwargs: Any) -> object:
        raise exc

    class _Shim:
        connect = staticmethod(_broken_connect)

    fake_module = types.ModuleType(
        "src.backend.infrastructure.workflow.temporal_backend"
    )
    fake_module.TemporalWorkflowBackend = _Shim  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.backend.infrastructure.workflow.temporal_backend", fake_module
    )


class TestTemporalFallback:
    """Fallback при недоступности Temporal-кластера."""

    @pytest.mark.asyncio
    async def test_connection_error_falls_back_to_pg_runner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError (недоступный хост) → fallback, а не падение."""
        _install_broken_temporal(monkeypatch, OSError("connection refused"))

        backend = await create_workflow_backend(kind="auto", profile="dev")

        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert isinstance(backend, PgRunnerWorkflowBackend)

    @pytest.mark.asyncio
    async def test_timeout_error_falls_back_to_pg_runner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TimeoutError → fallback (раньше ловился только RuntimeError)."""
        _install_broken_temporal(monkeypatch, TimeoutError("connect timeout"))

        backend = await create_workflow_backend(kind="auto", profile="dev")

        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert isinstance(backend, PgRunnerWorkflowBackend)

    @pytest.mark.asyncio
    async def test_downgrade_logs_lost_guarantees(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Downgrade логируется с перечнем потерянных гарантий."""
        _install_broken_temporal(monkeypatch, OSError("connection refused"))

        with caplog.at_level("WARNING"):
            await create_workflow_backend(kind="auto", profile="dev")

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "replay" in messages
        assert "determinism" in messages
        assert "typed-query" in messages

    @pytest.mark.asyncio
    async def test_explicit_temporal_kind_does_not_downgrade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Явный ``kind='temporal'`` → ошибка пробрасывается (без downgrade)."""
        _install_broken_temporal(monkeypatch, OSError("connection refused"))

        with pytest.raises(OSError, match="connection refused"):
            await create_workflow_backend(kind="temporal", profile="prod")


class TestDowngradeGuard:
    """ADR-0399 (ADR-0395): downgrade Temporal → pg_runner запрещён вне dev."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("profile", ["staging", "prod"])
    async def test_downgrade_forbidden_outside_dev(
        self, monkeypatch: pytest.MonkeyPatch, profile: str
    ) -> None:
        """В staging/prod падение Temporal → ошибка, а не pg_runner."""
        _install_broken_temporal(monkeypatch, OSError("connection refused"))

        with pytest.raises(RuntimeError, match="downgrade") as exc_info:
            await create_workflow_backend(kind="auto", profile=profile)

        message = str(exc_info.value)
        assert profile in message
        assert "pg_runner" in message
        assert isinstance(exc_info.value.__cause__, OSError)

    @pytest.mark.asyncio
    async def test_auto_without_profile_uses_active_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``kind='auto'`` без профиля (cli/workflow.py) → профиль из APP_PROFILE."""
        _install_broken_temporal(monkeypatch, OSError("connection refused"))
        monkeypatch.setenv("APP_PROFILE", "prod")

        with pytest.raises(RuntimeError, match="downgrade"):
            await create_workflow_backend(kind="auto")

    @pytest.mark.asyncio
    async def test_auto_without_profile_in_dev_still_downgrades(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """В dev-профиле downgrade остаётся разрешённым."""
        _install_broken_temporal(monkeypatch, OSError("connection refused"))
        monkeypatch.setenv("APP_PROFILE", "dev")

        backend = await create_workflow_backend(kind="auto")

        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert isinstance(backend, PgRunnerWorkflowBackend)

    @pytest.mark.asyncio
    async def test_explicit_pg_runner_kind_still_allowed_in_prod(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Явный выбор оператора (``kind='pg_runner'``) — не downgrade."""
        monkeypatch.setenv("APP_PROFILE", "prod")

        backend = await create_workflow_backend(kind="pg_runner")

        from src.backend.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert isinstance(backend, PgRunnerWorkflowBackend)


class TestTemporalDataConverter:
    """Типы payload'а не теряются при encode/decode."""

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_rich_types(self) -> None:
        """datetime / UUID / Decimal переживают round-trip через converter."""
        from src.backend.infrastructure.workflow.temporal_backend import (
            build_temporal_data_converter,
        )

        converter = build_temporal_data_converter()
        value = {
            "created_at": datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            "id": UUID("123e4567-e89b-12d3-a456-426614174000"),
            "amount": Decimal("10.50"),
        }

        payloads = await converter.encode([value])
        restored = await converter.decode(payloads)

        assert restored == [value]
        assert isinstance(restored[0]["created_at"], datetime)
        assert isinstance(restored[0]["id"], UUID)
        assert isinstance(restored[0]["amount"], Decimal)

    @pytest.mark.asyncio
    async def test_encoding_is_byte_stable(self) -> None:
        """Порядок ключей не влияет на байты payload'а (canonical JSON)."""
        from src.backend.infrastructure.workflow.temporal_backend import (
            build_temporal_data_converter,
        )

        converter = build_temporal_data_converter()

        first = (await converter.encode([{"a": 1, "b": 2}]))[0].data
        second = (await converter.encode([{"b": 2, "a": 1}]))[0].data

        assert first == second
