"""D-AUDIT-9701: regression-тест list_actions fail-LOUD (API-P1-005).

Бывший баг: list_actions возвращал _mock_actions() silent при
registry is None ИЛИ registry.list_all() throws Exception → admin UI
получал mock-список вместо индикатора сбоя. Decisions принимались
на недостоверных данных.

Фикс (cycle 97): fail-LOUD HTTP 503 + ERROR-лог с structured context.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.backend.entrypoints.api.v1.endpoints import admin_actions


@pytest.mark.asyncio
async def test_list_actions_registry_none_raises_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """registry is None → 503 (НЕ silent mock)."""
    # Stub feature_flags так, чтобы admin_marketplace_endpoints = True
    class _Flags:
        admin_marketplace_endpoints = True

    import src.backend.core.feature_flags as ff_mod

    monkeypatch.setattr(ff_mod, "get_feature_flag_service", lambda: _Flags())
    # Stub registry getter чтобы вернул None
    monkeypatch.setattr(admin_actions, "_get_registry", lambda: None)

    with pytest.raises(HTTPException) as exc_info:
        await admin_actions.list_actions()
    assert exc_info.value.status_code == 503
    assert "ActionHandlerRegistry недоступен" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_list_actions_list_all_raises_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """registry.list_all() throws → 503 (НЕ silent mock)."""
    class _Flags:
        admin_marketplace_endpoints = True

    import src.backend.core.feature_flags as ff_mod

    monkeypatch.setattr(ff_mod, "get_feature_flag_service", lambda: _Flags())

    # Mock registry, list_all() raises AttributeError
    mock_reg = MagicMock()
    mock_reg.list_all = MagicMock(side_effect=AttributeError("'NoneType' has no attribute 'list_all'"))
    monkeypatch.setattr(admin_actions, "_get_registry", lambda: mock_reg)

    with pytest.raises(HTTPException) as exc_info:
        await admin_actions.list_actions()
    assert exc_info.value.status_code == 503
    assert "Не удалось прочитать реестр" in str(exc_info.value.detail)
    assert "AttributeError" in str(exc_info.value.detail) or "NoneType" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_list_actions_returns_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: registry.list_all() возвращает specs → сериализуются в ActionSummary."""
    class _Flags:
        admin_marketplace_endpoints = True

    import src.backend.core.feature_flags as ff_mod

    monkeypatch.setattr(ff_mod, "get_feature_flag_service", lambda: _Flags())

    # Mock spec
    class _Spec:
        name = "system.health.check"
        description = "Проверка состояния"
        namespace = "system"
        tier = "1"

    mock_reg = MagicMock()
    mock_reg.list_all = MagicMock(return_value=[_Spec()])
    monkeypatch.setattr(admin_actions, "_get_registry", lambda: mock_reg)

    result = await admin_actions.list_actions()
    assert len(result) == 1
    assert result[0].name == "system.health.check"
    assert result[0].description == "Проверка состояния"
    assert result[0].namespace == "system"
    assert result[0].tier == "1"
