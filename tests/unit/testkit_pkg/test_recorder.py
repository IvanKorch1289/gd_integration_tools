"""Unit-тесты HAR-recorder."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from testkit.recorder import HARCassette, HAREntry, HARRecorder


def test_cassette_round_trip(tmp_path: Path) -> None:
    """Сериализация HARCassette сохраняет все поля."""
    cassette = HARCassette(
        entries=[
            HAREntry(
                method="GET",
                url="https://api.example.com/v1/items",
                status=200,
                request_headers={"accept": "application/json"},
                response_headers={"content-type": "application/json"},
                response_body='{"items":[]}',
            )
        ]
    )
    file = tmp_path / "demo.har.json"
    cassette.save(file)

    loaded = HARCassette.load(file)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].url == "https://api.example.com/v1/items"
    assert loaded.entries[0].response_body == '{"items":[]}'


def test_cassette_empty_round_trip() -> None:
    """Пустая кассета корректно (де)сериализуется."""
    cassette = HARCassette()
    raw = cassette.to_json()
    assert "1.2" in raw
    restored = HARCassette.from_json(raw)
    assert restored.entries == []


@pytest.mark.asyncio
async def test_recorder_captures_response_via_mock_transport() -> None:
    """Recorder сохраняет ответ, полученный через MockTransport — без сети."""
    recorder = HARRecorder()
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mock.local") as client:
        request = client.build_request("GET", "/items")
        response = await client.send(request)
        await response.aread()
        recorder._record_response(request, response)

    assert len(recorder.cassette.entries) == 1
    entry = recorder.cassette.entries[0]
    assert entry.method == "GET"
    assert entry.status == 200
    assert "ok" in (entry.response_body or "")
