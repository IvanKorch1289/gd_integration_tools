#!/usr/bin/env python3
"""Детерминированный mock-E2E бизнес-workflow'а СКБ (аудит 2026-11-20).

Зачем
-----
Функциональный прогон 19.11.2026 дошёл до ``create-request`` и получил
``Result: false`` → ``order_uuid`` не извлёкся → шаг ``get-result`` был
пропущен. То есть подтверждён был только сетевой путь, а не workflow
«создать заказ → получить id → дождаться результата → скачать документ».

Этот скрипт закрывает workflow детерминированно и локально:

* поднимается mock внешнего сервиса СКБ (реальный HTTP-сервер, состояние
  в памяти: ``pending`` → ``completed``, идемпотентность по ``Id``,
  выдача PDF-документа);
* поднимается настоящее приложение с РЕАЛЬНОЙ цепочкой middleware и
  реальным SKB-роутером (сервис перенаправлен на mock);
* workflow прогоняется настоящим HTTP-клиентом.

Что проверяется
---------------
1. Справочник видов запросов отдаётся (read-путь внешнего сервиса).
2. ``create-request`` → 200, ``Result: true``, получен ``order_uuid``.
3. Первый опрос результата → «в работе» (pending), второй → «готово»
   с данными: polling-контракт внешнего сервиса не сломан.
4. Документ скачивается (``response_type=PDF``), контрольная сумма
   совпадает с ожидаемой — контент, а не только код ответа.
5. Идемпотентность: повторный ``create-request`` с тем же ``Id`` не
   создаёт второй заказ (mock отдаёт тот же ``order_uuid``).
6. Recovery: после «перезапуска» клиента (новое приложение, новый
   HTTP-клиент, новый сервис) результат и документ по тому же
   ``order_uuid`` по-прежнему доступны.
7. ``api-key`` внешнего сервиса действительно передаётся (query-параметр).

Границы применимости
--------------------
Авторизация по ``X-API-Key`` подменяется на уровне FastAPI-зависимости
(проверка ключа требует хранилища ключей; она проверяется отдельно — в
``http_contract_smoke.py`` и в tenant-тестах). Внешний сервис СКБ — mock,
поэтому скрипт доказывает ИСПРАВНОСТЬ СБОРКИ И КОНТРАКТА, но не поведение
реального СКБ-Техно.

Запуск::

    python tools/checks/skb_mock_e2e.py

Код возврата: 0 — workflow пройден полностью, 1 — есть провалы, 2 —
ошибка окружения (сервер или mock не поднялись).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

#: Таймаут одного HTTP-запроса к приложению, секунды.
HTTP_TIMEOUT = 20.0
#: Таймаут ожидания готовности серверов, секунды.
STARTUP_TIMEOUT = 30.0
#: Сколько опросов результата нужно до «готово» (имитация обработки).
POLLS_BEFORE_READY = 1
#: Документ, который выдаёт mock (PDF-подобный байтовый payload).
DOCUMENT_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)
#: Ожидаемая контрольная сумма документа.
DOCUMENT_SHA256 = hashlib.sha256(DOCUMENT_BYTES).hexdigest()
#: Идентификатор вида запроса (справочник mock'а).
REQUEST_KIND_ID = "00000000-0000-0000-0000-000000000002"
#: Канонический номер объекта из функционального прогона.
OBJECT_NUMBER = "77:01:0100001:1234"


@dataclass
class _OrderState:
    """Состояние заказа в mock'е внешнего сервиса.

    Attributes:
        order_uuid: Идентификатор заказа.
        idempotency_key: Ключ идемпотентности (``Id`` запроса).
        polls: Сколько раз опрашивали результат.
        created: True — заказ создан в этом mock'е.
    """

    order_uuid: str
    idempotency_key: str
    polls: int = 0
    created: bool = True


@dataclass
class _MockSKBState:
    """Состояние mock'а внешнего сервиса СКБ.

    Attributes:
        orders: Заказы по ``order_uuid``.
        by_key: ``order_uuid`` по ключу идемпотентности.
        created_count: Сколько заказов реально создано (для проверки
            идемпотентности).
        api_key_seen: Значение ``api-key``, полученное от приложения.
    """

    orders: dict[str, _OrderState] = field(default_factory=dict)
    by_key: dict[str, str] = field(default_factory=dict)
    created_count: int = 0
    api_key_seen: str | None = None


def _make_handler(state: _MockSKBState) -> type[BaseHTTPRequestHandler]:
    """Собрать HTTP-обработчик mock'а СКБ.

    Args:
        state: Общее состояние mock'а.

    Returns:
        Класс обработчика с реализацией ``do_GET``/``do_POST``.
    """

    class _Handler(BaseHTTPRequestHandler):
        """Mock внешнего сервиса СКБ-Техно."""

        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            """Подавить логирование запросов mock'а.

            Args:
                fmt: Формат сообщения.
                args: Аргументы сообщения.
            """
            return None

        def _send(self, payload: bytes, content_type: str) -> None:
            """Отправить ответ.

            Args:
                payload: Тело ответа.
                content_type: Content-Type ответа.
            """
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload: dict[str, Any]) -> None:
            """Отправить JSON-ответ.

            Args:
                payload: Тело ответа.
            """
            self._send(json.dumps(payload).encode("utf-8"), "application/json")

        def do_GET(self) -> None:  # noqa: N802 — имя задано BaseHTTPRequestHandler
            """Обработать GET: справочник видов или результат заказа.

            Returns:
                None.
            """
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            state.api_key_seen = (params.get("api-key") or [None])[0]
            if parsed.path.endswith("/Kinds"):
                self._send_json(
                    [
                        {
                            "Id": REQUEST_KIND_ID,
                            "Name": "cadastral_passport",
                            "Description": "Выписка ЕГРН",
                        }
                    ]
                )
                return
            if "/Result/" in parsed.path:
                order_uuid = parsed.path.rsplit("/", 1)[-1]
                order = state.orders.get(order_uuid)
                if order is None:
                    self._send_json({"Result": False, "Detail": "unknown order"})
                    return
                if (params.get("Type") or [""])[0].upper() == "PDF":
                    self._send(DOCUMENT_BYTES, "application/pdf")
                    return
                order.polls += 1
                if order.polls <= POLLS_BEFORE_READY:
                    self._send_json({"Result": True, "Status": "processing"})
                    return
                self._send_json(
                    {
                        "Result": True,
                        "Status": "completed",
                        "Data": {
                            "Number": OBJECT_NUMBER,
                            "RequestType": REQUEST_KIND_ID,
                        },
                    }
                )
                return
            self._send_json({"Result": False, "Detail": "not found"})

        def do_POST(self) -> None:  # noqa: N802 — имя задано BaseHTTPRequestHandler
            """Обработать POST: создание заказа.

            Returns:
                None.
            """
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            state.api_key_seen = (params.get("api-key") or [None])[0]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw)
            except ValueError:
                body = {}
            if parsed.path.endswith("/Create"):
                idempotency_key = str(
                    body.get("Id") or body.get("OrderId") or uuid.uuid4()
                )
                existing = state.by_key.get(idempotency_key)
                if existing is not None:
                    # Идемпотентность: тот же Id → тот же заказ, новый не создаётся.
                    self._send_json({"Result": True, "order_uuid": existing})
                    return
                order_uuid = str(uuid.uuid4())
                state.orders[order_uuid] = _OrderState(
                    order_uuid=order_uuid, idempotency_key=idempotency_key
                )
                state.by_key[idempotency_key] = order_uuid
                state.created_count += 1
                self._send_json({"Result": True, "order_uuid": order_uuid})
                return
            self._send_json({"Result": False, "Detail": "not found"})

    return _Handler


class _MockSKBServer:
    """Mock внешнего сервиса СКБ (локальный HTTP-сервер)."""

    def __init__(self) -> None:
        """Поднять сервер на свободном порту."""
        self.state = _MockSKBState()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self.state))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        """Базовый URL mock'а (со слэшем — для корректного urljoin).

        Returns:
            URL вида ``http://127.0.0.1:<port>/``.
        """
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def stop(self) -> None:
        """Остановить сервер.

        Returns:
            None.
        """
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Результат одной проверки workflow'а.

    Attributes:
        name: Имя проверки.
        ok: Прошла ли проверка.
        detail: Пояснение.
    """

    name: str
    ok: bool
    detail: str


