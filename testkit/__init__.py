"""Testkit — переиспользуемые pytest-фикстуры и утилиты для тестов.

Назначение пакета:
    Содержит фабрики тестовых сертификатов, контейнеров IdP (Keycloak),
    HAR-рекордер для записи внешних HTTP-вызовов, фасад запуска DSL-route
    в изоляции, контейнерные фикстуры (Postgres/Redis/Temporal/Toxiproxy)
    и инструменты построения tenant-контекста.

Публичный API:
    HARCassette, HAREntry, HARRecorder, record_session — HAR-рекордер
    (см. :mod:`testkit.recorder`).
    build_replay_transport, load_cassette, MissingCassetteEntry —
    воспроизведение HAR через httpx.MockTransport (см. :mod:`testkit.replay`).
    RouteRunner, RouteRunResult — изолированный запуск DSL-route
    (см. :mod:`testkit.route_runner`).

Pytest-фикстуры регистрируются автоматически через entry-point
``testkit.pytest_plugin`` (см. :mod:`testkit.pytest_plugin`).
"""

from __future__ import annotations

from testkit.recorder import HARCassette, HAREntry, HARRecorder, record_session
from testkit.replay import MissingCassetteEntry, build_replay_transport, load_cassette
from testkit.route_runner import RouteRunner, RouteRunResult

__all__ = (
    "HARCassette",
    "HAREntry",
    "HARRecorder",
    "MissingCassetteEntry",
    "RouteRunResult",
    "RouteRunner",
    "build_replay_transport",
    "load_cassette",
    "record_session",
)
