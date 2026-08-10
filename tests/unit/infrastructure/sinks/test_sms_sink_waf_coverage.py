"""D-AUDIT-A2-01 fix (cycle 1): sms_sink uses OutboundHttpClient для WAF coverage.

Ранее sms_sink использовал прямой ``httpx.AsyncClient`` в 2 местах —
это обходило WAF-coverage gate (``tools/check_waf_coverage.py`` exit 1).

Фикс: заменено на ``OutboundHttpClient`` с WAF pre-hook + capability-gate.
"""


from __future__ import annotations

import inspect


class TestSmsSinkUsesOutboundHttpClient:
    """D-AUDIT-A2-01 fix (cycle 1): sms_sink использует OutboundHttpClient."""

    def test_no_direct_httpx_client_in_send(self) -> None:
        """SmsSink.send не использует httpx.AsyncClient напрямую."""
        from src.backend.infrastructure.sinks.sms_sink import SmsSink

        src = inspect.getsource(SmsSink.send)
        # 'async with httpx.AsyncClient' — прямой клиент
        assert "async with httpx.AsyncClient" not in src, (
            "SmsSink.send должен использовать OutboundHttpClient, не httpx.AsyncClient"
        )

    def test_no_direct_httpx_client_in_health(self) -> None:
        """SmsSink.health не использует httpx.AsyncClient напрямую."""
        from src.backend.infrastructure.sinks.sms_sink import SmsSink

        src = inspect.getsource(SmsSink.health)
        assert "async with httpx.AsyncClient" not in src, (
            "SmsSink.health должен использовать OutboundHttpClient, не httpx.AsyncClient"
        )

    def test_send_uses_outbound_http_client(self) -> None:
        """SmsSink.send использует OutboundHttpClient."""
        from src.backend.infrastructure.sinks.sms_sink import SmsSink

        src = inspect.getsource(SmsSink.send)
        assert "OutboundHttpClient" in src, (
            "SmsSink.send должен использовать OutboundHttpClient (WAF wrapper)"
        )

    def test_health_uses_outbound_http_client(self) -> None:
        """SmsSink.health использует OutboundHttpClient."""
        from src.backend.infrastructure.sinks.sms_sink import SmsSink

        src = inspect.getsource(SmsSink.health)
        assert "OutboundHttpClient" in src, (
            "SmsSink.health должен использовать OutboundHttpClient (WAF wrapper)"
        )

    def test_plugin_name_format(self) -> None:
        """OutboundHttpClient plugin name использует формат 'sms_sink.<provider>'."""
        from src.backend.infrastructure.sinks.sms_sink import SmsSink

        src = inspect.getsource(SmsSink)
        assert "plugin=f\"sms_sink.{self.provider}\"" in src, (
            "OutboundHttpClient plugin name должен быть 'sms_sink.<provider>'"
        )
