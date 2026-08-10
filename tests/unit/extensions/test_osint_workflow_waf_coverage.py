"""D-AUDIT-A2-02 fix (cycle 1): osint_workflow.py uses OutboundHttpClient для WAF coverage.

Ранее ``extensions/osint_agent/functions/osint_workflow.py:_scrape_url``
использовал прямой ``httpx.AsyncClient`` — обходил WAF-coverage gate.
extensions/ НЕ сканируются check_waf_coverage.py по умолчанию, но
все равно должен следовать R-V15-5 (strict WAF для :external).

Фикс: заменено на ``OutboundHttpClient`` с plugin='osint_agent.scrape'.
"""


from __future__ import annotations

import inspect


class TestOsintWorkflowUsesOutboundHttpClient:
    """D-AUDIT-A2-02 fix (cycle 1): osint_workflow использует OutboundHttpClient."""

    def test_scrape_url_no_direct_httpx(self) -> None:
        """_scrape_url не использует httpx.AsyncClient напрямую."""
        from extensions.osint_agent.functions import osint_workflow

        src = inspect.getsource(osint_workflow._scrape_url)
        assert "async with httpx.AsyncClient" not in src, (
            "_scrape_url должен использовать OutboundHttpClient, не httpx.AsyncClient"
        )

    def test_scrape_url_uses_outbound_http_client(self) -> None:
        """_scrape_url использует OutboundHttpClient (WAF wrapper)."""
        from extensions.osint_agent.functions import osint_workflow

        src = inspect.getsource(osint_workflow._scrape_url)
        assert "OutboundHttpClient" in src, (
            "_scrape_url должен использовать OutboundHttpClient (WAF wrapper)"
        )

    def test_scrape_url_plugin_name(self) -> None:
        """OutboundHttpClient plugin name = 'osint_agent.scrape'."""
        from extensions.osint_agent.functions import osint_workflow

        src = inspect.getsource(osint_workflow._scrape_url)
        assert 'plugin="osint_agent.scrape"' in src, (
            "OutboundHttpClient plugin name должен быть 'osint_agent.scrape'"
        )
