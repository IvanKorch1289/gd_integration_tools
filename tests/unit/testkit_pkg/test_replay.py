"""Unit-тесты replay-transport (HAR → MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from testkit.recorder import HARCassette, HAREntry
from testkit.replay import MissingCassetteEntry, build_replay_transport


@pytest.mark.asyncio
async def test_replay_returns_recorded_response() -> None:
    """build_replay_transport отдаёт ответ из кассеты."""
    cassette = HARCassette(
        entries=[
            HAREntry(
                method="GET",
                url="https://api.example.com/v1/x",
                status=201,
                response_headers={"content-type": "application/json"},
                response_body='{"id":42}',
            )
        ]
    )
    transport = build_replay_transport(cassette)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://api.example.com/v1/x")
    assert resp.status_code == 201
    assert resp.json() == {"id": 42}


@pytest.mark.asyncio
async def test_replay_strict_raises_on_unknown() -> None:
    """Strict: неизвестный URL → MissingCassetteEntry."""
    transport = build_replay_transport(HARCassette())
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(MissingCassetteEntry):
            await client.get("https://nope.local/x")


@pytest.mark.asyncio
async def test_replay_non_strict_returns_404() -> None:
    """Non-strict: неизвестный URL → 404."""
    transport = build_replay_transport(HARCassette(), strict=False)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://nope.local/x")
    assert resp.status_code == 404


def test_round_trip_recorder_to_replay() -> None:
    """Кассета сериализуется и восстанавливается без потерь."""
    original = HARCassette(
        entries=[HAREntry(method="POST", url="https://x/y", status=204)]
    )
    raw = original.to_json()
    restored = HARCassette.from_json(raw)
    transport = build_replay_transport(restored)
    assert transport is not None
