"""Unit-тесты task_group_tolerant (Sprint 9 K3 W8)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.utils.async_utils import task_group_tolerant


@pytest.mark.asyncio
async def test_all_success() -> None:
    async def good(x: int) -> int:
        return x * 2

    results = await task_group_tolerant([good(1), good(2), good(3)])
    assert results == [2, 4, 6]


@pytest.mark.asyncio
async def test_partial_failure_isolated() -> None:
    async def good() -> int:
        return 1

    async def bad() -> int:
        raise RuntimeError("boom")

    results = await task_group_tolerant([good(), bad(), good()])
    assert results[0] == 1
    assert isinstance(results[1], RuntimeError)
    assert results[2] == 1


@pytest.mark.asyncio
async def test_empty_list() -> None:
    results = await task_group_tolerant([])
    assert results == []


@pytest.mark.asyncio
async def test_order_preserved() -> None:
    async def delay(x: int, sleep: float) -> int:
        await asyncio.sleep(sleep)
        return x

    results = await task_group_tolerant(
        [delay(1, 0.02), delay(2, 0.0), delay(3, 0.01)]
    )
    assert results == [1, 2, 3]
