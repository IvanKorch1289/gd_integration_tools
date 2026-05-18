"""Sprint 5 pilot batch — функциональные тесты 4 новых процессоров.

Покрывает:
* :class:`WebhookSignVerifyProcessor` (stdlib hmac, без extra deps);
* :class:`JsonPathProcessor` (extra ``dsl-extras`` → ``jsonpath-ng``);
* :class:`UnitConversionProcessor` (extra ``dsl-extras`` → ``pint``);
* :class:`IcsCalendarProcessor` (extra ``dsl-extras`` → ``icalendar``).

Тесты, требующие optional-deps, используют ``pytest.importorskip``.
"""

# ruff: noqa: S101, S105, S106

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.calendar_ics import IcsCalendarProcessor
from src.backend.dsl.engine.processors.data_query import JsonPathProcessor
from src.backend.dsl.engine.processors.enrichment import WebhookSignVerifyProcessor
from src.backend.dsl.engine.processors.units import UnitConversionProcessor


def _exchange(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ─────────────────────────── WebhookSignVerifyProcessor ──────────────────────────


def _hmac_hex(secret: str, body: bytes, algo: str = "sha256") -> str:
    return hmac.new(secret.encode(), body, getattr(hashlib, algo)).hexdigest()


@pytest.mark.asyncio
class TestWebhookSignVerifyProcessor:
    async def test_valid_signature(self) -> None:
        secret = "topsecret"
        body = b'{"event":"order.created"}'
        sig = _hmac_hex(secret, body)
        ex = _exchange(body=body, headers={"X-Webhook-Signature": sig})
        proc = WebhookSignVerifyProcessor(secret=secret)

        await proc.process(ex, _ctx())

        assert ex.error is None
        assert ex.properties.get("webhook_signature_valid") is True

    async def test_mismatch_fails_pipeline(self) -> None:
        ex = _exchange(body=b"x", headers={"X-Webhook-Signature": "deadbeef"})
        proc = WebhookSignVerifyProcessor(secret="K")

        await proc.process(ex, _ctx())

        assert ex.properties.get("webhook_signature_valid") is False
        assert ex.error is not None and "signature mismatch" in ex.error

    async def test_mismatch_warn_does_not_fail(self) -> None:
        ex = _exchange(body=b"x", headers={"X-Webhook-Signature": "deadbeef"})
        proc = WebhookSignVerifyProcessor(secret="K", on_mismatch="warn")

        await proc.process(ex, _ctx())

        assert ex.error is None
        assert ex.properties.get("webhook_signature_valid") is False

    async def test_missing_header_fails(self) -> None:
        ex = _exchange(body=b"x")
        proc = WebhookSignVerifyProcessor(secret="K")

        await proc.process(ex, _ctx())

        assert ex.error is not None and "missing" in ex.error

    async def test_prefixed_signature_v1(self) -> None:
        secret = "K"
        body = b"hello"
        sig = _hmac_hex(secret, body)
        ex = _exchange(body=body, headers={"X-Webhook-Signature": f"v1={sig}"})
        proc = WebhookSignVerifyProcessor(secret=secret, prefix="v1")

        await proc.process(ex, _ctx())

        assert ex.properties.get("webhook_signature_valid") is True

    async def test_dict_body_is_orjson_serialized(self) -> None:
        import orjson

        secret = "K"
        body_obj: dict[str, Any] = {"a": 1, "b": [1, 2]}
        body_bytes = orjson.dumps(body_obj, default=str)
        sig = _hmac_hex(secret, body_bytes)
        ex = _exchange(body=body_obj, headers={"X-Webhook-Signature": sig})
        proc = WebhookSignVerifyProcessor(secret=secret)

        await proc.process(ex, _ctx())

        assert ex.properties.get("webhook_signature_valid") is True

    async def test_invalid_on_mismatch_value_raises(self) -> None:
        with pytest.raises(ValueError):
            WebhookSignVerifyProcessor(secret="K", on_mismatch="weird")

    def test_to_spec_round_trip(self) -> None:
        proc = WebhookSignVerifyProcessor(
            secret="K",
            header="X-Sig",
            algorithm="sha512",
            prefix="v1",
            on_mismatch="warn",
        )
        spec = proc.to_spec()
        assert spec == {
            "webhook_verify": {
                "secret": "K",
                "header": "X-Sig",
                "algorithm": "sha512",
                "prefix": "v1",
                "on_mismatch": "warn",
            }
        }


# ─────────────────────────────── JsonPathProcessor ────────────────────────────────


@pytest.mark.asyncio
class TestJsonPathProcessor:
    @pytest.fixture(autouse=True)
    def _skip_without_dep(self) -> None:
        pytest.importorskip("jsonpath_ng")

    async def test_extract_list(self) -> None:
        body = {"items": [{"price": 10}, {"price": 20}]}
        ex = _exchange(body=body)
        proc = JsonPathProcessor("$.items[*].price")
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == [10, 20]

    async def test_extract_single(self) -> None:
        body = {"user": {"email": "a@b.io"}}
        ex = _exchange(body=body)
        proc = JsonPathProcessor("$.user.email", single=True)
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == "a@b.io"

    async def test_extract_to_property(self) -> None:
        body = {"user": {"email": "x@y.io"}}
        ex = _exchange(body=body)
        proc = JsonPathProcessor(
            "$.user.email", single=True, to_property="user_email"
        )
        await proc.process(ex, _ctx())
        assert ex.properties["user_email"] == "x@y.io"
        assert ex.out_message is None

    async def test_update_replaces_value(self) -> None:
        body = {"status": "pending"}
        ex = _exchange(body=body)
        proc = JsonPathProcessor("$.status", mode="update", value="approved")
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"status": "approved"}

    async def test_exists_true(self) -> None:
        body = {"a": 1}
        ex = _exchange(body=body)
        proc = JsonPathProcessor("$.a", mode="exists")
        await proc.process(ex, _ctx())
        assert ex.properties["jsonpath_exists"] is True

    async def test_exists_false_stop(self) -> None:
        body = {"a": 1}
        ex = _exchange(body=body)
        proc = JsonPathProcessor("$.b", mode="exists", stop_on_missing=True)
        await proc.process(ex, _ctx())
        assert ex.properties["jsonpath_exists"] is False
        assert ex.stopped

    async def test_json_string_body(self) -> None:
        ex = _exchange(body='{"x": 42}')
        proc = JsonPathProcessor("$.x", single=True)
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == 42

    async def test_invalid_expression(self) -> None:
        ex = _exchange(body={"a": 1})
        proc = JsonPathProcessor("$..[?(invalid")
        await proc.process(ex, _ctx())
        assert ex.error is not None

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            JsonPathProcessor("$.x", mode="weird")

    def test_to_spec(self) -> None:
        proc = JsonPathProcessor(
            "$.x", mode="exists", stop_on_missing=True, to_property="found"
        )
        spec = proc.to_spec()
        assert spec == {
            "jsonpath": {
                "expression": "$.x",
                "mode": "exists",
                "to_property": "found",
                "stop_on_missing": True,
            }
        }


