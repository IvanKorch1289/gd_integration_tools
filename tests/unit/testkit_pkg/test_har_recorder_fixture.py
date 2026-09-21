"""Tail-debt s10-debt/c2 — consumer для fixture :func:`har_recorder`.

Закрывает orphan-scaffold: fixture создана в A.1, но 0 тестов её
использовали. ``test_recorder.py`` инстанциировал :class:`HARRecorder`
напрямую. Этот тест гарантирует, что обе fixture (``har_recorder`` +
``har_cassette_path``) корректно регистрируются через
``testkit.pytest_plugin`` и проходят round-trip без сети.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from testkit.recorder import HARCassette, HARRecorder


def test_har_recorder_fixture_round_trip(
    har_recorder: HARRecorder, har_cassette_path: Path
) -> None:
    """Fixture даёт recorder с mask_secrets=True и записываемый путь кассеты."""

    # Mask-secrets включён по умолчанию (контракт fixture).
    assert har_recorder._mask_secrets is True
    # Путь во временном каталоге pytest — родительская директория должна
    # уже существовать (tmp_path).
    assert har_cassette_path.parent.exists()
    assert har_cassette_path.name.endswith(".har.json")


@pytest.mark.asyncio
async def test_har_recorder_fixture_records_via_mock_transport(
    har_recorder: HARRecorder, har_cassette_path: Path
) -> None:
    """Fixture записывает MockTransport-ответ и переживает round-trip."""

    async def handler(request: httpx.Request) -> httpx.Response:
        # Sensitive header — должен быть замаскирован при записи.
        return httpx.Response(
            200, json={"items": ["a", "b"]}, headers={"x-api-key": "supersecret-token"}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://mock.local"
    ) as client:
        request = client.build_request("GET", "/v1/items")
        response = await client.send(request)
        await response.aread()
        har_recorder._record_response(request, response)

    assert len(har_recorder.cassette.entries) == 1
    har_recorder.cassette.save(har_cassette_path)
    assert har_cassette_path.exists()

    loaded = HARCassette.load(har_cassette_path)
    assert len(loaded.entries) == 1
    entry = loaded.entries[0]
    assert entry.method == "GET"
    assert entry.status == 200
    # Mask-secrets pipeline должен сменить значение api-key на masked.
    assert entry.response_headers.get("x-api-key") != "supersecret-token"