def _build_app(mock_base_url: str) -> Any:
    """Собрать приложение с реальным SKB-роутером, направленным на mock.

    Args:
        mock_base_url: Базовый URL mock'а внешнего сервиса.

    Returns:
        FastAPI-приложение.
    """
    from fastapi import FastAPI

    from src.backend.entrypoints.api.dependencies.auth import require_api_key
    from src.backend.entrypoints.api.v1.endpoints.skb import router as skb_router
    from src.backend.services.integrations import skb as skb_module

    app = FastAPI()
    app.include_router(skb_router, prefix="/api/v1/skb")
    # Проверка X-API-Key требует хранилища ключей (внешняя инфраструктура) →
    # на уровне зависимости подменяем её: авторизация проверяется отдельно.
    app.dependency_overrides[require_api_key] = lambda: "mock-e2e-client"

    # Сервис СКБ → mock: подменяем prod_url и кладём экземпляр в кэш фабрики.
    patched = skb_module.settings.skb_api.model_copy(update={"prod_url": mock_base_url})
    service = skb_module.APISKBService(skb_settings=patched)
    skb_module._skb_service_instance = service  # noqa: SLF001 — подмена DI-синглтона
    return app


def _free_port() -> int:
    """Найти свободный локальный порт.

    Returns:
        Номер порта.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_ready(base_url: str, deadline: float) -> bool:
    """Дождаться готовности приложения.

    Args:
        base_url: Базовый URL приложения.
        deadline: Момент, после которого ждать бессмысленно (monotonic).

    Returns:
        ``True``, если приложение ответило.
    """
    import httpx

    while time.monotonic() < deadline:
        try:
            httpx.get(f"{base_url}/api/v1/skb/get-kinds", timeout=2.0)
        except httpx.HTTPError:
            time.sleep(0.2)
            continue
        return True
    return False


def _run_workflow(
    base_url: str, idempotency_id: str
) -> tuple[list[CheckResult], str | None]:
    """Прогнать бизнес-workflow против приложения.

    Args:
        base_url: Базовый URL приложения.
        idempotency_id: Ключ идемпотентности (``Id`` запроса).

    Returns:
        Кортеж ``(результаты проверок, order_uuid)``; ``order_uuid`` — ``None``,
        если заказ создать не удалось.
    """
    import httpx

    results: list[CheckResult] = []
    headers = {"X-API-Key": "mock-e2e-key", "Content-Type": "application/json"}

    with httpx.Client(base_url=base_url, timeout=HTTP_TIMEOUT) as client:
        # 1) Справочник видов запросов (read-путь внешнего сервиса).
        response = client.get("/api/v1/skb/get-kinds", headers=headers)
        envelope = response.json() if response.status_code == 200 else {}
        kinds = envelope.get("data") if isinstance(envelope, dict) else None
        results.append(
            CheckResult(
                "reference_kinds_available",
                response.status_code == 200 and isinstance(kinds, list) and bool(kinds),
                f"status={response.status_code} видов={len(kinds) if isinstance(kinds, list) else 0}",
            )
        )

        # 2) Создание заказа. Контракт: Id/OrderId — UUID,
        #    response_type — только 'JSON'/'PDF' (enum ResponseTypeChoices).
        order = {
            "Id": idempotency_id,
            "OrderId": idempotency_id,
            "Number": OBJECT_NUMBER,
            "Priority": 80,
            "RequestType": REQUEST_KIND_ID,
        }
        response = client.post(
            "/api/v1/skb/create-request", json=order, headers=headers
        )
        envelope = response.json() if response.status_code == 200 else {}
        payload = envelope.get("data") if isinstance(envelope, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        order_uuid = payload.get("order_uuid")
        results.append(
            CheckResult(
                "create_request_returns_order_uuid",
                response.status_code == 200
                and bool(payload.get("Result"))
                and bool(order_uuid),
                f"status={response.status_code} Result={payload.get('Result')!r} "
                f"order_uuid={order_uuid!r}",
            )
        )
        if not order_uuid:
            return results, None

        # 3) Первый опрос — «в работе», второй — «готово» с данными.
        response = client.get(
            "/api/v1/skb/get-result",
            params={"order_uuid": order_uuid, "response_type": "JSON"},
            headers=headers,
        )
        envelope = response.json() if response.status_code == 200 else {}
        first = envelope.get("data") if isinstance(envelope, dict) else {}
        if not isinstance(first, dict):
            first = {}
        results.append(
            CheckResult(
                "first_poll_is_pending",
                response.status_code == 200 and first.get("Status") == "processing",
                f"status={response.status_code} Status={first.get('Status')!r}",
            )
        )

        response = client.get(
            "/api/v1/skb/get-result",
            params={"order_uuid": order_uuid, "response_type": "JSON"},
            headers=headers,
        )
        envelope = response.json() if response.status_code == 200 else {}
        second = envelope.get("data") if isinstance(envelope, dict) else {}
        if not isinstance(second, dict):
            second = {}
        results.append(
            CheckResult(
                "second_poll_is_completed",
                response.status_code == 200
                and second.get("Status") == "completed"
                and bool(second.get("Data")),
                f"status={response.status_code} Status={second.get('Status')!r} "
                f"Data={bool(second.get('Data'))}",
            )
        )

        # 4) Документ: байты и контрольная сумма.
        response = client.get(
            "/api/v1/skb/get-result",
            params={"order_uuid": order_uuid, "response_type": "PDF"},
            headers=headers,
        )
        checksum = hashlib.sha256(response.content).hexdigest()
        results.append(
            CheckResult(
                "document_downloaded_with_checksum",
                response.status_code == 200
                and response.content == DOCUMENT_BYTES
                and checksum == DOCUMENT_SHA256,
                f"status={response.status_code} "
                f"content-type={response.headers.get('content-type')!r} "
                f"sha256={checksum[:16]}… ожидался {DOCUMENT_SHA256[:16]}…",
            )
        )

        # 5) Идемпотентность: тот же Id → тот же order_uuid, заказ не создан.
        response = client.post(
            "/api/v1/skb/create-request", json=order, headers=headers
        )
        envelope = response.json() if response.status_code == 200 else {}
        repeat = envelope.get("data") if isinstance(envelope, dict) else {}
        if not isinstance(repeat, dict):
            repeat = {}
        results.append(
            CheckResult(
                "create_request_is_idempotent",
                response.status_code == 200 and repeat.get("order_uuid") == order_uuid,
                f"status={response.status_code} "
                f"order_uuid={repeat.get('order_uuid')!r} (ожидался {order_uuid!r})",
            )
        )

    return results, order_uuid


def _run_recovery(base_url: str, order_uuid: str) -> list[CheckResult]:
    """Проверить, что заказ доживает до конца после «перезапуска» клиента.

    Новое приложение (новый сервис, новый HTTP-клиент) запрашивает результат
    и документ по заказу, созданному до перезапуска. Состояние заказа хранит
    внешний сервис — поэтому результат должен быть доступен.

    Args:
        base_url: Базовый URL нового приложения.
        order_uuid: Идентификатор заказа, созданного до перезапуска.

    Returns:
        Список результатов проверок.
    """
    import httpx

    headers = {"X-API-Key": "mock-e2e-key", "Content-Type": "application/json"}
    results: list[CheckResult] = []
    with httpx.Client(base_url=base_url, timeout=HTTP_TIMEOUT) as client:
        response = client.get(
            "/api/v1/skb/get-result",
            params={"order_uuid": order_uuid, "response_type": "JSON"},
            headers=headers,
        )
        envelope = response.json() if response.status_code == 200 else {}
        payload = envelope.get("data") if isinstance(envelope, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        results.append(
            CheckResult(
                "recovery_result_still_available",
                response.status_code == 200 and payload.get("Status") == "completed",
                f"status={response.status_code} Status={payload.get('Status')!r}",
            )
        )

        response = client.get(
            "/api/v1/skb/get-result",
            params={"order_uuid": order_uuid, "response_type": "PDF"},
            headers=headers,
        )
        checksum = hashlib.sha256(response.content).hexdigest()
        results.append(
            CheckResult(
                "recovery_document_still_available",
                response.status_code == 200 and checksum == DOCUMENT_SHA256,
                f"status={response.status_code} sha256={checksum[:16]}…",
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    """Точка входа: mock СКБ + приложение + workflow + отчёт.

    Args:
        argv: Аргументы командной строки (по умолчанию ``sys.argv[1:]``).

    Returns:
        0 — workflow пройден; 1 — есть провалы; 2 — ошибка окружения.
    """
    parser = argparse.ArgumentParser(
        description="Детерминированный mock-E2E бизнес-workflow'а СКБ"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Адрес приложения (по умолчанию 127.0.0.1)"
    )
    args = parser.parse_args(argv)

    import uvicorn

    from src.backend.services.integrations import skb as skb_module

    mock = _MockSKBServer()
    port = _free_port()
    base_url = f"http://{args.host}:{port}"
    idempotency_id = str(uuid.uuid4())

    # Захват ДО подмены: `_build_app` кладёт mock-сервис в кэш фабрики,
    # и если захватить синглтон после, восстановление в `finally` вернуло
    # бы mock вместо исходного значения — глобальное состояние утекало
    # бы в pytest-сессию (независимое ревью 2026-11-23, MINOR-3).
    previous_service = skb_module._skb_service_instance  # noqa: SLF001
    app = _build_app(mock.base_url)
    config = uvicorn.Config(
        app, host=args.host, port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    results: list[CheckResult] = []
    try:
        if not _wait_ready(base_url, time.monotonic() + STARTUP_TIMEOUT):
            print("ОШИБКА: приложение не поднялось", file=sys.stderr)
            return 2

        workflow_results, order_uuid = _run_workflow(base_url, idempotency_id)
        results.extend(workflow_results)

        # 6) Recovery: «перезапуск» клиента — новое приложение, новый
        # сервис, новый HTTP-клиент. Заказ и его результат должны остаться
        # доступны.
        #
        # Первое приложение НЕ останавливается до старта второго: его
        # lifespan закрывает общий DI-пул HTTP-клиента, и запросы второго
        # приложения к mock'у падали бы с «TCPTransport closed»
        # (независимое ревью 2026-11-23, MINOR-11).
        recovery_port = _free_port()
        recovery_url = f"http://{args.host}:{recovery_port}"
        recovery_app = _build_app(mock.base_url)
        recovery_config = uvicorn.Config(
            recovery_app,
            host=args.host,
            port=recovery_port,
            log_level="warning",
            access_log=False,
        )
        recovery_server = uvicorn.Server(recovery_config)
        recovery_thread = threading.Thread(target=recovery_server.run, daemon=True)
        recovery_thread.start()
        try:
            if not _wait_ready(recovery_url, time.monotonic() + STARTUP_TIMEOUT):
                results.append(
                    CheckResult(
                        "recovery_after_restart", False, "приложение не поднялось"
                    )
                )
            elif order_uuid:
                results.extend(_run_recovery(recovery_url, order_uuid))
                results.append(
                    CheckResult(
                        "recovery_after_restart",
                        mock.state.created_count == 1,
                        f"заказов создано в mock'е: {mock.state.created_count} "
                        "(повторный create-request не создал второй)",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "recovery_after_restart",
                        False,
                        "заказ не создан — recovery нечего проверять",
                    )
                )
        finally:
            recovery_server.should_exit = True
            recovery_thread.join(timeout=10)

        results.append(
            CheckResult(
                "api_key_forwarded_to_external_service",
                bool(mock.state.api_key_seen),
                f"api-key получен mock'ом: {bool(mock.state.api_key_seen)}",
            )
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        skb_module._skb_service_instance = previous_service  # noqa: SLF001
        mock.stop()

    width = max(len(r.name) for r in results)
    print(f"SKB mock E2E: {base_url} (mock {mock.base_url})")
    for result in results:
        mark = "OK  " if result.ok else "FAIL"
        print(f"  [{mark}] {result.name.ljust(width)}  {result.detail}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\nПРОВАЛЕНО проверок: {len(failed)} из {len(results)}", file=sys.stderr)
        return 1
    print(f"\nWorkflow пройден полностью: {len(results)} проверок")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
