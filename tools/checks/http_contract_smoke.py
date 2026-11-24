#!/usr/bin/env python3
"""HTTP contract smoke — проверка HTTP-контракта на ЖИВОМ сервере.

Зачем
-----
Юнит-тесты проверяют middleware изолированно, а отчёт о готовности
требует проверки на реальном HTTP-сервере: заголовки кэша, условный GET,
SSE-стриминг и сжатие ведут себя иначе под uvicorn (h11), чем в
ASGI-вызовах тестов. Этот скрипт поднимает настоящий сервер с РЕАЛЬНОЙ
цепочкой middleware проекта и проверяет контракт настоящим HTTP-клиентом.

Рантайм выбирается флагом ``--server``:

* ``uvicorn`` (по умолчанию) — dev-рантайм;
* ``granian`` — ПРОДОВЫЙ рантайм (ADR-0059). Контракт HTTP-сервера
  проверяется на обоих: поведение SSE, gzip и условного GET зависит от
  HTTP-стека сервера, а не только от middleware (аудит 2026-11-23,
  ЭТАП 2.3).

Что проверяется (дефекты аудита 2026-11-20, §3.1-3.2)
-------------------------------------------------------
1. ``Cache-Control`` персонализированного ответа — ``private`` (не
   ``public``): ``public`` допустим только по явному opt-in endpoint'а.
2. Политика endpoint'а (``no-store``) не перетирается middleware.
3. Условный GET → 304 с тем же ETag и той же политикой кэша.
4. SSE отдаёт ПЕРВЫЙ чанк до завершения producer'а (инкрементально).
5. Сжатое тело после декодирования совпадает с несжатым (чанки не теряются).
6. Тело больше лимита кэша не буферизуется (нет ETag) и приходит целиком.
7. Несовпадение tenant (заголовок vs аутентифицированный) → 403.

Запуск::

    python tools/checks/http_contract_smoke.py

Запуск::

    python tools/checks/http_contract_smoke.py --server granian

Код возврата: 0 — все проверки пройдены, 1 — есть провалы, 2 — ошибка
окружения (сервер не поднялся).
"""

from __future__ import annotations

import argparse
import gzip
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tools.checks.http_contract_app import (
    AUTH_TENANT,
    OTHER_TENANT,
    SSE_EVENTS,
    SSE_INTERVAL,
    build_app,
)

#: Таймаут одного HTTP-запроса, секунды.
HTTP_TIMEOUT = 15.0
#: Таймаут ожидания готовности сервера, секунды.
STARTUP_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Результат одной проверки HTTP-контракта.

    Attributes:
        name: Имя проверки.
        ok: Прошла ли проверка.
        detail: Пояснение (что именно увидели).
    """

    name: str
    ok: bool
    detail: str


def _free_port() -> int:
    """Найти свободный локальный порт.

    Returns:
        Номер порта.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    base_url: str, path: str, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    """Выполнить HTTP-запрос.

    Args:
        base_url: Базовый URL сервера.
        path: Путь ресурса.
        headers: Заголовки запроса.

    Returns:
        Кортеж ``(статус, заголовки ответа, тело)``.

    Raises:
        RuntimeError: Сервер недоступен.
    """
    request = Request(f"{base_url}{path}", headers=headers or {})  # noqa: S310
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:  # noqa: S310
            return (
                int(response.status),
                {k.lower(): v for k, v in response.headers.items()},
                response.read(),
            )
    except HTTPError as exc:  # 4xx/5xx — ответ, а не сбой
        return (
            int(exc.code),
            {k.lower(): v for k, v in exc.headers.items()},
            exc.read(),
        )
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"запрос {path} не удался: {exc}") from exc


def _sse_timeline(base_url: str, path: str) -> tuple[float, float, int]:
    """Измерить тайминг SSE-потока.

    Args:
        base_url: Базовый URL сервера.
        path: Путь SSE-ресурса.

    Returns:
        Кортеж ``(время до первого события, общее время, число событий)``.

    Raises:
        RuntimeError: Поток недоступен или не содержит событий.
    """
    request = Request(  # noqa: S310 — локальный http-URL smoke-сервера
        f"{base_url}{path}", headers={"Accept": "text/event-stream"}
    )
    started = time.monotonic()
    first_at: float | None = None
    events = 0
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:  # noqa: S310
            for raw in response:
                if raw.startswith(b"data:"):
                    events += 1
                    if first_at is None:
                        first_at = time.monotonic()
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"SSE-поток {path} недоступен: {exc}") from exc
    total = time.monotonic() - started
    if first_at is None:
        raise RuntimeError("SSE-поток не отдал ни одного события")
    return first_at - started, total, events


