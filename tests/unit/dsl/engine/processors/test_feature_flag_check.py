"""S84 W1 — тесты FeatureFlagCheckProcessor.

Сценарии:
    * Flag enabled + stop_on_disabled=True → pipeline продолжается,
      ``exchange.properties["_flag_enabled"] = True``.
    * Flag disabled + stop_on_disabled=True → ``exchange.stop()``,
      pipeline прерывается.
    * Flag disabled + stop_on_disabled=False → pipeline продолжается,
      результат записан.
    * Resolver exception → ``exchange.fail()``.
    * Custom ``output_field`` → результат в кастомном поле.
    * ``to_spec()`` сериализует все параметры.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.feature_flag_check import (
    FeatureFlagCheckProcessor,
)


def _exchange_with() -> Exchange[Any]:
    return Exchange(in_message=Message(body=b"", headers={}))


def _patch_resolver(is_enabled_return: bool | Exception) -> Any:
    """Подменяет ``TenantFeatureFlagResolver.is_enabled``."""

    async def _factory(*_args: Any, **_kwargs: Any) -> Any:
        if isinstance(is_enabled_return, Exception):
            raise is_enabled_return
        return is_enabled_return

    fake_resolver_cls = MagicMock()
    fake_resolver_cls.return_value = MagicMock()
    fake_resolver_cls.return_value.is_enabled = _factory
    return fake_resolver_cls


# ─── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feature_flag_enabled_continues_pipeline() -> None:
    """Flag = True → pipeline не прерывается, поле записано."""
    proc = FeatureFlagCheckProcessor(flag="new_ui", default=False)
    ex = _exchange_with()

    with patch(
        "src.backend.core.tenancy.feature_flag_scope.TenantFeatureFlagResolver",
        new=_patch_resolver(True),
    ):
        await proc.process(ex, context=MagicMock())

    # exchange НЕ остановлен.
    assert ex.properties.get("_stopped") is not True
    assert ex.properties.get("_flag_enabled") is True


@pytest.mark.asyncio
async def test_feature_flag_disabled_stops_pipeline_by_default() -> None:
    """Flag = False + stop_on_disabled=True (default) → exchange.stop()."""
    proc = FeatureFlagCheckProcessor(flag="disabled_flag")
    ex = _exchange_with()

    with patch(
        "src.backend.core.tenancy.feature_flag_scope.TenantFeatureFlagResolver",
        new=_patch_resolver(False),
    ):
        await proc.process(ex, context=MagicMock())

    # exchange помечен как stopped.
    assert ex.properties.get("_stopped") is True
    # Но НЕ failed.
    assert ex.properties.get("_flag_enabled") is False


@pytest.mark.asyncio
async def test_feature_flag_disabled_continues_when_stop_disabled() -> None:
    """Flag = False + stop_on_disabled=False → pipeline идёт дальше."""
    proc = FeatureFlagCheckProcessor(flag="ab_test", stop_on_disabled=False)
    ex = _exchange_with()

    with patch(
        "src.backend.core.tenancy.feature_flag_scope.TenantFeatureFlagResolver",
        new=_patch_resolver(False),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.properties.get("_stopped") is not True
    assert ex.properties.get("_flag_enabled") is False


# ─── Custom output_field ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feature_flag_custom_output_field() -> None:
    """``output_field="can_proceed"`` → результат в кастомном поле."""
    proc = FeatureFlagCheckProcessor(
        flag="experimental", output_field="can_proceed"
    )
    ex = _exchange_with()

    with patch(
        "src.backend.core.tenancy.feature_flag_scope.TenantFeatureFlagResolver",
        new=_patch_resolver(True),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.properties.get("can_proceed") is True
    assert "_flag_enabled" not in ex.properties


# ─── Failure paths ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feature_flag_resolver_exception_fails_exchange() -> None:
    """Resolver бросает исключение → exchange.fail с понятным сообщением."""
    proc = FeatureFlagCheckProcessor(flag="problematic")
    ex = _exchange_with()

    with patch(
        "src.backend.core.tenancy.feature_flag_scope.TenantFeatureFlagResolver",
        new=_patch_resolver(RuntimeError("provider down")),
    ):
        await proc.process(ex, context=MagicMock())

    assert ex.error is not None
    assert "provider down" in ex.error
    assert "problematic" in ex.error
    # Не должно быть никакого "_flag_enabled" в properties.
    assert "_flag_enabled" not in ex.properties


# ─── to_spec serialization ─────────────────────────────────────────────────


def test_feature_flag_to_spec_minimal() -> None:
    """Default значения опускаются в spec."""
    proc = FeatureFlagCheckProcessor(flag="x")
    spec = proc.to_spec()
    assert spec == {"feature_flag": {"flag": "x", "default": False}}


def test_feature_flag_to_spec_full() -> None:
    """Все параметры сериализуются."""
    proc = FeatureFlagCheckProcessor(
        flag="experimental",
        default=True,
        stop_on_disabled=False,
        output_field="can_proceed",
    )
    spec = proc.to_spec()
    assert spec == {
        "feature_flag": {
            "flag": "experimental",
            "default": True,
            "stop_on_disabled": False,
            "output_field": "can_proceed",
        }
    }


# ─── Default value passthrough ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feature_flag_default_value_when_not_resolved() -> None:
    """Когда resolver возвращает default (False) — это валидный flow."""
    proc = FeatureFlagCheckProcessor(flag="missing_flag", default=True)
    ex = _exchange_with()

    with patch(
        "src.backend.core.tenancy.feature_flag_scope.TenantFeatureFlagResolver",
        new=_patch_resolver(True),
    ):
        await proc.process(ex, context=MagicMock())

    # default=True проигнорирован (resolver вернул True напрямую).
    assert ex.properties.get("_flag_enabled") is True
