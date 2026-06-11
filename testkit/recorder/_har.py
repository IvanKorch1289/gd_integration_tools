"""HAR-кассеты для записи внешних HTTP-запросов в тестах.

Запись делает :class:`HARRecorder`: оборачивает существующий
``httpx.AsyncClient`` или ``httpx.Client`` и сохраняет каждый
запрос/ответ в JSON формата, совместимого с HAR 1.2 (минимальное
подмножество). Воспроизведение — :func:`testkit.replay.load_cassette`.

С S10 Wave 1 рекордер по умолчанию маскирует секреты в headers и body
(см. :mod:`testkit.recorder.secrets_mask`). Опциональный параметр
``mask_secrets=False`` отключает маскирование (только для отладки).

Зависимостей вне stdlib + ``httpx`` нет, чтобы recorder работал в
любом окружении тестов.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from testkit.recorder.secrets_mask import mask_request_body, mask_response_headers

__all__ = ("HARCassette", "HAREntry", "HARRecorder", "record_session")


@dataclass(slots=True)
class HAREntry:
    """Одна запись HAR-кассеты (запрос + ответ)."""

    method: str
    url: str
    status: int
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    request_body: str | None = None
    response_body: str | None = None


@dataclass(slots=True)
class HARCassette:
    """Сериализуемая кассета — список :class:`HAREntry`."""

    entries: list[HAREntry] = field(default_factory=list)

    def to_json(self) -> str:
        """Сериализовать кассету в JSON-строку."""
        payload = {"version": "1.2", "entries": [asdict(e) for e in self.entries]}
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, data: str) -> HARCassette:
        """Десериализовать кассету из JSON-строки."""
        raw = json.loads(data)
        entries = [HAREntry(**e) for e in raw.get("entries", [])]
        return cls(entries=entries)

    def save(self, path: Path) -> None:
        """Сохранить кассету в файл."""
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> HARCassette:
        """Загрузить кассету из файла."""
        return cls.from_json(path.read_text(encoding="utf-8"))


class HARRecorder:
    """Перехватывает HTTP-вызовы и складывает их в :class:`HARCassette`.

    Используется как контекст-менеджер; внутри отдаёт
    ``httpx.AsyncClient`` с :class:`httpx.AsyncBaseTransport` обёрткой,
    которая сохраняет каждый запрос/ответ.

    Args:
        base_url: префикс для всех записей (опциональный).
        mask_secrets: если ``True`` (default), значения секретных
            headers/body-полей заменяются на ``"<masked>"`` перед
            сохранением в кассету. Отключать только для локальной
            отладки — кассеты с секретами не должны попадать в репо.
    """

    def __init__(
        self, *, base_url: str | None = None, mask_secrets: bool = True
    ) -> None:
        """Инициализирует recorder с пустой кассетой."""
        self.cassette = HARCassette()
        self._base_url = base_url
        self._mask_secrets = mask_secrets

    def _record_response(
        self, request: httpx.Request, response: httpx.Response
    ) -> None:
        """Сохраняет request/response в кассету (с маскированием при включённом флаге)."""
        try:
            req_body = request.content.decode("utf-8") if request.content else None
        except UnicodeDecodeError:
            req_body = None
        try:
            resp_body = response.text if response.content else None
        except UnicodeDecodeError:
            resp_body = None

        req_headers = dict(request.headers)
        resp_headers = dict(response.headers)

        if self._mask_secrets:
            req_headers = mask_response_headers(req_headers)
            resp_headers = mask_response_headers(resp_headers)
            req_body = mask_request_body(
                req_body, content_type=req_headers.get("content-type")
            )
            resp_body = mask_request_body(
                resp_body, content_type=resp_headers.get("content-type")
            )

        self.cassette.entries.append(
            HAREntry(
                method=request.method,
                url=str(request.url),
                status=response.status_code,
                request_headers=req_headers,
                response_headers=resp_headers,
                request_body=req_body,
                response_body=resp_body,
            )
        )

    @asynccontextmanager
    async def async_client(self, **kwargs: Any):
        """Async-контекст: ``httpx.AsyncClient`` с записью."""
        recorder = self

        class _Transport(httpx.AsyncBaseTransport):
            def __init__(self) -> None:
                self._inner = httpx.AsyncHTTPTransport()

            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                response = await self._inner.handle_async_request(request)
                # читаем body заранее, чтобы кассета была самодостаточной
                await response.aread()
                recorder._record_response(request, response)
                return response

            async def aclose(self) -> None:
                await self._inner.aclose()

        async with httpx.AsyncClient(
            transport=_Transport(), base_url=self._base_url or "", **kwargs
        ) as client:
            yield client

    @contextmanager
    def sync_client(self, **kwargs: Any):
        """Sync-контекст: ``httpx.Client`` с записью."""
        recorder = self

        class _Transport(httpx.BaseTransport):
            def __init__(self) -> None:
                self._inner = httpx.HTTPTransport()

            def handle_request(self, request: httpx.Request) -> httpx.Response:
                response = self._inner.handle_request(request)
                response.read()
                recorder._record_response(request, response)
                return response

            def close(self) -> None:
                self._inner.close()

        with httpx.Client(
            transport=_Transport(), base_url=self._base_url or "", **kwargs
        ) as client:
            yield client


@asynccontextmanager
async def record_session(
    *, base_url: str | None = None, mask_secrets: bool = True, **kwargs: Any
):
    """Удобная shortcut-обёртка: ``async with record_session() as (client, cassette):``."""
    recorder = HARRecorder(base_url=base_url, mask_secrets=mask_secrets)
    async with recorder.async_client(**kwargs) as client:
        yield client, recorder.cassette
