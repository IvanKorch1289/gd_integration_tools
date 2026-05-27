"""Pytest-фикстура: in-memory Temporal через :mod:`temporalio.testing`.

Lazy-импорт SDK — без ``temporalio`` (extra ``workflow``) фикстура
выставляет ``pytest.skip``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

__all__ = ("temporal_env",)


@pytest_asyncio.fixture(scope="function")
async def temporal_env() -> AsyncIterator[Any]:
    """Поднимает :class:`temporalio.testing.WorkflowEnvironment`."""
    try:
        from temporalio.testing import WorkflowEnvironment  # noqa: PLC0415
    except ImportError:
        pytest.skip("temporalio not installed (extra: workflow)")

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        yield env
    finally:
        await env.shutdown()
