"""Scraping Pipeline DSL processors — structured extraction, pagination, API proxy.

Provides web scraping capabilities within DSL routes:
- ScrapeProcessor: extract structured data via CSS selectors
- PaginateProcessor: multi-page crawling with automatic next-page detection
- ApiProxyProcessor: transparent API proxy with request/response transformation
"""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

__all__ = ("ScrapeProcessor", "PaginateProcessor", "ApiProxyProcessor")

_scrape_logger = logging.getLogger("dsl.scraping")

_BLOCKED_IP_PREFIXES = (
    "127.",
    "10.",
    "0.",
    "192.168.",
    "169.254.",
    "::1",
    "fc00:",
    "fe80:",
)
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata.aws"}


def _validate_url(url: str) -> None:
    """Block requests to private networks, localhost, and cloud metadata endpoints."""
    import ipaddress
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Blocked host: {host}")

    for prefix in _BLOCKED_IP_PREFIXES:
        if host.startswith(prefix):
            raise ValueError(f"Blocked private IP: {host}")

    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"Blocked private/loopback IP: {host}")
    except ValueError:
        pass


# ── Anti-bot stealth helpers ──

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 OPR/109.0.0.0",
]

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "ru-RU,ru;q=0.9,en;q=0.8",
    "en-GB,en;q=0.9",
    "de-DE,de;q=0.9,en;q=0.8",
]


