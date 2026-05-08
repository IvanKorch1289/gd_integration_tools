"""Тесты register_ai_2026_providers: default-OFF и graceful skip."""

from __future__ import annotations

import pytest

from src.backend.plugins.composition.setup_ai_2026 import register_ai_2026_providers


@pytest.mark.asyncio
async def test_register_default_off_does_not_raise() -> None:
    """С default-OFF флагами setup не должен падать (только log debug)."""
    await register_ai_2026_providers()


@pytest.mark.asyncio
async def test_register_runs_idempotently() -> None:
    """Повторный вызов также не должен падать."""
    await register_ai_2026_providers()
    await register_ai_2026_providers()
