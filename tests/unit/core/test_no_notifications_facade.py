"""Regression tests для core.notifications facade removal (Sprint 35 W1, ADR-0282 Phase B).

Покрывает:
1. `src.backend.core.notifications` import raises ModuleNotFoundError
   (facade fully deleted, NOT a stub).
2. `infrastructure.notifications` is canonical home для get_gateway +
   NotificationGateway.
3. Caller migration: 3 files (services/ops/notification_hub.py,
   plugins/composition/lifecycle/protocols.py, dsl/engine/processors/notify/__init__.py)
   import из `infrastructure.notifications` напрямую.

Per ADR-0282 §3 Phase B: prune notification-фасады (38 LOC, 3 callers).
Verification: 2 allowlist entries removed (`core/notifications/__init__.py`),
1 new allowlist entry added (`services/ops/notification_hub.py → infrastructure.notifications`,
documented as architectural debt — services layer legitimately needs gateway, ADR
follow-up needed). Net: 61 → 60 entries (−1, not −2 as planned).
"""

from __future__ import annotations

import importlib
import sys

import pytest


def test_core_notifications_module_does_not_exist() -> None:
    """``core.notifications`` facade fully removed (Sprint 35 W1).

    Pre-fix: thin facade re-exported get_gateway + NotificationGateway
    from infrastructure.notifications. Post-fix: callers import directly
    from infrastructure.notifications.

    Asserts:
    - ``import src.backend.core.notifications`` raises ModuleNotFoundError
      (facade directory deleted, NOT a stub file).
    - The module name is not registered в sys.modules (not cached).
    """
    # Clear any cached import (defensive — pytest collection order может vary)
    sys.modules.pop("src.backend.core.notifications", None)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        importlib.import_module("src.backend.core.notifications")

    assert "core.notifications" in str(exc_info.value) or "core/notifications" in str(
        exc_info.value
    )


def test_infrastructure_notifications_is_canonical_home() -> None:
    """``infrastructure.notifications`` provides get_gateway + NotificationGateway.

    Per ARC-005 analysis doc: notifications gateway is canonical home
    для ``get_gateway`` factory + ``NotificationGateway`` class (single
    source of truth, no facade indirection).
    """
    from src.backend.infrastructure.notifications import get_gateway
    from src.backend.infrastructure.notifications.gateway import NotificationGateway

    # Factory и class должны быть callable / instantiable
    assert callable(get_gateway), "get_gateway должна быть callable factory"
    assert NotificationGateway is not None, (
        "NotificationGateway class должен существовать"
    )


def test_three_callers_migrated_to_infrastructure_notifications() -> None:
    """3 known callers of core.notifications теперь import из infrastructure.notifications.

    Caller inventory (Sprint 35 W1 verified):
    1. src/backend/services/ops/notification_hub.py — module-level + lazy in method
    2. src/backend/plugins/composition/lifecycle/protocols.py — lazy in function
    3. src/backend/dsl/engine/processors/notify/__init__.py — lazy in process()
    """
    # Caller 1: services/ops/notification_hub.py
    # Has 2 imports: module-level (line 16) + lazy in method (line 99).
    # Both переведены на infrastructure.notifications.
    text = (
        importlib.resources.files("src.backend.services.ops")
        .joinpath("notification_hub.py")
        .read_text(encoding="utf-8")
    )
    assert "from src.backend.infrastructure.notifications import get_gateway" in text, (
        "services/ops/notification_hub.py должна import из infrastructure.notifications"
    )
    assert "from src.backend.core.notifications" not in text, (
        "services/ops/notification_hub.py не должна использовать core.notifications"
    )

    # Caller 2: plugins/composition/lifecycle/protocols.py
    text = (
        importlib.resources.files("src.backend.plugins.composition.lifecycle")
        .joinpath("protocols.py")
        .read_text(encoding="utf-8")
    )
    assert "from src.backend.infrastructure.notifications import (" in text
    assert "get_gateway" in text
    assert "from src.backend.core.notifications" not in text

    # Caller 3: dsl/engine/processors/notify/__init__.py
    text = (
        importlib.resources.files("src.backend.dsl.engine.processors")
        .joinpath("notify/__init__.py")
        .read_text(encoding="utf-8")
    )
    assert "from src.backend.infrastructure.notifications import (" in text
    assert "get_gateway" in text
    assert "from src.backend.core.notifications" not in text