def run_checks(base_url: str) -> list[CheckResult]:
    """Выполнить все проверки HTTP-контракта.

    Args:
        base_url: Базовый URL поднятого сервера.

    Returns:
        Список результатов по каждой проверке.
    """
    results: list[CheckResult] = []

    status, headers, _ = _request(base_url, "/json")
    cache_control = headers.get("cache-control", "")
    results.append(
        CheckResult(
            "cache_policy_never_public",
            status == 200 and "public" not in cache_control,
            f"status={status} cache-control={cache_control!r} "
            "(public недопустим для персонализированного ответа)",
        )
    )
    results.append(
        CheckResult(
            "set_cookie_forces_no_store",
            "set-cookie" in headers and "no-store" in cache_control,
            f"set-cookie={'yes' if 'set-cookie' in headers else 'no'} "
            f"cache-control={cache_control!r} (CSRF выдаёт cookie → no-store)",
        )
    )
    results.append(
        CheckResult(
            "etag_present", bool(headers.get("etag")), f"etag={headers.get('etag')!r}"
        )
    )
    results.append(
        CheckResult(
            "tenant_header_matches_auth_tenant",
            headers.get("x-tenant-id") == AUTH_TENANT,
            f"x-tenant-id={headers.get('x-tenant-id')!r} (ожидался {AUTH_TENANT!r})",
        )
    )

    status, headers, _ = _request(base_url, "/json-no-store")
    cache_control = headers.get("cache-control", "")
    results.append(
        CheckResult(
            "endpoint_no_store_preserved",
            status == 200 and "no-store" in cache_control,
            f"status={status} cache-control={cache_control!r}",
        )
    )

    etag = headers.get("etag", "")
    status, headers, body = _request(base_url, "/json")
    etag = headers.get("etag", etag)
    status, headers, body = _request(base_url, "/json", headers={"If-None-Match": etag})
    results.append(
        CheckResult(
            "conditional_get_304",
            status == 304 and headers.get("etag") == etag and not body,
            f"status={status} etag={headers.get('etag')!r} body_len={len(body)}",
        )
    )

    try:
        first_at, total, events = _sse_timeline(base_url, "/sse")
    except RuntimeError as exc:
        results.append(CheckResult("sse_streams_incrementally", False, str(exc)))
    else:
        producer_span = SSE_INTERVAL * (SSE_EVENTS - 1)
        # Инвариант: первое событие приходит ЗНАЧИТЕЛЬНО раньше конца потока.
        # Сравнение относительное (доля от общего времени), а не абсолютное:
        # на нагруженном CI-раннере весь поток смещается, но соотношение
        # «первое событие vs конец потока» сохраняется. На старой
        # (буферизующей) реализации первое событие приходит в конец потока
        # (first_at == total) — проверка падает.
        incremental = events == SSE_EVENTS and first_at < total * 0.75
        results.append(
            CheckResult(
                "sse_streams_incrementally",
                incremental,
                f"событий={events} первое через {first_at:.2f}с, весь поток "
                f"{total:.2f}с (producer работает ~{producer_span:.2f}с)",
            )
        )

    _, plain_headers, plain_body = _request(base_url, "/json-large")
    status, gzip_headers, gzip_body = _request(
        base_url, "/json-large", headers={"Accept-Encoding": "gzip"}
    )
    try:
        decoded = gzip.decompress(gzip_body)
    except OSError:  # gzip.BadGzipFile — подкласс OSError
        decoded = b""
    results.append(
        CheckResult(
            "gzip_body_intact",
            status == 200
            and gzip_headers.get("content-encoding") == "gzip"
            and bool(decoded)
            and decoded == plain_body,
            f"status={status} content-encoding={gzip_headers.get('content-encoding')!r} "
            f"распакованный={len(decoded)} байт, совпадение с несжатым: "
            f"{decoded == plain_body}",
        )
    )
    results.append(
        CheckResult(
            "large_body_not_cached",
            status == 200 and "etag" not in gzip_headers,
            f"etag={gzip_headers.get('etag')!r} (лимит кэша превышен → passthrough)",
        )
    )

    status, headers, body = _request(
        base_url, "/json", headers={"X-Tenant-ID": OTHER_TENANT}
    )
    raw = body[:200].decode("latin-1", errors="replace")
    results.append(
        CheckResult(
            "tenant_mismatch_denied",
            status == 403 and "tenant_mismatch" in raw,
            f"status={status} body={raw[:80]!r}",
        )
    )

    return results


