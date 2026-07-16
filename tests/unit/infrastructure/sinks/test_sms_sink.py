"""Unit-тесты для SmsSink (S203 W5)."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.sms_sink import SmsSink


class TestSmsSinkConstruction:
    """S203 W5: валидация провайдера + поля."""

    def test_default_kind_is_sms(self) -> None:
        s = SmsSink(sink_id="t", provider="smsru", api_id="x")
        assert s.kind == SinkKind.SMS

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="provider must be one of"):
            SmsSink(sink_id="t", provider="unknown_provider", api_id="x")

    @pytest.mark.parametrize("provider", ["smsru", "mts", "megafon"])
    def test_valid_providers_accepted(self, provider: str) -> None:
        s = SmsSink(sink_id="t", provider=provider, api_id="x")
        assert s.provider == provider

    def test_endpoint_lookup(self) -> None:
        s = SmsSink(sink_id="t", provider="smsru", api_id="x")
        ep = s._endpoint()
        assert "sms.ru" in ep

    def test_extract_dict_payload(self) -> None:
        s = SmsSink(sink_id="t", provider="smsru", default_to="+7000")
        to, body, sender = s._extract_payload(
            {"to": "+7111", "body": "hi", "from": "X"}
        )
        assert to == "+7111"
        assert body == "hi"
        assert sender == "X"

    def test_extract_str_payload_uses_default_to(self) -> None:
        s = SmsSink(sink_id="t", provider="smsru", default_to="+7000")
        to, body, sender = s._extract_payload("just text")
        assert to == "+7000"
        assert body == "just text"
        assert sender is None

    def test_extract_invalid_payload(self) -> None:
        s = SmsSink(sink_id="t", provider="smsru")
        assert s._extract_payload(12345) == (None, None, None)