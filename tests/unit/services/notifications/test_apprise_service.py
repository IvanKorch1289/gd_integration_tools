"""Юнит-тесты AppriseNotificationService (S3 K3 W1).

Проверяют:
    1. Пропуск (False) если ``feature_flags.notification_dsl_enabled = False``.
    2. Lazy-import apprise (mock apprise.Apprise).
    3. notify_multi возвращает per-channel dict с результатами.
    4. Graceful-деградация при отсутствии пакета apprise (ImportError → False).
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── вспомогательная фикстура: свежий singleton ───────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Сбрасывает глобальный singleton перед каждым тестом."""
    import src.backend.services.notifications.apprise_service as mod

    original = mod._instance
    mod._instance = None
    yield
    mod._instance = original


# ─── тест 1: пропуск при выключенном flag ─────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_skips_when_flag_off() -> None:
    """notify() возвращает False и не обращается к apprise при flag=False."""
    with patch(
        "src.backend.core.config.features.feature_flags.notification_dsl_enabled",
        False,
    ):
        from src.backend.services.notifications.apprise_service import (
            get_notification_service,
        )

        svc = get_notification_service()
        await svc.register_channel("slack", "slack://token/channel")

        with patch.dict(sys.modules, {"apprise": None}):
            result = await svc.notify("slack", "Test", "Body")

    assert result is False


# ─── тест 2: lazy-import apprise (mock apprise.Apprise) ──────────────────────


@pytest.mark.asyncio
async def test_notify_lazy_imports_apprise() -> None:
    """notify() вызывает apprise.Apprise() и async_notify при flag=True."""
    mock_apobj = AsyncMock()
    mock_apobj.async_notify = AsyncMock(return_value=True)

    mock_apprise_mod = MagicMock()
    mock_apprise_mod.Apprise.return_value = mock_apobj
    mock_apprise_mod.NotifyFormat.TEXT = "text"
    mock_apprise_mod.NotifyFormat.HTML = "html"
    mock_apprise_mod.NotifyFormat.MARKDOWN = "markdown"

    with (
        patch(
            "src.backend.core.config.features.feature_flags.notification_dsl_enabled",
            True,
        ),
        patch.dict(sys.modules, {"apprise": mock_apprise_mod}),
    ):
        from src.backend.services.notifications.apprise_service import (
            AppriseNotificationService,
        )

        svc = AppriseNotificationService()
        await svc.register_channel("slack", "slack://token/channel")
        result = await svc.notify("slack", "Заголовок", "Тело")

    assert result is True
    mock_apprise_mod.Apprise.assert_called_once()
    mock_apobj.async_notify.assert_awaited_once()


# ─── тест 3: notify_multi возвращает per-channel dict ─────────────────────────


@pytest.mark.asyncio
async def test_notify_multi_returns_per_channel_status() -> None:
    """notify_multi() возвращает словарь {channel: bool} для каждого канала."""
    mock_apobj = AsyncMock()
    mock_apobj.async_notify = AsyncMock(side_effect=[True, False])

    mock_apprise_mod = MagicMock()
    mock_apprise_mod.Apprise.return_value = mock_apobj
    mock_apprise_mod.NotifyFormat.TEXT = "text"
    mock_apprise_mod.NotifyFormat.HTML = "html"
    mock_apprise_mod.NotifyFormat.MARKDOWN = "markdown"

    with (
        patch(
            "src.backend.core.config.features.feature_flags.notification_dsl_enabled",
            True,
        ),
        patch.dict(sys.modules, {"apprise": mock_apprise_mod}),
    ):
        from src.backend.services.notifications.apprise_service import (
            AppriseNotificationService,
        )

        svc = AppriseNotificationService()
        await svc.register_channel("slack", "slack://token/ch")
        await svc.register_channel("telegram", "tgram://token/chat")

        results = await svc.notify_multi(
            channels=["slack", "telegram"],
            title="Multi",
            body="Тело",
        )

    assert isinstance(results, dict)
    assert set(results.keys()) == {"slack", "telegram"}
    assert results["slack"] is True
    assert results["telegram"] is False


# ─── тест 4: graceful при отсутствии apprise ──────────────────────────────────


@pytest.mark.asyncio
async def test_notify_graceful_when_apprise_missing() -> None:
    """notify() возвращает False без краша если apprise не установлен."""
    with (
        patch(
            "src.backend.core.config.features.feature_flags.notification_dsl_enabled",
            True,
        ),
    ):
        # Имитируем ImportError при import apprise
        original = sys.modules.get("apprise", ...)
        sys.modules["apprise"] = None  # type: ignore[assignment]
        try:
            from src.backend.services.notifications.apprise_service import (
                AppriseNotificationService,
            )

            svc = AppriseNotificationService()
            await svc.register_channel("slack", "slack://token/ch")
            result = await svc.notify("slack", "Test", "Body")
        finally:
            if original is ...:
                sys.modules.pop("apprise", None)
            else:
                sys.modules["apprise"] = original  # type: ignore[assignment]

    assert result is False
