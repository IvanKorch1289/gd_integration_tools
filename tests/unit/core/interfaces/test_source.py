"""Unit tests for src.backend.core.interfaces.source."""

from __future__ import annotations

from src.backend.core.interfaces.source import Source, SourceEvent, SourceKind


class TestSourceKind:
    def test_values(self) -> None:
        assert SourceKind.HTTP == "http"
        assert SourceKind.WEBHOOK == "webhook"
        assert SourceKind.EMAIL == "email"


class TestSourceEvent:
    def test_defaults(self) -> None:
        ev = SourceEvent(source_id="s1", kind=SourceKind.HTTP, payload={"x": 1})
        assert ev.source_id == "s1"
        assert ev.kind == SourceKind.HTTP
        assert ev.payload == {"x": 1}
        assert ev.metadata == {}
        assert ev.event_id is not None


class TestSource:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            source_id: str = "s1"
            kind: SourceKind = SourceKind.HTTP

            async def start(self, on_event: object) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def health(self) -> bool:
                return True

        assert isinstance(Fake(), Source)

    def test_missing_method_fails(self) -> None:
        class Bad:
            source_id: str = "s1"
            kind: SourceKind = SourceKind.HTTP

        assert not isinstance(Bad(), Source)