# ───────────────────────────── UnitConversionProcessor ─────────────────────────────


@pytest.mark.asyncio
class TestUnitConversionProcessor:
    @pytest.fixture(autouse=True)
    def _skip_without_dep(self) -> None:
        pytest.importorskip("pint")

    async def test_dict_body_converts_unit(self) -> None:
        ex = _exchange(body={"value": 100, "unit": "celsius"})
        proc = UnitConversionProcessor(to_unit="fahrenheit", precision=2)
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        result = ex.out_message.body
        assert result["unit"] == "fahrenheit"
        assert result["value"] == pytest.approx(212.0, abs=0.01)

    async def test_scalar_body_with_from_unit(self) -> None:
        ex = _exchange(body=10.0)
        proc = UnitConversionProcessor(
            from_unit="km", to_unit="mile", precision=4
        )
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == pytest.approx(6.2137, abs=0.001)

    async def test_list_body(self) -> None:
        ex = _exchange(body=[1, 2, 3])
        proc = UnitConversionProcessor(
            from_unit="meter", to_unit="centimeter"
        )
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == [100.0, 200.0, 300.0]

    async def test_to_property_does_not_replace_body(self) -> None:
        ex = _exchange(body={"value": 1, "unit": "kg"})
        proc = UnitConversionProcessor(to_unit="gram", to_property="weight_g")
        await proc.process(ex, _ctx())
        assert ex.out_message is None
        assert ex.properties["weight_g"]["value"] == pytest.approx(1000.0)

    async def test_incompatible_dimensions_fails(self) -> None:
        ex = _exchange(body={"value": 1, "unit": "kg"})
        proc = UnitConversionProcessor(to_unit="celsius")
        await proc.process(ex, _ctx())
        assert ex.error is not None and "dimension" in ex.error.lower()

    async def test_undefined_unit_fails(self) -> None:
        ex = _exchange(body={"value": 1, "unit": "blub"})
        proc = UnitConversionProcessor(to_unit="meter")
        await proc.process(ex, _ctx())
        assert ex.error is not None

    async def test_scalar_without_from_unit_fails(self) -> None:
        ex = _exchange(body=10)
        proc = UnitConversionProcessor(to_unit="meter")
        await proc.process(ex, _ctx())
        assert ex.error is not None and "from_unit" in ex.error

    def test_to_spec(self) -> None:
        proc = UnitConversionProcessor(
            from_unit="km", to_unit="mile", precision=2, to_property="dist"
        )
        spec = proc.to_spec()
        assert spec == {
            "convert_units": {
                "to_unit": "mile",
                "from_unit": "km",
                "precision": 2,
                "to_property": "dist",
            }
        }


