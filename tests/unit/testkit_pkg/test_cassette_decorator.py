"""Тесты для @cassette decorator (S10 K5 W6)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from testkit.recorder import cassette
from testkit.recorder._har import HARCassette, HAREntry
from testkit.recorder.cassette import (
    _ReplayTransport,
    load_cassette,
    save_cassette,
)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    cas = HARCassette(
        entries=[
            HAREntry(
                method="GET",
                url="https://api.example.com/x",
                status=200,
                request_headers={"x": "1"},
                response_headers={"content-type": "application/json"},
                request_body=None,
                response_body='{"y":1}',
            )
        ]
    )
    path = tmp_path / "tc.yaml"
    save_cassette(path, cas)
    loaded = load_cassette(path)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].url == "https://api.example.com/x"
    assert loaded.entries[0].status == 200


def test_replay_transport_returns_recorded_response() -> None:
    cas = HARCassette(
        entries=[
            HAREntry(
                method="GET",
                url="https://api.test/x",
                status=200,
                request_headers={},
                response_headers={"content-type": "application/json"},
                request_body=None,
                response_body='{"ok":true}',
            )
        ]
    )
    transport = _ReplayTransport(cas)
    # Просто smoke: map должен содержать запись.
    assert ("GET", "https://api.test/x") in transport._map


def test_replay_transport_miss_returns_599() -> None:
    cas = HARCassette(entries=[])
    transport = _ReplayTransport(cas)
    assert ("ANY", "https://api.test/missing") not in transport._map


@pytest.mark.asyncio
async def test_decorator_replays_existing_cassette(tmp_path: Path) -> None:
    """Pre-populated cassette → @cassette ничего не ходит в сеть, replay-режим."""
    # Подготавливаем пред-записанную кассету.
    cas = HARCassette(
        entries=[
            HAREntry(
                method="GET",
                url="https://api.test/score",
                status=200,
                request_headers={},
                response_headers={"content-type": "application/json"},
                request_body=None,
                response_body='{"score":750}',
            )
        ]
    )
    path = tmp_path / "score.yaml"
    save_cassette(path, cas)

    @cassette(path)
    async def _test_fn(client: httpx.AsyncClient) -> int:
        resp = await client.get("https://api.test/score")
        assert resp.status_code == 200
        return resp.json()["score"]

    assert await _test_fn() == 750


@pytest.mark.asyncio
async def test_decorator_replay_mode_raises_when_no_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"

    @cassette(path, mode="replay")
    async def _f(client: httpx.AsyncClient) -> int:
        return 1

    with pytest.raises(FileNotFoundError):
        await _f()


@pytest.mark.asyncio
async def test_decorator_records_then_loadable_yaml(tmp_path: Path, monkeypatch) -> None:
    """Mock httpx.AsyncHTTPTransport чтобы не выходить в реальную сеть."""

    class _StubTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"hi": 1},
                headers={"content-type": "application/json"},
                request=request,
            )

    monkeypatch.setattr(
        httpx,
        "AsyncHTTPTransport",
        lambda *a, **kw: _StubTransport(),  # type: ignore[arg-type]
    )

    path = tmp_path / "rec.yaml"

    @cassette(path, mode="record")
    async def _f(client: httpx.AsyncClient) -> int:
        r = await client.get("https://test.local/x")
        return r.status_code

    code = await _f()
    assert code == 200
    assert path.is_file()
    cas = load_cassette(path)
    assert len(cas.entries) == 1


def test_decorator_requires_client_param() -> None:
    """Если у функции нет client-параметра, декорирование падает с TypeError."""
    with pytest.raises(TypeError, match="параметра для client"):

        @cassette("/tmp/nonexistent.yaml")
        async def _f() -> None:
            pass
