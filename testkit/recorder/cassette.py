"""VCR-style cassette decorator для testkit (Sprint 10 K5 W6, EXT-5.5).

Декоратор ``@cassette(path)`` оборачивает test-функцию: при первом
запуске запись HTTP-вызовов в YAML-файл, при повторных запусках —
replay из этого файла без реальных сетевых обращений.

Поддерживается:

* HTTP / HTTPS (через httpx Transport);
* SOAP / gRPC, использующие httpx как транспорт (REST-like wrappers);
* Async и sync тесты.

Использование::

    from testkit.recorder.cassette import cassette

    @cassette("tests/cassettes/bki_query.yaml")
    async def test_bki_returns_score(client):
        # client — httpx.AsyncClient с активной кассетой
        resp = await client.get("https://bki.local/api/score?id=42")
        assert resp.status_code == 200

Режимы (через kwarg ``mode``):

* ``"auto"`` (default): запись если файла нет, иначе replay;
* ``"record"``: всегда запись (перезапись);
* ``"replay"``: только replay (FileNotFoundError если файла нет).
"""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml

from testkit.recorder._har import HARCassette, HAREntry, HARRecorder
from testkit.recorder.secrets_mask import mask_request_body, mask_response_headers

__all__ = (
    "cassette",
    "load_cassette",
    "save_cassette",
    "CassetteMode",
)

CassetteMode = Literal["auto", "record", "replay"]


def save_cassette(path: Path, cas: HARCassette) -> None:
    """Сериализует cassette в YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": "1.0",
        "entries": [asdict(entry) for entry in cas.entries],
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def load_cassette(path: Path) -> HARCassette:
    """Десериализует cassette из YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = [HAREntry(**entry) for entry in raw.get("entries", [])]
    return HARCassette(entries=entries)


class _ReplayTransport(httpx.AsyncBaseTransport):
    """HTTPX transport, воспроизводящий записанные ответы по url/method."""

    def __init__(self, cas: HARCassette) -> None:
        """Создаёт map (method, url) -> HAREntry для O(1) поиска."""
        self._cas = cas
        self._map: dict[tuple[str, str], HAREntry] = {
            (e.method.upper(), e.url): e for e in cas.entries
        }

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        """Возвращает записанный ответ или 599 'cassette miss'."""
        key = (request.method.upper(), str(request.url))
        entry = self._map.get(key)
        if entry is None:
            return httpx.Response(
                status_code=599,
                content=json.dumps(
                    {"error": "cassette_miss", "url": str(request.url)}
                ).encode("utf-8"),
                headers={"content-type": "application/json"},
                request=request,
            )
        body = (entry.response_body or "").encode("utf-8")
        return httpx.Response(
            status_code=entry.status,
            content=body,
            headers=entry.response_headers,
            request=request,
        )


def _client_param_name(fn: Callable) -> str:
    """Возвращает имя параметра, в который подставлять httpx.AsyncClient."""
    sig = inspect.signature(fn)
    candidates = ("client", "http_client", "async_client")
    for name in candidates:
        if name in sig.parameters:
            return name
    # fallback на первый параметр после self/cls/fixtures.
    for name in sig.parameters:
        if name not in {"self", "cls"}:
            return name
    raise TypeError(
        f"@cassette: функция {fn.__name__} не имеет параметра для client"
    )


def cassette(
    path: str | Path,
    *,
    mode: CassetteMode = "auto",
    mask_secrets: bool = True,
) -> Callable:
    """Декоратор @cassette — оборачивает тест в record/replay HTTP.

    Args:
        path: путь к YAML-кассете (относительно CWD).
        mode: ``auto`` | ``record`` | ``replay``.
        mask_secrets: если ``True`` (default), на запись маскируются
            заголовки/тела с известными секретными ключами.

    Returns:
        Декоратор, который оборачивает test-функцию.
    """
    cas_path = Path(path)

    def _decorator(fn: Callable) -> Callable:
        is_async = inspect.iscoroutinefunction(fn)
        client_param = _client_param_name(fn)

        if is_async:

            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                replay_mode = _decide_mode(cas_path, mode)
                if replay_mode == "replay":
                    cas = load_cassette(cas_path)
                    transport = _ReplayTransport(cas)
                    async with httpx.AsyncClient(transport=transport) as client:
                        kwargs[client_param] = client
                        return await fn(*args, **kwargs)

                # record mode
                recorder = HARRecorder(mask_secrets=mask_secrets)
                async with recorder.async_client() as client:
                    kwargs[client_param] = client
                    result = await fn(*args, **kwargs)
                save_cassette(cas_path, recorder.cassette)
                return result

            return _async_wrapper

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            replay_mode = _decide_mode(cas_path, mode)
            if replay_mode == "replay":
                cas = load_cassette(cas_path)
                # sync replay: используем MockTransport
                handler = _build_sync_handler(cas)
                with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                    kwargs[client_param] = client
                    return fn(*args, **kwargs)

            recorder = HARRecorder(mask_secrets=mask_secrets)
            with recorder.sync_client() as client:
                kwargs[client_param] = client
                result = fn(*args, **kwargs)
            save_cassette(cas_path, recorder.cassette)
            return result

        return _sync_wrapper

    return _decorator


def _decide_mode(path: Path, mode: CassetteMode) -> CassetteMode:
    """Резолвит ``auto`` → ``record``/``replay`` исходя из наличия файла."""
    if mode == "record":
        return "record"
    if mode == "replay":
        if not path.is_file():
            raise FileNotFoundError(f"@cassette: replay-режим, но {path} не существует")
        return "replay"
    # auto:
    return "replay" if path.is_file() else "record"


def _build_sync_handler(cas: HARCassette):
    """Возвращает callable для httpx.MockTransport, отдающий записанные ответы."""

    cmap: dict[tuple[str, str], HAREntry] = {
        (e.method.upper(), e.url): e for e in cas.entries
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        """Sync handler для httpx.MockTransport — отдаёт записанный ответ.

        Args:
            request: httpx.Request (method + URL).

        Returns:
            httpx.Response с данными из CASSETTE или 599 при miss.
        """
        key = (request.method.upper(), str(request.url))
        entry = cmap.get(key)
        if entry is None:
            return httpx.Response(599, json={"error": "cassette_miss"})
        body = (entry.response_body or "").encode("utf-8")
        return httpx.Response(
            entry.status,
            content=body,
            headers=entry.response_headers,
        )

    return _handler


# Re-export секрет-маскеров для convenience.
__all__ = (
    "cassette",
    "CassetteMode",
    "load_cassette",
    "mask_request_body",
    "mask_response_headers",
    "save_cassette",
)
