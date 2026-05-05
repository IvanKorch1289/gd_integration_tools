"""Unit-тесты Wave 2.5: ``LogSink`` ABC, backends, router и circuit-breaker.

Покрытие (DoD ≥ 8 тестов):

1. ``ConsoleJsonLogSink.write`` — успех, JSON-валиден, newline.
2. ``ConsoleJsonLogSink.write`` — graceful обработка не-JSON-сериализуемого.
3. ``DiskRotatingLogSink.write`` — создаёт файл и пишет одну строку.
4. ``DiskRotatingLogSink`` — flush + close без ошибок.
5. ``GraylogGelfLogSink`` — UDP-отправка через mock-socket.
6. ``GraylogGelfLogSink`` — circuit-breaker open → ``is_healthy=False``,
   запись пропускается.
7. ``build_sinks_for_profile`` — корректный набор для каждого профиля.
8. ``SinkRouter.dispatch`` — fan-out во все healthy sinks параллельно.
9. ``SinkRouter.dispatch`` — отказ одного sink не ломает остальные.
"""

# ruff: noqa: S101

from __future__ import annotations

import io
import socket
from pathlib import Path
from typing import Any
from unittest.mock import patch

import orjson
import pytest

from src.backend.core.config.profile import AppProfileChoices
from src.backend.core.interfaces.log_sink import LogSink
from src.backend.infrastructure.logging.backends import (
    ConsoleJsonLogSink,
    DiskRotatingLogSink,
    GraylogGelfLogSink,
)
from src.backend.infrastructure.logging.router import (
    SinkRouter,
    build_sinks_for_profile,
)
from src.backend.infrastructure.resilience.breaker import BreakerSpec


# ---------------------------------------------------------------------- ConsoleJson
@pytest.mark.asyncio
async def test_console_json_writes_valid_json_line() -> None:
    """``ConsoleJsonLogSink`` пишет одну валидную JSON-строку с переводом строки."""
    stream = io.StringIO()
    sink = ConsoleJsonLogSink(stream=stream)
    await sink.write({"event": "hello", "level": "info", "n": 42})
    output = stream.getvalue()
    assert output.endswith("\n")
    parsed = orjson.loads(output.strip())
    assert parsed == {"event": "hello", "level": "info", "n": 42}
    assert sink.is_healthy is True
    assert sink.name == "console_json"


@pytest.mark.asyncio
async def test_console_json_handles_non_serializable_value() -> None:
    """Не-JSON-типы (например ``object``) приводятся к строке без падения."""
    stream = io.StringIO()
    sink = ConsoleJsonLogSink(stream=stream)

    class Custom:
        def __repr__(self) -> str:
            return "<Custom>"

    await sink.write({"event": "x", "obj": Custom()})
    parsed = orjson.loads(stream.getvalue().strip())
    assert parsed["event"] == "x"
    assert "Custom" in parsed["obj"]


# ---------------------------------------------------------------------- DiskRotating
@pytest.mark.asyncio
async def test_disk_rotating_writes_file(tmp_path: Path) -> None:
    """``DiskRotatingLogSink`` создаёт файл и пишет одну запись."""
    log_path = tmp_path / "subdir" / "app.jsonl"
    sink = DiskRotatingLogSink(path=log_path, max_bytes=1024, backup_count=2)
    await sink.write({"event": "boot", "level": "info"})
    await sink.flush()
    await sink.close()

    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8").strip()
    assert content
    parsed = orjson.loads(content.splitlines()[0])
    assert parsed["event"] == "boot"


@pytest.mark.asyncio
async def test_disk_rotating_close_idempotent(tmp_path: Path) -> None:
    """Повторный ``close`` не должен падать; sink остаётся в корректном состоянии."""
    sink = DiskRotatingLogSink(path=tmp_path / "log.jsonl")
    await sink.close()
    await sink.close()
    assert sink.name == "disk_rotating"


# ---------------------------------------------------------------------- Graylog
@pytest.mark.asyncio
async def test_graylog_udp_sends_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """UDP-отправка использует ``socket.sendto`` и держит sink healthy."""
    captured: dict[str, Any] = {}

    class _FakeSocket:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        def sendto(self, payload: bytes, addr: tuple[str, int]) -> None:
            captured["payload"] = payload
            captured["addr"] = addr

        def close(self) -> None: ...

    monkeypatch.setattr(socket, "socket", _FakeSocket)
    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=12201,
        protocol="udp",
        # маленькая ширина окна не влияет на обычную отправку
        breaker_spec=BreakerSpec(failure_threshold=5, recovery_timeout=10.0),
        # по умолчанию compress=True; короткий payload — не сжимаем
    )
    await sink.write({"event": "ping", "level": "info"})
    assert captured["addr"] == ("127.0.0.1", 12201)
    assert captured["payload"]  # bytes
    assert sink.is_healthy is True


