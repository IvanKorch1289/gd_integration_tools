"""W23 — операции SourceRegistry / SinkRegistry."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.interfaces.sink import SinkKind, SinkResult
from src.backend.core.interfaces.source import EventCallback, SourceKind
from src.backend.services.sources.registry import SinkRegistry, SourceRegistry


class _Src:
    def __init__(self, sid: str, kind: SourceKind = SourceKind.HTTP) -> None:
        self.source_id = sid
        self.kind = kind

    async def start(self, on_event: EventCallback) -> None:  # noqa: D401
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> bool:
        return True


class _Snk:
    def __init__(self, sid: str) -> None:
        self.sink_id = sid
        self.kind = SinkKind.HTTP

    async def send(self, payload: object) -> SinkResult:
        return SinkResult(ok=True)

    async def health(self) -> bool:
        return True


class TestSourceRegistry:
    def test_register_and_lookup(self) -> None:
        reg = SourceRegistry()
        src = _Src("a")
        reg.register(src)
        assert reg.get("a") is src
        assert "a" in reg
        assert len(reg) == 1

    def test_duplicate_raises(self) -> None:
        reg = SourceRegistry()
        reg.register(_Src("a"))
        with pytest.raises(ValueError):
            reg.register(_Src("a"))

    def test_missing_lookup_raises(self) -> None:
        reg = SourceRegistry()
        with pytest.raises(KeyError):
            reg.get("nope")

    def test_all_sorted(self) -> None:
        reg = SourceRegistry()
        reg.register(_Src("b"))
        reg.register(_Src("a"))
        ids = [s.source_id for s in reg.all()]
        assert ids == ["a", "b"]


class TestSinkRegistry:
    def test_register_and_lookup(self) -> None:
        reg = SinkRegistry()
        snk = _Snk("a")
        reg.register(snk)
        assert reg.get("a") is snk
        assert "a" in reg

    def test_duplicate_raises(self) -> None:
        reg = SinkRegistry()
        reg.register(_Snk("a"))
        with pytest.raises(ValueError):
            reg.register(_Snk("a"))
