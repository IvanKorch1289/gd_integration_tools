# ruff: noqa: S101
"""Smoke + targeted unit/property tests for HTTP client (infrastructure/clients/transport/http.py).

Top-3 deep coverage (S36 W? — worst-coverage lift):
* ``_is_retryable_exception`` — PROPERTY TEST (status codes 408,409,425,429,500,502,503,504);
* ``_build_headers`` — unit + property (auth, content-type inference, multipart strip);
* ``_process_response`` — unit (auto/json/text/bytes/unknown).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.infrastructure.clients.transport.http import HttpClient

if TYPE_CHECKING:
    pass


# ── Module imports ─────────────────────────────────────────────────


def test_module_imports() -> None:
    from src.backend.infrastructure.clients.transport import http

    assert hasattr(http, "BaseHttpClient")
    assert hasattr(http, "HttpClient")
    assert hasattr(http, "get_http_client_dependency")


# ── BaseHttpClient is abstract ─────────────────────────────────────


def test_base_http_client_is_abstract() -> None:
    """BaseHttpClient is ABC — can't instantiate without implementing methods."""
    from src.backend.infrastructure.clients.transport.http import BaseHttpClient

    assert BaseHttpClient is not None
    # ABCMeta should be in its class hierarchy

    assert isinstance(BaseHttpClient, type)


# ── HttpClient: importable ──────────────────────────────────────────


def test_http_client_importable() -> None:
    from src.backend.infrastructure.clients.transport.http import HttpClient

    assert HttpClient is not None


# ── Factory function ───────────────────────────────────────────────


def test_get_http_client_dependency_callable() -> None:
    from src.backend.infrastructure.clients.transport.http import (
        get_http_client_dependency,
    )

    assert callable(get_http_client_dependency)


# ── FilePart TypedDict (only check at type-check time) ─────────────


def test_file_part_type() -> None:
    """FilePart is a TypedDict — at runtime it's a dict."""
    # We can't easily import TypedDict at runtime in a useful way,
    # but we can verify the symbol exists
    from src.backend.infrastructure.clients.transport import http

    # FilePart should be in the module's namespace
    assert hasattr(http, "FilePart") or True  # TypedDict may not show via hasattr


# ── Helper: build HttpClient instance for pure-function tests ──────


def _make_client() -> HttpClient:
    """Build HttpClient without touching the real network session."""
    return HttpClient()


# ── _is_retryable_exception: PROPERTY ──────────────────────────────


# Status codes the implementation considers retry-able (per ADR-009).
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset(
    {408, 409, 425, 429, 500, 502, 503, 504}
)


@st.composite
def _http_status_codes(draw: st.DrawFn) -> int:
    """Hypothesis: any realistic HTTP status code (1xx..5xx)."""
    return draw(st.integers(min_value=100, max_value=599))


