"""Воспроизведение HAR-кассет через :class:`httpx.MockTransport`.

Загружает кассету (см. :mod:`testkit.recorder`) и собирает функцию
:class:`httpx.MockTransport`, которая отдаёт сохранённые ответы по
совпадению ``method + url``. Используется в unit-тестах, где не нужно
делать живые HTTP-вызовы.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from testkit.recorder import HARCassette

__all__ = ("MissingCassetteEntry", "build_replay_transport", "load_cassette")


class MissingCassetteEntry(LookupError):
    """В кассете нет ответа для запрошенной пары method + url."""

    def __init__(self, method: str, url: str) -> None:
        """Сохраняет method/url для трассировки."""
        self.method = method
        self.url = url
        super().__init__(f"no cassette entry for {method} {url}")


def load_cassette(path: Path | str) -> HARCassette:
    """Загрузить кассету из файла."""
    return HARCassette.load(Path(path))


def build_replay_transport(
    cassette: HARCassette, *, strict: bool = True
) -> httpx.MockTransport:
    """Собрать :class:`httpx.MockTransport` из кассеты.

    При ``strict=True`` (по умолчанию) при отсутствии записи
    выбрасывает :class:`MissingCassetteEntry`. При ``strict=False``
    возвращает ``404 Not Found``.
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in cassette.entries:
        by_key[(entry.method.upper(), str(entry.url))] = {
            "status": entry.status,
            "headers": entry.response_headers,
            "body": entry.response_body or "",
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        key = (request.method.upper(), str(request.url))
        match = by_key.get(key)
        if match is None:
            if strict:
                raise MissingCassetteEntry(request.method, str(request.url))
            return httpx.Response(404)
        return httpx.Response(
            status_code=match["status"],
            headers=match["headers"],
            content=match["body"].encode("utf-8"),
        )

    return httpx.MockTransport(_handler)
