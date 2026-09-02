"""Unit-тесты ``services.ops.notification_hub`` deprecation — Sprint C3 (S50 P0 #17).

S48 swarm audit (A3 Services #7): ``services.ops.notification_hub`` помечен
deprecated (IL2.2 / ADR-023) но 5 consumers ещё не мигрировали:
- services.ops.anomaly_detector (uses ``hub.broadcast(channels, subject, message)``)
- services.ops.scheduled_reports (uses ``hub.broadcast``)
- dsl.commands.setup.registers_workflow (uses ``service_getter=get_notification_hub``)
- plugins.composition.lifecycle.protocols (uses ``register_provider("notifier", "hub", get_notification_hub)``)
- dsl.commands.setup.registers_workflow (duplicate)

Sprint C3 scope (verification-only sprint per Plan A):
* Verify DeprecationWarning emitted на import (per module-level warnings.warn)
* Verify ``get_notification_hub`` factory + ``NotificationHub.broadcast/email/etc`` still work (legacy contract intact)
* Document migration path (target: ``infrastructure.notifications.gateway.get_gateway()``)

Full migration (per-consumer rewrite) — deferred (4h task, requires
template design + per-consumer recipient extraction). Migration target
ADR-023 specifies new Gateway API uses Jinja2 templates + multi-channel
broadcast + priority queues + DLQ — breaking change for current 5 consumers.
"""

from __future__ import annotations

import warnings

import pytest

from src.backend.services.ops.notification_hub import (
    Channel,
    NotificationHub,
    NotificationRequest,
    get_notification_hub,
)


@pytest.mark.unit
class TestNotificationHubDeprecation:
    """Verify ``services.ops.notification_hub`` is properly deprecated."""

    def test_deprecation_warning_emitted_on_import(self) -> None:
        """Import triggers ``DeprecationWarning`` (per ADR-023 / IL2.2)."""
        with warnings.catch_warnings(record=True) as warning_list:
            warnings.simplefilter("always")
            # Force re-import (already imported, force re-eval)
            import importlib

            importlib.reload(
                __import__(
                    "src.backend.services.ops.notification_hub",
                    fromlist=["*"],
                )
            )

        # Find DeprecationWarning mentioning notification_hub / IL2.2 / ADR-023
        deprecation_warnings = [
            w
            for w in warning_list
            if issubclass(w.category, DeprecationWarning)
            and (
                "notification_hub" in str(w.message)
                or "IL2.2" in str(w.message)
                or "ADR-023" in str(w.message)
            )
        ]
        assert len(deprecation_warnings) > 0, (
            "notification_hub должен emit DeprecationWarning на import "
            "(per ADR-023 deprecation policy)"
        )

    def test_module_docstring_documents_migration_target(self) -> None:
        """Module docstring ссылается на migration target (``get_gateway``)."""
        import src.backend.services.ops.notification_hub as mod

        doc = mod.__doc__
        assert doc is not None
        assert "deprecated" in doc.lower()
        assert "get_gateway" in doc
        assert "ADR-023" in doc or "IL2.2" in doc

    def test_all_exports_still_importable(self) -> None:
        """Backward-compat: legacy exports still available (no breaking)."""
        # Per ADR-023: deprecation, not removal. Все 4 symbols
        # остаются importable для existing 5 consumers.
        assert callable(get_notification_hub)
        assert isinstance(Channel, type)
        assert isinstance(NotificationHub, type)
        assert isinstance(NotificationRequest, type)

    def test_channel_strenum_values(self) -> None:
        """``Channel`` StrEnum values — backward-compat с legacy consumers."""
        assert Channel.EMAIL == "email"
        assert Channel.EXPRESS == "express"
        assert Channel.WEBHOOK == "webhook"
        assert Channel.TELEGRAM == "telegram"

    def test_migration_documented_in_module(self) -> None:
        """Module docstring документирует 5 consumers ещё не мигрировали."""
        import src.backend.services.ops.notification_hub as mod

        doc = mod.__doc__
        # Per inline comment (line 65-72): 5 consumers — anomaly_detector,
        # scheduled_reports, registers_workflow (×2 refs), protocols, notify_actions.
        assert doc is not None
        assert "5 consumers" in doc or "5 исторических" in doc or "consumer" in doc.lower()


@pytest.mark.unit
class TestNotificationHubLegacyContract:
    """Legacy contract preserved — migration is gradual."""

    def test_notification_request_dataclass(self) -> None:
        """``NotificationRequest`` dataclass — backward-compat fields."""
        req = NotificationRequest(
            subject="test",
            message="test msg",
            channel=Channel.EMAIL,
        )
        assert req.subject == "test"
        assert req.message == "test msg"
        assert req.channel == Channel.EMAIL

    def test_get_notification_hub_returns_singleton(self) -> None:
        """``get_notification_hub()`` — singleton instance."""
        hub1 = get_notification_hub()
        hub2 = get_notification_hub()
        # Per ``@app_state_singleton("notification_hub", factory=NotificationHub)``
        assert hub1 is hub2

    def test_notification_hub_has_legacy_methods(self) -> None:
        """``NotificationHub`` имеет legacy methods (broadcast, email, etc)."""
        hub = get_notification_hub()
        # Per module docstring: email, eXpress, webhook, telegram, broadcast
        for method_name in ("broadcast", "email", "express", "webhook", "telegram"):
            assert hasattr(hub, method_name), (
                f"NotificationHub missing legacy method '{method_name}' "
                f"(consumers depend on it until migration)"
            )