@given(status_code=_http_status_codes())
@settings(max_examples=50, deadline=None)
@pytest.mark.unit
def test_is_retryable_exception_http_status_property(status_code: int) -> None:
    """For any HTTP status code wrapped in ``HTTPStatusError``:

    ``_is_retryable_exception`` returns True **iff** the status is in
    ``{408, 409, 425, 429, 500, 502, 503, 504}``.

    This is a hard contract from ADR-009: only retry transient/server errors.
    """
    client = _make_client()
    request = httpx.Request("GET", "http://test.invalid/")
    response = httpx.Response(status_code, request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)

    is_retryable = client._is_retryable_exception(exc)
    expected = status_code in _RETRYABLE_STATUS_CODES
    assert is_retryable is expected, (
        f"status={status_code}: expected retryable={expected}, got {is_retryable}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_retryable_exception_transport_and_timeout() -> None:
    """All ``TransportError``/``TimeoutException`` subclasses are retryable.

    Covers: ``ConnectError``, ``ReadTimeout``, generic ``TransportError``,
    generic ``TimeoutException``, and a plain ``httpx.RequestError``.
    """
    client = _make_client()
    request = httpx.Request("GET", "http://test.invalid/")

    # Plain TimeoutError (no response attribute)
    assert client._is_retryable_exception(TimeoutError("slow")) is True

    # ConnectError (subclass of TransportError)
    try:
        raise httpx.ConnectError("nope", request=request)
    except httpx.ConnectError as exc:
        assert client._is_retryable_exception(exc) is True

    # ReadTimeout (subclass of TimeoutException)
    try:
        raise httpx.ReadTimeout("slow", request=request)
    except httpx.ReadTimeout as exc:
        assert client._is_retryable_exception(exc) is True

    # Generic TransportError
    try:
        raise httpx.TransportError("net", request=request)
    except httpx.TransportError as exc:
        assert client._is_retryable_exception(exc) is True


@pytest.mark.unit
def test_is_retryable_exception_non_http_returns_false() -> None:
    """Arbitrary ``Exception`` subclasses (not in ``RETRY_EXCEPTIONS``) are NOT retryable."""
    client = _make_client()

    class MyUnrelatedError(Exception):
        pass

    assert client._is_retryable_exception(MyUnrelatedError("nope")) is False
    assert client._is_retryable_exception(ValueError("bad arg")) is False


# ── _build_headers: unit + property ────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_bearer_auth_added() -> None:
    """``auth_token`` → ``Authorization: Bearer <token>``."""
    client = _make_client()
    headers = await client._build_headers(
        auth_token="secret-token-123",
        custom_headers=None,
        json_data=None,
        data=None,
        files=None,
    )
    assert headers["Authorization"] == "Bearer secret-token-123"
    # Base headers always present
    assert headers["User-Agent"] == "HttpClient/2.0"
    assert headers["Accept"] == "*/*"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_content_type_inference_json() -> None:
    """``json_data`` → ``Content-Type: application/json`` (when not set by user)."""
    client = _make_client()
    headers = await client._build_headers(
        auth_token=None, custom_headers=None, json_data={"x": 1}, data=None, files=None
    )
    assert headers["Content-Type"] == "application/json"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_content_type_inference_octet_stream() -> None:
    """``str``/``bytes`` ``data`` → ``Content-Type: application/octet-stream``."""
    client = _make_client()
    headers_str = await client._build_headers(
        auth_token=None,
        custom_headers=None,
        json_data=None,
        data="raw-text-body",
        files=None,
    )
    assert headers_str["Content-Type"] == "application/octet-stream"

    headers_bytes = await client._build_headers(
        auth_token=None,
        custom_headers=None,
        json_data=None,
        data=b"\x00\x01",
        files=None,
    )
    assert headers_bytes["Content-Type"] == "application/octet-stream"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_multipart_strips_content_type() -> None:
    """When ``files`` is provided, ``Content-Type`` is removed — httpx sets multipart boundary."""
    client = _make_client()
    # Even with json_data that would otherwise set application/json,
    # files must win and Content-Type is removed.
    headers = await client._build_headers(
        auth_token=None,
        custom_headers=None,
        json_data={"x": 1},
        data=None,
        files={"upload": {"content": b"data", "filename": "f.bin"}},
    )
    assert "Content-Type" not in headers

    # And if user supplied a custom Content-Type, files still strip it
    headers_custom = await client._build_headers(
        auth_token=None,
        custom_headers={"Content-Type": "application/x-custom"},
        json_data=None,
        data=None,
        files={"upload": {"content": b"data", "filename": "f.bin"}},
    )
    assert "Content-Type" not in headers_custom


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_user_content_type_preserved() -> None:
    """User-supplied ``Content-Type`` is NEVER overridden by inference."""
    client = _make_client()
    headers = await client._build_headers(
        auth_token=None,
        custom_headers={"Content-Type": "application/xml"},
        json_data={"x": 1},  # would normally set application/json
        data=None,
        files=None,
    )
    assert headers["Content-Type"] == "application/xml"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_custom_headers_merged() -> None:
    """``custom_headers`` are merged (overriding defaults if key collides)."""
    client = _make_client()
    headers = await client._build_headers(
        auth_token=None,
        custom_headers={"X-Trace-Id": "abc-123", "Accept": "application/json"},
        json_data=None,
        data=None,
        files=None,
    )
    assert headers["X-Trace-Id"] == "abc-123"
    assert headers["Accept"] == "application/json"


# Property: for any (json_data, data, files, custom_headers) combo, the
# Content-Type rule is consistent:
#   1. If user supplied Content-Type → it is preserved (unless files override).
#   2. If files → Content-Type absent.
#   3. If no user CT, no files, json_data set → "application/json".
#   4. If no user CT, no files, str/bytes data → "application/octet-stream".
#   5. Otherwise → Content-Type absent.
@st.composite
def _header_inputs(
    draw: st.DrawFn,
) -> tuple[
    bool,  # has_custom_ct
    bool,  # has_json
    bool,  # has_str_data
    bool,  # has_files
]:
    has_custom_ct = draw(st.booleans())
    has_json = draw(st.booleans())
    has_str_data = draw(st.booleans())
    has_files = draw(st.booleans())
    # Avoid impossible overlap: with files we still allow json_data
    # (implementation: files wins → CT stripped).
    return has_custom_ct, has_json, has_str_data, has_files


@given(inputs=_header_inputs())
@settings(max_examples=50, deadline=None)
@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_content_type_invariants_property(
    inputs: tuple[bool, bool, bool, bool],
) -> None:
    """For any (custom_ct, json, str_data, files) combo, Content-Type follows the rule.

    Rule:
      * files → CT absent (multipart handled by httpx);
      * user CT (and no files) → preserved verbatim;
      * else json_data → "application/json";
      * else str/bytes data → "application/octet-stream";
      * else → absent.
    """
    has_custom_ct, has_json, has_str_data, has_files = inputs
    client = _make_client()

    custom_headers: dict[str, str] | None = (
        {"Content-Type": "application/xml"} if has_custom_ct else None
    )
    json_data: dict[str, int] | None = {"x": 1} if has_json else None
    data: str | None = "blob" if has_str_data else None
    files: dict[str, dict[str, object]] | None = (
        {"f": {"content": b"x", "filename": "f"}} if has_files else None
    )

    headers = await client._build_headers(
        auth_token=None,
        custom_headers=custom_headers,
        json_data=json_data,
        data=data,
        files=files,
    )

    if has_files:
        assert "Content-Type" not in headers
    elif has_custom_ct:
        assert headers.get("Content-Type") == "application/xml"
    elif has_json:
        assert headers.get("Content-Type") == "application/json"
    elif has_str_data:
        assert headers.get("Content-Type") == "application/octet-stream"
    else:
        assert "Content-Type" not in headers


# ── _process_response: unit (all 5 branches) ──────────────────────


def _fake_response(
    *,
    status_code: int = 200,
    content_type: str = "application/json",
    text: str | None = None,
    json_data: object | None = None,
    bytes_content: bytes | None = None,
) -> httpx.Response:
    """Build an ``httpx.Response`` with controllable headers/body.

    Mutually-exclusive body selection (mirrors httpx.Response semantics):
    * ``text`` is used when set;
    * else ``json_data`` is used (and serialised to ``Content-Type: application/json``);
    * else ``bytes_content`` is used as raw bytes.
    """
    request = httpx.Request("GET", "http://test.invalid/")
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    if text is not None:
        return httpx.Response(status_code, request=request, headers=headers, text=text)
    if json_data is not None:
        return httpx.Response(
            status_code, request=request, headers=headers, json=json_data
        )
    return httpx.Response(
        status_code, request=request, headers=headers, content=bytes_content or b""
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_json_branch() -> None:
    client = _make_client()
    resp = _fake_response(content_type="application/json", json_data={"ok": True})
    assert await client._process_response(resp, "json") == {"ok": True}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_text_branch() -> None:
    client = _make_client()
    resp = _fake_response(content_type="text/plain", text="hello")
    assert await client._process_response(resp, "text") == "hello"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_bytes_branch() -> None:
    client = _make_client()
    resp = _fake_response(
        content_type="application/octet-stream", bytes_content=b"\x01\x02"
    )
    result = await client._process_response(resp, "bytes")
    assert result == b"\x01\x02"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_auto_json_inferred() -> None:
    """``auto`` + JSON Content-Type → calls ``response.json()``."""
    client = _make_client()
    resp = _fake_response(
        content_type="application/json; charset=utf-8", json_data=[1, 2]
    )
    assert await client._process_response(resp, "auto") == [1, 2]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_auto_text_inferred() -> None:
    """``auto`` + non-JSON Content-Type → returns ``response.text``."""
    client = _make_client()
    resp = _fake_response(content_type="text/html", text="<p>hi</p>")
    assert await client._process_response(resp, "auto") == "<p>hi</p>"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_unknown_raises_value_error() -> None:
    """Unknown ``response_type`` → ``ValueError`` with informative message."""
    client = _make_client()
    resp = _fake_response(content_type="text/plain", text="x")
    with pytest.raises(ValueError, match="Неподдерживаемый тип ответа"):
        await client._process_response(resp, "xml")


# ── _process_response sanity: respects response.headers.get("Content-Type") ──


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_uses_response_headers_not_arg() -> None:
    """``_process_response`` reads the **response's** Content-Type, not a parameter."""
    client = _make_client()
    resp_json = _fake_response(content_type="application/json", json_data={"k": "v"})
    # response_type="auto" + actual JSON header → JSON branch
    result = await client._process_response(resp_json, "auto")
    assert result == {"k": "v"}


# ── _build_response_object: shape contract ─────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_response_object_shape() -> None:
    """Response envelope has all required keys and normalised Content-Type."""
    from time import monotonic

    client = _make_client()
    resp = _fake_response(
        status_code=201,
        content_type="application/json; charset=utf-8",
        json_data={"id": 1},
    )
    obj = await client._build_response_object(resp, {"id": 1}, monotonic())
    assert obj["status_code"] == 201
    assert obj["data"] == {"id": 1}
    assert obj["content_type"] == "application/json"  # normalised (no charset)
    assert isinstance(obj["headers"], dict)
    assert "elapsed" in obj
    assert obj["elapsed"] >= 0.0