def _stealth_headers(referer: str | None = None) -> dict[str, str]:
    """Generate randomized browser-like headers for each request."""
    import random

    headers = {
        "User-Agent": random.choice(_USER_AGENTS),  # noqa: S311  # stealth header rotation, не криптография
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(_ACCEPT_LANGUAGES),  # noqa: S311  # stealth header rotation, не криптография
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


async def _random_delay(min_s: float = 1.0, max_s: float = 3.0) -> None:
    """Random delay between requests to avoid rate-limiting."""
    import asyncio
    import random

    await asyncio.sleep(min_s + random.random() * (max_s - min_s))  # noqa: S311  # rate-limit jitter, не криптография


class ScrapeProcessor(BaseProcessor):
    """Extract structured data from HTML using CSS selectors.

    Usage in DSL::

        .scrape("https://example.com", selectors={"title": "h1", "price": ".price"})
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        selectors: dict[str, str] | None = None,
        url_property: str | None = None,
        output_property: str = "scraped",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"scrape:{url or 'dynamic'}")
        self._url = url
        self._selectors = selectors or {}
        self._url_property = url_property
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        url = self._url
        if self._url_property:
            url = exchange.properties.get(self._url_property, url)
        if not url:
            body = exchange.in_message.body
            url = body.get("url") if isinstance(body, dict) else str(body)

        if not url:
            exchange.fail("No URL provided for scraping")
            return

        try:
            _validate_url(url)
        except ValueError as exc:
            exchange.fail(f"SSRF blocked: {exc}")
            return

        try:
            from src.infrastructure.clients.transport.http import HttpClient

            client = HttpClient()
            response = await client.make_request(
                method="GET", url=url, response_type="text", headers=_stealth_headers()
            )
            html = (
                response.get("data", "")
                if isinstance(response, dict)
                else str(response)
            )
        except Exception as exc:
            exchange.fail(f"Scrape fetch failed: {exc}")
            return

        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(html)
        except ImportError:
            exchange.fail(
                "selectolax not installed, scraping requires: pip install selectolax"
            )
            return

        result: dict[str, Any] = {}
        for field_name, selector in self._selectors.items():
            nodes = tree.css(selector)
            if len(nodes) == 1:
                result[field_name] = nodes[0].text().strip()
            elif len(nodes) > 1:
                result[field_name] = [n.text().strip() for n in nodes]
            else:
                result[field_name] = None

        exchange.set_property(self._output_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class PaginateProcessor(BaseProcessor):
    """Multi-page crawling with automatic next-page detection.

    Usage in DSL::

        .paginate(next_selector=".next-page a", max_pages=10,
                  item_selector=".product-card")
    """

    def __init__(
        self,
        *,
        next_selector: str = "a.next",
        item_selector: str | None = None,
        max_pages: int = 10,
        start_url: str | None = None,
        delay_seconds: float = 2.0,
        output_property: str = "paginated_results",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"paginate(max={max_pages})")
        self._next_selector = next_selector
        self._item_selector = item_selector
        self._max_pages = max_pages
        self._start_url = start_url
        self._delay = delay_seconds
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.infrastructure.clients.transport.http import HttpClient

        url = self._start_url
        if not url:
            body = exchange.in_message.body
            if isinstance(body, dict):
                url = body.get("url")
            elif isinstance(body, str) and body.startswith("http"):
                url = body

        scraped = exchange.properties.get("scraped")
        if not url and isinstance(scraped, dict):
            url = scraped.get("_source_url")

        if not url:
            exchange.fail("No start URL for pagination")
            return

        try:
            _validate_url(url)
        except ValueError as exc:
            exchange.fail(f"SSRF blocked: {exc}")
            return

        try:
            from selectolax.parser import HTMLParser
        except ImportError:
            exchange.fail("selectolax not installed")
            return

        client = HttpClient()
        all_items: list[Any] = []
        visited: set[str] = set()

        prev_url: str | None = None

        for page_num in range(self._max_pages):
            if url in visited:
                break
            visited.add(url)

            if page_num > 0:
                await _random_delay(self._delay * 0.5, self._delay * 1.5)

            try:
                response = await client.make_request(
                    method="GET",
                    url=url,
                    response_type="text",
                    headers=_stealth_headers(referer=prev_url),
                )
                html = (
                    response.get("data", "")
                    if isinstance(response, dict)
                    else str(response)
                )
            except Exception as exc:
                _scrape_logger.warning(
                    "Pagination fetch failed on page %d: %s", page_num, exc
                )
                break

            prev_url = url

            tree = HTMLParser(html)

            if self._item_selector:
                items = [node.text().strip() for node in tree.css(self._item_selector)]
                all_items.extend(items)
            else:
                all_items.append(
                    {"page": page_num, "url": url, "html_length": len(html)}
                )

            next_link = tree.css_first(self._next_selector)
            if next_link is None:
                break

            href = next_link.attributes.get("href", "")
            if not href:
                break

            if href.startswith("/"):
                from urllib.parse import urljoin

                url = urljoin(url, href)
            elif href.startswith("http"):
                url = href
            else:
                break

        exchange.set_property(self._output_property, all_items)
        exchange.set_property("pages_crawled", len(visited))
        exchange.set_out(body=all_items, headers=dict(exchange.in_message.headers))


class ApiProxyProcessor(BaseProcessor):
    """Transparent API proxy with request/response transformation.

    Forwards exchange body as request to external API,
    applies optional header mapping and response transformation.

    Usage in DSL::

        .api_proxy(base_url="https://api.example.com", method="POST", path="/v1/data")
    """

    def __init__(
        self,
        base_url: str,
        *,
        method: str = "GET",
        path: str = "",
        headers_mapping: dict[str, str] | None = None,
        timeout: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"api_proxy:{method}:{base_url}")
        self._base_url = base_url.rstrip("/")
        self._method = method.upper()
        self._path = path
        self._headers_mapping = headers_mapping or {}
        self._timeout = timeout

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.infrastructure.clients.transport.http import HttpClient

        path = self._path
        if "{" in path and isinstance(exchange.in_message.body, dict):
            try:
                path = path.format(**exchange.in_message.body)
            except KeyError, IndexError:
                pass

        url = f"{self._base_url}{path}"

        try:
            _validate_url(url)
        except ValueError as exc:
            exchange.fail(f"SSRF blocked: {exc}")
            return

        proxy_headers: dict[str, str] = {}
        for target_header, source_header in self._headers_mapping.items():
            value = exchange.in_message.headers.get(source_header)
            if value is not None:
                proxy_headers[target_header] = str(value)

        json_body = None
        if self._method in ("POST", "PUT", "PATCH"):
            body = exchange.in_message.body
            if isinstance(body, dict):
                json_body = body

        client = HttpClient()
        try:
            result = await client.make_request(
                method=self._method,
                url=url,
                headers=proxy_headers or None,
                json=json_body,
                total_timeout=self._timeout,
            )
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
            exchange.set_property("proxy_url", url)
            exchange.set_property("proxy_status", "success")
        except Exception as exc:
            exchange.fail(f"API proxy {self._method} {url} failed: {exc}")
