"""Scraping Pipeline DSL processors — structured extraction, pagination, API proxy.

Provides web scraping capabilities within DSL routes:
- ScrapeProcessor: extract structured data via CSS selectors
- PaginateProcessor: multi-page crawling with automatic next-page detection
- ApiProxyProcessor: transparent API proxy with request/response transformation
"""

from __future__ import annotations

import logging
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = ("ScrapeProcessor", "PaginateProcessor", "ApiProxyProcessor")

_scrape_logger = logging.getLogger("dsl.scraping")


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
            from app.infrastructure.clients.http import HttpClient
            client = HttpClient()
            response = await client.make_request(
                method="GET", url=url, response_type="text",
            )
            html = response.get("data", "") if isinstance(response, dict) else str(response)
        except Exception as exc:
            exchange.fail(f"Scrape fetch failed: {exc}")
            return

        try:
            from selectolax.parser import HTMLParser
            tree = HTMLParser(html)
        except ImportError:
            from html.parser import HTMLParser as _FallbackParser
            exchange.fail("selectolax not installed, scraping requires: pip install selectolax")
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
        output_property: str = "paginated_results",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"paginate(max={max_pages})")
        self._next_selector = next_selector
        self._item_selector = item_selector
        self._max_pages = max_pages
        self._start_url = start_url
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.infrastructure.clients.http import HttpClient

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
            from selectolax.parser import HTMLParser
        except ImportError:
            exchange.fail("selectolax not installed")
            return

        client = HttpClient()
        all_items: list[Any] = []
        visited: set[str] = set()

        for page_num in range(self._max_pages):
            if url in visited:
                break
            visited.add(url)

            try:
                response = await client.make_request(
                    method="GET", url=url, response_type="text",
                )
                html = response.get("data", "") if isinstance(response, dict) else str(response)
            except Exception as exc:
                _scrape_logger.warning("Pagination fetch failed on page %d: %s", page_num, exc)
                break

            tree = HTMLParser(html)

            if self._item_selector:
                items = [node.text().strip() for node in tree.css(self._item_selector)]
                all_items.extend(items)
            else:
                all_items.append({"page": page_num, "url": url, "html_length": len(html)})

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
        from app.infrastructure.clients.http import HttpClient

        path = self._path
        if "{" in path and isinstance(exchange.in_message.body, dict):
            try:
                path = path.format(**exchange.in_message.body)
            except (KeyError, IndexError):
                pass

        url = f"{self._base_url}{path}"

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
