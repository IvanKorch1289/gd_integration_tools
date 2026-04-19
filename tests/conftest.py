"""Pytest configuration — shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def dsl_builder() -> AsyncGenerator:
    """Fresh RouteBuilder for each test."""
    from app.dsl.builder import RouteBuilder
    yield RouteBuilder


@pytest.fixture
def sample_exchange():
    """Basic Exchange with dict body."""
    from app.dsl.engine.exchange import Exchange, Message

    return Exchange(
        in_message=Message(body={"test": "data"}, headers={"X-Test": "1"})
    )
