"""Unit-тесты scraping processors — _validate_url, _is_blocked_host, ScrapeProcessor, PaginateProcessor, ApiProxyProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.scraping import (
    ApiProxyProcessor,
    PaginateProcessor,
    ScrapeProcessor,
    _is_blocked_host,
    _validate_url,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


# ── _validate_url / _is_blocked_host ──


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "expected_msg"),
    [
        ("http://localhost/foo", "Blocked host: localhost"),
        ("http://metadata.google.internal", "Blocked host: metadata.google.internal"),
        ("http://metadata.aws", "Blocked host: metadata.aws"),
        ("http://127.0.0.1", "Blocked private IP: 127.0.0.1"),
        ("http://10.0.0.1", "Blocked private IP: 10.0.0.1"),
        ("http://0.0.0.0", "Blocked private IP: 0.0.0.0"),
        ("http://192.168.1.1", "Blocked private IP: 192.168.1.1"),
        ("http://169.254.169.254", "Blocked private IP: 169.254.169.254"),
        ("http://[::1]", "Blocked private IP: ::1"),
        ("http://[fc00::1]", "Blocked private IP: fc00::1"),
        ("http://[fe80::1]", "Blocked private IP: fe80::1"),
        ("http://172.16.0.1", "Blocked private/loopback IP: 172.16.0.1"),
    ],
)
def test_validate_url_blocks(url: str, expected_msg: str) -> None:
    with pytest.raises(ValueError, match=expected_msg):
        _validate_url(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://8.8.8.8",
        "https://1.1.1.1",
        "https://[2001:4860:4860::8888]",
        "ftp://example.com",
        "",
        "not-a-url",
    ],
)
def test_validate_url_allows(url: str) -> None:
    # should not raise
    _validate_url(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("host", "expected_msg"),
    [
        ("localhost", "Blocked host: localhost"),
        ("127.0.0.1", "Blocked private IP: 127.0.0.1"),
        ("10.0.0.1", "Blocked private IP: 10.0.0.1"),
        ("172.16.0.1", "Blocked private/loopback IP: 172.16.0.1"),
        ("::1", "Blocked private IP: ::1"),
    ],
)
def test_is_blocked_host_raises(host: str, expected_msg: str) -> None:
    with pytest.raises(ValueError, match=expected_msg):
        _is_blocked_host(host)


@pytest.mark.unit
@pytest.mark.parametrize("host", ["example.com", "8.8.8.8", "2001:4860:4860::8888", ""])
def test_is_blocked_host_allows(host: str) -> None:
    # should not raise
    _is_blocked_host(host)


# ── ScrapeProcessor ──


@pytest.mark.unit
def test_scrape_processor_to_spec_defaults() -> None:
    proc = ScrapeProcessor(url="https://example.com", selectors={"title": "h1"})
    assert proc.to_spec() == {
        "scrape": {"url": "https://example.com", "selectors": {"title": "h1"}}
    }


@pytest.mark.unit
def test_scrape_processor_to_spec_full() -> None:
    proc = ScrapeProcessor(
        url="https://example.com",
        selectors={"title": "h1"},
        url_property="my_url",
        output_property="out",
        name="custom",
    )
    assert proc.to_spec() == {
        "scrape": {
            "url": "https://example.com",
            "selectors": {"title": "h1"},
            "url_property": "my_url",
            "output_property": "out",
        }
    }


@pytest.mark.asyncio
@pytest.mark.unit
async def test_scrape_processor_process_success() -> None:
    proc = ScrapeProcessor(url="https://example.com", selectors={"title": "h1"})
    ex = _ex()

    fake_node = MagicMock()
    fake_node.text.return_value = "Hello World"
    fake_tree = MagicMock()
    fake_tree.css.return_value = [fake_node]

    fake_response = {"data": "<html></html>", "status_code": 200}

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        with patch.dict(
            "sys.modules", {"selectolax": MagicMock(), "selectolax.parser": MagicMock()}
        ):
            with patch("selectolax.parser.HTMLParser", return_value=fake_tree):
                await proc.process(ex, AsyncMock())

    assert ex.error is None
    assert ex.properties["scraped"] == {"title": "Hello World"}
    assert ex.out_message is not None
    assert ex.out_message.body == {"title": "Hello World"}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_scrape_processor_missing_url() -> None:
    proc = ScrapeProcessor()
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.error is not None
    assert "No URL" in ex.error


@pytest.mark.asyncio
@pytest.mark.unit
async def test_scrape_processor_ssrf_blocked() -> None:
    proc = ScrapeProcessor(url="http://127.0.0.1")
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.error is not None
    assert "SSRF blocked" in ex.error


@pytest.mark.asyncio
@pytest.mark.unit
async def test_scrape_processor_url_from_property() -> None:
    proc = ScrapeProcessor(url_property="target_url", selectors={"a": "a"})
    ex = _ex()
    ex.set_property("target_url", "https://example.com")

    fake_node = MagicMock()
    fake_node.text.return_value = "link"
    fake_tree = MagicMock()
    fake_tree.css.return_value = [fake_node]
    fake_response = {"data": "<html></html>", "status_code": 200}

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        with patch.dict(
            "sys.modules", {"selectolax": MagicMock(), "selectolax.parser": MagicMock()}
        ):
            with patch("selectolax.parser.HTMLParser", return_value=fake_tree):
                await proc.process(ex, AsyncMock())

    assert ex.error is None
    assert ex.properties["scraped"] == {"a": "link"}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_scrape_processor_fetch_failure() -> None:
    proc = ScrapeProcessor(url="https://example.com", selectors={"title": "h1"})
    ex = _ex()

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        side_effect=Exception("timeout"),
    ):
        await proc.process(ex, AsyncMock())

    assert ex.error is not None
    assert "Scrape fetch failed" in ex.error


# ── PaginateProcessor ──


@pytest.mark.unit
def test_paginate_processor_to_spec_defaults() -> None:
    proc = PaginateProcessor()
    assert proc.to_spec() == {"paginate": {}}


@pytest.mark.unit
def test_paginate_processor_to_spec_full() -> None:
    proc = PaginateProcessor(
        next_selector=".next",
        item_selector=".item",
        max_pages=5,
        start_url="https://example.com",
        delay_seconds=1.0,
        output_property="items",
        name="custom",
    )
    assert proc.to_spec() == {
        "paginate": {
            "next_selector": ".next",
            "item_selector": ".item",
            "max_pages": 5,
            "start_url": "https://example.com",
            "delay_seconds": 1.0,
            "output_property": "items",
        }
    }


@pytest.mark.asyncio
@pytest.mark.unit
async def test_paginate_processor_process_success() -> None:
    proc = PaginateProcessor(
        start_url="https://example.com",
        next_selector="a.next",
        item_selector=".item",
        max_pages=3,
        delay_seconds=0.0,
    )
    ex = _ex()

    html_with_next = '<a class="next" href="/page2">next</a><div class="item">A</div>'
    html_without_next = '<div class="item">B</div>'

    fake_node = MagicMock()
    fake_node.text.return_value = "A"
    fake_node2 = MagicMock()
    fake_node2.text.return_value = "B"

    fake_tree1 = MagicMock()
    fake_tree1.css.return_value = [fake_node]
    fake_next_link1 = MagicMock()
    fake_next_link1.attributes = {"href": "/page2"}
    fake_tree1.css_first.return_value = fake_next_link1

    fake_tree2 = MagicMock()
    fake_tree2.css.return_value = [fake_node2]
    fake_tree2.css_first.return_value = None

    responses = [
        {"data": html_with_next, "status_code": 200},
        {"data": html_without_next, "status_code": 200},
    ]

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        side_effect=responses,
    ):
        with patch.dict(
            "sys.modules", {"selectolax": MagicMock(), "selectolax.parser": MagicMock()}
        ):
            with patch(
                "selectolax.parser.HTMLParser", side_effect=[fake_tree1, fake_tree2]
            ):
                with patch(
                    "src.backend.dsl.engine.processors.scraping._random_delay",
                    new_callable=AsyncMock,
                ):
                    await proc.process(ex, AsyncMock())

    assert ex.error is None
    assert ex.properties["paginated_results"] == ["A", "B"]
    assert ex.properties["pages_crawled"] == 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_paginate_processor_missing_url() -> None:
    proc = PaginateProcessor()
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.error is not None
    assert "No start URL" in ex.error


@pytest.mark.asyncio
@pytest.mark.unit
async def test_paginate_processor_ssrf_blocked() -> None:
    proc = PaginateProcessor(start_url="http://localhost")
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.error is not None
    assert "SSRF blocked" in ex.error


# ── ApiProxyProcessor ──


@pytest.mark.unit
def test_api_proxy_processor_to_spec_defaults() -> None:
    proc = ApiProxyProcessor(base_url="https://api.example.com")
    assert proc.to_spec() == {"api_proxy": {"base_url": "https://api.example.com"}}


@pytest.mark.unit
def test_api_proxy_processor_to_spec_full() -> None:
    proc = ApiProxyProcessor(
        base_url="https://api.example.com",
        method="POST",
        path="/v1/data",
        headers_mapping={"X-Token": "Authorization"},
        timeout=10.0,
        name="custom",
    )
    assert proc.to_spec() == {
        "api_proxy": {
            "base_url": "https://api.example.com",
            "method": "POST",
            "path": "/v1/data",
            "headers_mapping": {"X-Token": "Authorization"},
            "timeout": 10.0,
        }
    }


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_proxy_processor_process_success() -> None:
    proc = ApiProxyProcessor(
        base_url="https://api.example.com", method="GET", path="/items"
    )
    ex = _ex({"id": 1})
    ex.in_message.headers["Authorization"] = "Bearer tok"

    fake_response = {"status_code": 200, "data": {"items": []}}

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_req:
        await proc.process(ex, AsyncMock())

    assert ex.error is None
    assert ex.out_message is not None
    assert ex.out_message.body == fake_response
    assert ex.properties["proxy_url"] == "https://api.example.com/items"
    assert ex.properties["proxy_status"] == "success"
    mock_req.assert_awaited_once_with(
        method="GET",
        url="https://api.example.com/items",
        headers=None,
        json=None,
        total_timeout=30.0,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_proxy_processor_path_formatting() -> None:
    proc = ApiProxyProcessor(
        base_url="https://api.example.com", method="GET", path="/items/{id}"
    )
    ex = _ex({"id": 42})

    fake_response = {"status_code": 200, "data": {}}

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_req:
        await proc.process(ex, AsyncMock())

    mock_req.assert_awaited_once_with(
        method="GET",
        url="https://api.example.com/items/42",
        headers=None,
        json=None,
        total_timeout=30.0,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_proxy_processor_headers_mapping() -> None:
    proc = ApiProxyProcessor(
        base_url="https://api.example.com", headers_mapping={"X-Custom": "X-Source"}
    )
    ex = _ex({})
    ex.in_message.headers["X-Source"] = "value"

    fake_response = {"status_code": 200, "data": {}}

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_req:
        await proc.process(ex, AsyncMock())

    mock_req.assert_awaited_once_with(
        method="GET",
        url="https://api.example.com",
        headers={"X-Custom": "value"},
        json=None,
        total_timeout=30.0,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_proxy_processor_post_json_body() -> None:
    proc = ApiProxyProcessor(
        base_url="https://api.example.com", method="POST", path="/create"
    )
    ex = _ex({"name": "test"})

    fake_response = {"status_code": 201, "data": {"id": 1}}

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_req:
        await proc.process(ex, AsyncMock())

    mock_req.assert_awaited_once_with(
        method="POST",
        url="https://api.example.com/create",
        headers=None,
        json={"name": "test"},
        total_timeout=30.0,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_proxy_processor_ssrf_blocked() -> None:
    proc = ApiProxyProcessor(base_url="http://127.0.0.1")
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.error is not None
    assert "SSRF blocked" in ex.error


@pytest.mark.asyncio
@pytest.mark.unit
async def test_api_proxy_processor_request_failure() -> None:
    proc = ApiProxyProcessor(base_url="https://api.example.com")
    ex = _ex({})

    with patch(
        "src.backend.infrastructure.clients.transport.http.HttpClient.make_request",
        new_callable=AsyncMock,
        side_effect=Exception("conn refused"),
    ):
        await proc.process(ex, AsyncMock())

    assert ex.error is not None
    assert "API proxy GET https://api.example.com failed" in ex.error
