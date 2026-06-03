"""Unit tests for src.backend.core.interfaces.sink."""

from __future__ import annotations

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult


class TestSinkKind:
    def test_values(self) -> None:
        assert SinkKind.HTTP == "http"
        assert SinkKind.MQ == "mq"
        assert SinkKind.MQTT == "mqtt"


class TestSinkResult:
    def test_defaults(self) -> None:
        res = SinkResult(ok=True)
        assert res.ok is True
        assert res.external_id is None
        assert res.details == {}

    def test_full(self) -> None:
        res = SinkResult(ok=False, external_id="ext1", details={"code": 500})
        assert res.ok is False
        assert res.external_id == "ext1"
        assert res.details == {"code": 500}


class TestSink:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            sink_id: str = "s1"
            kind: SinkKind = SinkKind.HTTP

            async def send(self, payload: object) -> SinkResult:
                return SinkResult(ok=True)

            async def health(self) -> bool:
                return True

        assert isinstance(Fake(), Sink)

    def test_missing_method_fails(self) -> None:
        class Bad:
            sink_id: str = "s1"
            kind: SinkKind = SinkKind.HTTP

        assert not isinstance(Bad(), Sink)
