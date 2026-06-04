"""Unit-тесты RequestReplyMixin builder methods."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.processors.request_reply import (
    ReplyProcessor,
    RequestProcessor,
)


class TestRequest:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.request", source="internal:test")
        result = builder.request("events.test", {"q": "hello"})
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_request_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.request", source="internal:test")
            .request("events.test", {"q": "hello"}, timeout=10.0, result_property="resp")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, RequestProcessor)
        assert proc._target_channel == "events.test"
        assert proc._timeout == 10.0
        assert proc._result_property == "resp"

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.request", source="internal:test")
            .request("events.test", {"q": "hello"}, timeout=5.0)
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {
            "request": {
                "target_channel": "events.test",
                "payload": {"q": "hello"},
                "timeout": 5.0,
                "correlation_id": None,
                "result_property": "reply",
            }
        }


class TestReply:
    def test_returns_route_builder(self) -> None:
        builder = RouteBuilder.from_("test.reply", source="internal:test")
        result = builder.reply("events.replies.abc", {"answer": 42})
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_reply_processor(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.reply", source="internal:test")
            .reply("events.replies.abc", {"answer": 42}, correlation_id="cid")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, ReplyProcessor)
        assert proc._reply_channel == "events.replies.abc"
        assert proc._correlation_id == "cid"

    def test_to_spec(self) -> None:
        pipeline = (
            RouteBuilder.from_("test.reply", source="internal:test")
            .reply("events.replies.abc")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        assert spec == {
            "reply": {
                "reply_channel": "events.replies.abc",
                "payload": None,
                "correlation_id": None,
            }
        }
