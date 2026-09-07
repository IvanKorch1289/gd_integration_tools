"""Тесты lazy-прокси scheduler/admin.py (T3 ratchet: 0%→100%).

__getattr__ проксирует SchedulerDLQStore / get_scheduler_dlq_store /
get_scheduler_manager в core.api.scheduler (sub-modules dlq и
scheduler_manager). Неизвестные атрибуты -> AttributeError.
"""

from __future__ import annotations

import pytest

import src.backend.services.scheduler.admin as admin


def test_proxy_scheduler_dlq_store_class() -> None:
    """SchedulerDLQStore проксируется в infrastructure.scheduler.dlq."""
    from src.backend.infrastructure.scheduler.dlq import SchedulerDLQStore as real

    assert admin.SchedulerDLQStore is real


def test_proxy_get_scheduler_dlq_store_callable() -> None:
    from src.backend.infrastructure.scheduler.dlq import (
        get_scheduler_dlq_store as real,
    )

    assert admin.get_scheduler_dlq_store is real


def test_proxy_get_scheduler_manager() -> None:
    """get_scheduler_manager проксируется в scheduler_manager sub-module."""
    from src.backend.core.api.scheduler import scheduler_manager as _mod

    assert admin.get_scheduler_manager is _mod.get_scheduler_manager


def test_unknown_attribute_raises() -> None:
    with pytest.raises(AttributeError, match="nonexistent"):
        admin.nonexistent_attribute  # noqa: B018