def _wait_ready(base_url: str, deadline: float) -> bool:
    """Дождаться готовности сервера.

    Args:
        base_url: Базовый URL сервера.
        deadline: Момент, после которого ждать бессмысленно (monotonic).

    Returns:
        ``True``, если сервер ответил.
    """
    while time.monotonic() < deadline:
        try:
            _request(base_url, "/json")
        except RuntimeError:
            time.sleep(0.2)
            continue
        return True
    return False


def _start_uvicorn(
    app_factory: Callable[[], Any], host: str, port: int
) -> tuple[Callable[[], None], Callable[[], None]]:
    """Поднять uvicorn в фоновом потоке.

    Args:
        app_factory: Фабрика ASGI-приложения.
        host: Адрес bind'а.
        port: Порт.

    Returns:
        Пара ``(stop, join)`` — stop останавливает сервер, join дожидается
        завершения фонового потока.
    """
    import uvicorn

    config = uvicorn.Config(
        app_factory(), host=host, port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    def _stop() -> None:
        # У uvicorn ``Server.shutdown`` — coroutine, вызывать его извне
        # нельзя; остановка выполняется флагом ``should_exit``.
        server.should_exit = True

    return _stop, lambda: thread.join(timeout=10)


def _start_granian(
    app_factory: Callable[[], Any], host: str, port: int
) -> tuple[Callable[[], None], Callable[[], None]]:
    """Поднять Granian (продовый рантайм) отдельным процессом.

    Granian устанавливает signal-handlers, поэтому в потоке не запускается
    («signal only works in main thread») — как в production, процесс
    поднимается отдельно (ADR-0059, ``tools/granian_runner.py``).

    Args:
        app_factory: Фабрика ASGI-приложения (в этом процессе не нужна:
            приложение собирается в дочернем процессе).
        host: Адрес bind'а.
        port: Порт.

    Returns:
        Пара ``(stop, join)`` — stop останавливает сервер, join дожидается
        завершения процесса.
    """
    del app_factory  # приложение собирается в дочернем процессе
    cmd = [
        sys.executable,
        "-m",
        "granian",
        "--interface",
        "asgi",
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        "1",
        "--no-access-log",
        "tools.checks.http_contract_app:app",
    ]
    process = subprocess.Popen(  # noqa: S603  # argv из контролируемых значений
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    def _stop() -> None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    return _stop, lambda: process.wait(timeout=10)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: поднять сервер, прогнать проверки, напечатать отчёт.

    Args:
        argv: Аргументы командной строки (по умолчанию ``sys.argv[1:]``).

    Returns:
        0 — все проверки пройдены; 1 — есть провалы; 2 — сервер не поднялся.
    """
    parser = argparse.ArgumentParser(
        description="HTTP contract smoke на живом HTTP-сервере"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Адрес сервера (по умолчанию 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=0, help="Порт (0 — свободный автоматически)"
    )
    parser.add_argument(
        "--server",
        choices=("uvicorn", "granian"),
        default="uvicorn",
        help="HTTP-рантайм: uvicorn (dev) или granian (прод, ADR-0059)",
    )
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    base_url = f"http://{args.host}:{port}"

    starter = _start_granian if args.server == "granian" else _start_uvicorn
    stop, join = starter(build_app, args.host, port)

    if not _wait_ready(base_url, time.monotonic() + STARTUP_TIMEOUT):
        stop()
        print("ОШИБКА: сервер не поднялся", file=sys.stderr)
        return 2

    try:
        results = run_checks(base_url)
    except RuntimeError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    finally:
        stop()
        join()

    width = max(len(r.name) for r in results)
    print(f"HTTP contract smoke ({args.server}): {base_url}")
    for result in results:
        mark = "OK  " if result.ok else "FAIL"
        print(f"  [{mark}] {result.name.ljust(width)}  {result.detail}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\nПРОВАЛЕНО проверок: {len(failed)} из {len(results)}", file=sys.stderr)
        return 1
    print(f"\nВсе проверки пройдены: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