# ─────────────────────────────── IcsCalendarProcessor ──────────────────────────────

_SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//RU
BEGIN:VEVENT
UID:evt-1@example.com
SUMMARY:Standup
DESCRIPTION:Daily team standup
LOCATION:Zoom
DTSTART:20260507T090000Z
DTEND:20260507T091500Z
ORGANIZER:mailto:lead@example.com
ATTENDEE:mailto:dev1@example.com
ATTENDEE:mailto:dev2@example.com
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
"""


@pytest.mark.asyncio
class TestIcsCalendarProcessor:
    @pytest.fixture(autouse=True)
    def _skip_without_dep(self) -> None:
        pytest.importorskip("icalendar")

    async def test_parse_extracts_event_fields(self) -> None:
        ex = _exchange(body=_SAMPLE_ICS)
        proc = IcsCalendarProcessor()
        await proc.process(ex, _ctx())

        assert ex.out_message is not None
        events = ex.out_message.body
        assert isinstance(events, list)
        assert len(events) == 1

        evt = events[0]
        assert evt["uid"] == "evt-1@example.com"
        assert evt["summary"] == "Standup"
        assert evt["location"] == "Zoom"
        assert evt["status"] == "CONFIRMED"
        assert len(evt["attendees"]) == 2
        assert "2026-05-07" in evt["start"]

    async def test_parse_only_first(self) -> None:
        ex = _exchange(body=_SAMPLE_ICS)
        proc = IcsCalendarProcessor(only_first=True)
        await proc.process(ex, _ctx())
        assert ex.out_message is not None
        evt = ex.out_message.body
        assert isinstance(evt, dict)
        assert evt["uid"] == "evt-1@example.com"

    async def test_build_round_trip(self) -> None:
        ex = _exchange(
            body={
                "uid": "evt-build-1",
                "summary": "Sprint Planning",
                "description": "Plan next sprint",
            }
        )
        proc_build = IcsCalendarProcessor(mode="build")
        await proc_build.process(ex, _ctx())
        assert ex.out_message is not None
        ics_bytes = ex.out_message.body
        assert isinstance(ics_bytes, bytes)
        assert b"VEVENT" in ics_bytes
        assert b"evt-build-1" in ics_bytes

        ex2 = _exchange(body=ics_bytes)
        proc_parse = IcsCalendarProcessor(only_first=True)
        await proc_parse.process(ex2, _ctx())
        assert ex2.out_message is not None
        parsed = ex2.out_message.body
        assert parsed["uid"] == "evt-build-1"
        assert parsed["summary"] == "Sprint Planning"

    async def test_build_invalid_body_fails(self) -> None:
        ex = _exchange(body="not a list of dicts")
        proc = IcsCalendarProcessor(mode="build")
        await proc.process(ex, _ctx())
        assert ex.error is not None

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            IcsCalendarProcessor(mode="weird")

    def test_to_spec(self) -> None:
        proc = IcsCalendarProcessor(
            mode="build", only_first=True, prodid="-//demo//RU"
        )
        spec = proc.to_spec()
        assert spec == {
            "parse_ics": {
                "mode": "build",
                "only_first": True,
                "prodid": "-//demo//RU",
            }
        }