@pytest.mark.asyncio
async def test_graylog_circuit_breaker_open_skips_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Когда breaker в ``open`` — :meth:`write` мгновенно ставит unhealthy."""
    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=12201,
        protocol="udp",
        name=f"graylog_test_{id(object())}",
    )

    # Эмулируем open-state: подменяем свойство breaker.is_open
    monkeypatch.setattr(type(sink._breaker), "is_open", property(lambda self: True))

    # Любая попытка отправить должна быть пропущена — отлавливаем,
    # что socket вообще не создавался.
    sentinel: dict[str, bool] = {"called": False}

    def _fail_socket(*args: Any, **kwargs: Any) -> None:
        sentinel["called"] = True
        raise AssertionError("socket must not be opened when breaker is open")

    monkeypatch.setattr(socket, "socket", _fail_socket)

    await sink.write({"event": "should_skip"})
    assert sink.is_healthy is False
    assert sentinel["called"] is False


# ---------------------------------------------------------------------- profile
def test_build_sinks_dev_light() -> None:
    """``dev_light`` → один ``ConsoleJsonLogSink``."""
    sinks = build_sinks_for_profile(AppProfileChoices.dev_light)
    assert len(sinks) == 1
    assert isinstance(sinks[0], ConsoleJsonLogSink)


def test_build_sinks_dev(tmp_path: Path) -> None:
    """``dev`` → ``[Console, Disk]``."""
    sinks = build_sinks_for_profile(
        AppProfileChoices.dev, disk_path=str(tmp_path / "app.jsonl")
    )
    assert len(sinks) == 2
    assert isinstance(sinks[0], ConsoleJsonLogSink)
    assert isinstance(sinks[1], DiskRotatingLogSink)


def test_build_sinks_prod(tmp_path: Path) -> None:
    """``prod`` → ``[Graylog, Disk]``."""
    with patch.object(socket, "gethostname", return_value="test-host"):
        sinks = build_sinks_for_profile(
            AppProfileChoices.prod,
            disk_path=str(tmp_path / "prod.jsonl"),
            graylog_host="graylog.local",
            graylog_port=12201,
            graylog_protocol="udp",
        )
    assert len(sinks) == 2
    assert isinstance(sinks[0], GraylogGelfLogSink)
    assert isinstance(sinks[1], DiskRotatingLogSink)


# ---------------------------------------------------------------------- router
class _RecordingSink(LogSink):
    """Тестовый sink, фиксирует все ``write`` в список."""

    def __init__(self, name: str = "rec", *, fail: bool = False) -> None:
        self.name = name
        self.is_healthy = True
        self._fail = fail
        self.records: list[dict[str, Any]] = []
        self.flushed = 0
        self.closed = 0

    async def write(self, record: dict[str, Any]) -> None:
        if self._fail:
            raise RuntimeError("boom")
        self.records.append(record)

    async def flush(self) -> None:
        self.flushed += 1

    async def close(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_router_dispatch_fans_out_to_all_healthy_sinks() -> None:
    """``SinkRouter.dispatch`` отправляет запись во все healthy sinks."""
    a, b = _RecordingSink("a"), _RecordingSink("b")
    router = SinkRouter([a, b])
    await router.dispatch({"event": "x"})
    assert a.records == [{"event": "x"}]
    assert b.records == [{"event": "x"}]


@pytest.mark.asyncio
async def test_router_dispatch_isolates_failing_sink() -> None:
    """Падение одного sink не должно ломать доставку в остальные."""
    bad = _RecordingSink("bad", fail=True)
    good = _RecordingSink("good")
    router = SinkRouter([bad, good])
    # gather с return_exceptions=True не должен пробрасывать
    await router.dispatch({"event": "y"})
    assert good.records == [{"event": "y"}]


@pytest.mark.asyncio
async def test_router_aclose_calls_flush_and_close() -> None:
    """``aclose`` вызывает ``flush`` и ``close`` на каждом sink-е."""
    a = _RecordingSink("a")
    b = _RecordingSink("b")
    router = SinkRouter([a, b])
    await router.aclose()
    assert a.flushed == 1 and a.closed == 1
    assert b.flushed == 1 and b.closed == 1
    assert router.sinks == ()


@pytest.mark.asyncio
async def test_router_skips_unhealthy_when_healthy_present() -> None:
    """Нездоровые sink-и пропускаются при наличии healthy."""
    healthy = _RecordingSink("h")
    unhealthy = _RecordingSink("u")
    unhealthy.is_healthy = False
    router = SinkRouter([unhealthy, healthy])
    await router.dispatch({"event": "z"})
    assert healthy.records == [{"event": "z"}]
    assert unhealthy.records == []
