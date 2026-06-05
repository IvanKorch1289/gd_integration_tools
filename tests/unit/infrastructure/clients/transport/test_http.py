"""Unit-tests for HttpClient (httpx transport)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.backend.infrastructure.clients.transport.http import (
    BaseHttpClient,
    HttpClient,
    get_http_client,
    get_http_client_dependency,
)


class _FakeHttpSettings:
    limit = 100
    limit_per_host = 20
    keepalive_timeout = 300
    connect_timeout = 10
    sock_read_timeout = 15
    total_timeout = 30
    max_retries = 1
    retry_backoff_factor = 0.0
    purging_interval = 300
    enable_connection_purging = False
    circuit_breaker_max_failures = 5
    circuit_breaker_reset_timeout = 30
    ssl_verify = False


@pytest.fixture(autouse=True)
def _clear_dependency_cache() -> None:
    get_http_client_dependency.cache_clear()


@pytest.fixture
def fake_settings() -> _FakeHttpSettings:
    return _FakeHttpSettings()


@pytest.fixture
def mock_cb() -> MagicMock:
    cb = MagicMock()
    cb.record_success = MagicMock()
    cb.record_failure = MagicMock()
    cb.check_state = AsyncMock()
    return cb


@pytest.fixture
def mock_registry() -> MagicMock:
    reg = MagicMock()
    reg.create_task = MagicMock(return_value=MagicMock())
    return reg


@pytest.fixture
def mock_logger() -> MagicMock:
    return MagicMock()


@pytest.fixture
def http_client(
    fake_settings: _FakeHttpSettings,
    mock_cb: MagicMock,
    mock_registry: MagicMock,
    mock_logger: MagicMock,
) -> HttpClient:
    with patch("src.backend.infrastructure.clients.transport.http.settings") as m_settings:
        m_settings.http_base_settings = fake_settings
        with patch(
            "src.backend.infrastructure.clients.transport.http.get_circuit_breaker",
            return_value=mock_cb,
        ):
            with patch(
                "src.backend.infrastructure.clients.transport.http.get_task_registry",
                return_value=mock_registry,
            ):
                client = HttpClient()
                client.logger = mock_logger
                yield client


@pytest.fixture
def mock_httpx() -> AsyncMock:
    client = AsyncMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def patched_client(http_client: HttpClient, mock_httpx: AsyncMock) -> HttpClient:
    with patch(
        "src.backend.infrastructure.clients.transport.http.httpx.AsyncClient",
        return_value=mock_httpx,
    ):
        yield http_client


def _response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    text: str = "",
    json_data: Any = None,
    content: bytes = b"",
    raise_exc: Exception | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    resp.content = content
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(return_value={})
    if raise_exc:
        resp.raise_for_status = MagicMock(side_effect=raise_exc)
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _status_error(status_code: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    req = MagicMock()
    return httpx.HTTPStatusError("err", request=req, response=resp)


class _FakeTask:
    """Mock asyncio.Task that supports await and cancel."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def done(self) -> bool:
        return self._cancelled

    def __await__(self):
        if self._cancelled:
            raise asyncio.CancelledError()
        return iter([])


# --- make_request success paths ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_json_success(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    resp = _response(status_code=200, json_data={"ok": True}, headers={"Content-Type": "application/json"})
    mock_httpx.request = AsyncMock(return_value=resp)

    result = await patched_client.make_request("GET", "http://example.com/api")

    assert result["status_code"] == 200
    assert result["data"] == {"ok": True}
    assert result["content_type"] == "application/json"
    assert "elapsed" in result
    assert "headers" in result
    mock_httpx.request.assert_awaited_once()
    mock_cb.record_success.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_text_response(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200, text="hello", headers={"Content-Type": "text/plain"})
    mock_httpx.request = AsyncMock(return_value=resp)

    result = await patched_client.make_request("GET", "http://example.com", response_type="text")

    assert result["data"] == "hello"
    assert result["content_type"] == "text/plain"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_bytes_response(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200, content=b"\x00\x01", headers={"Content-Type": "application/octet-stream"})
    mock_httpx.request = AsyncMock(return_value=resp)

    result = await patched_client.make_request("GET", "http://example.com", response_type="bytes")

    assert result["data"] == b"\x00\x01"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_auto_json(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200, json_data={"auto": True}, headers={"Content-Type": "application/json; charset=utf-8"})
    mock_httpx.request = AsyncMock(return_value=resp)

    result = await patched_client.make_request("GET", "http://example.com")

    assert result["data"] == {"auto": True}
    assert result["content_type"] == "application/json"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_auto_text(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200, text="plain text", headers={"Content-Type": "text/html"})
    mock_httpx.request = AsyncMock(return_value=resp)

    result = await patched_client.make_request("GET", "http://example.com")

    assert result["data"] == "plain text"
    assert result["content_type"] == "text/html"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_with_auth_token(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("GET", "http://example.com", auth_token="secret")

    headers = mock_httpx.request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_with_custom_headers(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("GET", "http://example.com", headers={"X-Custom": "val"})

    headers = mock_httpx.request.call_args.kwargs["headers"]
    assert headers["X-Custom"] == "val"
    assert headers["User-Agent"] == "HttpClient/2.0"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_with_files(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    files = {"file": {"content": b"data", "filename": "test.txt", "content_type": "text/plain"}}
    await patched_client.make_request("POST", "http://example.com", files=files)

    call_kwargs = mock_httpx.request.call_args.kwargs
    assert "files" in call_kwargs
    assert call_kwargs["files"]["file"] == ("test.txt", b"data", "text/plain")
    headers = call_kwargs["headers"]
    assert "Content-Type" not in headers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_with_data_dict(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("POST", "http://example.com", data={"key": "value"})

    call_kwargs = mock_httpx.request.call_args.kwargs
    assert call_kwargs["data"] == {"key": "value"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_with_content_str(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("POST", "http://example.com", data="raw string")

    call_kwargs = mock_httpx.request.call_args.kwargs
    assert call_kwargs["content"] == "raw string"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_with_content_bytes(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("POST", "http://example.com", data=b"raw bytes")

    call_kwargs = mock_httpx.request.call_args.kwargs
    assert call_kwargs["content"] == b"raw bytes"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_passes_params(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("GET", "http://example.com", params={"page": 1})

    assert mock_httpx.request.call_args.kwargs["params"] == {"page": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_method_uppercase(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request("get", "http://example.com")

    assert mock_httpx.request.call_args.kwargs["method"] == "GET"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_timeout_overrides(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=200)
    mock_httpx.request = AsyncMock(return_value=resp)

    await patched_client.make_request(
        "GET",
        "http://example.com",
        connect_timeout=5.0,
        read_timeout=20.0,
        total_timeout=60.0,
    )

    timeout = mock_httpx.request.call_args.kwargs["timeout"]
    assert timeout.connect == 5.0
    assert timeout.read == 20.0
    assert timeout.pool == 60.0


# --- make_request error / retry paths ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_raise_for_status_false_returns_error_response(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    resp = _response(status_code=404, text="not found")
    mock_httpx.request = AsyncMock(return_value=resp)

    result = await patched_client.make_request("GET", "http://example.com", raise_for_status=False)

    assert result["status_code"] == 404
    assert result["data"] == "not found"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_raise_for_status_true_on_4xx_raises(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    exc = _status_error(404)
    resp = _response(status_code=404, raise_exc=exc)
    mock_httpx.request = AsyncMock(return_value=resp)

    with pytest.raises(httpx.HTTPStatusError):
        await patched_client.make_request("GET", "http://example.com", raise_for_status=True)

    mock_cb.record_failure.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_retry_on_retryable_status_then_success(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    fail_exc = _status_error(503)
    fail_resp = _response(status_code=503, raise_exc=fail_exc)
    ok_resp = _response(status_code=200, json_data={"ok": True})
    mock_httpx.request = AsyncMock(side_effect=[fail_resp, ok_resp])

    result = await patched_client.make_request("GET", "http://example.com")

    assert result["status_code"] == 200
    assert mock_httpx.request.await_count == 2
    mock_cb.record_success.assert_called_once()
    mock_cb.record_failure.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_retry_exhausted_raises(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    exc = _status_error(503)
    resp = _response(status_code=503, raise_exc=exc)
    mock_httpx.request = AsyncMock(side_effect=[resp, resp])

    with pytest.raises(httpx.HTTPStatusError):
        await patched_client.make_request("GET", "http://example.com", raise_for_status=True)

    assert mock_httpx.request.await_count == 2
    mock_cb.record_failure.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_network_error_retry_then_success(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    mock_httpx.request = AsyncMock(side_effect=[httpx.ConnectError("down"), _response(status_code=200)])

    result = await patched_client.make_request("GET", "http://example.com")

    assert result["status_code"] == 200
    assert mock_httpx.request.await_count == 2
    mock_cb.record_success.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_network_error_exhausted_no_raise(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    mock_httpx.request = AsyncMock(side_effect=httpx.ConnectError("network down"))

    result = await patched_client.make_request("GET", "http://example.com", raise_for_status=False)

    assert result["status_code"] is None
    assert "network down" in result["error"]
    mock_cb.record_failure.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_timeout_error_retry(patched_client: HttpClient, mock_httpx: AsyncMock) -> None:
    mock_httpx.request = AsyncMock(side_effect=[httpx.TimeoutException("slow"), _response(status_code=200)])

    result = await patched_client.make_request("GET", "http://example.com")

    assert result["status_code"] == 200
    assert mock_httpx.request.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_request_non_retryable_error_raises(patched_client: HttpClient, mock_httpx: AsyncMock, mock_cb: MagicMock) -> None:
    mock_httpx.request = AsyncMock(side_effect=ValueError("bad arg"))

    with pytest.raises(ValueError, match="bad arg"):
        await patched_client.make_request("GET", "http://example.com")

    mock_cb.record_failure.assert_called_once()


# --- _is_retryable_exception ---


@pytest.mark.unit
@pytest.mark.parametrize(
    "status_code,expected",
    [
        (408, True),
        (409, True),
        (425, True),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (400, False),
        (404, False),
        (200, False),
    ],
)
def test_is_retryable_exception_status_codes(http_client: HttpClient, status_code: int, expected: bool) -> None:
    exc = _status_error(status_code)
    assert http_client._is_retryable_exception(exc) is expected


@pytest.mark.unit
def test_is_retryable_exception_transport(http_client: HttpClient) -> None:
    assert http_client._is_retryable_exception(httpx.ConnectError("x")) is True
    assert http_client._is_retryable_exception(httpx.TimeoutException("x")) is True


@pytest.mark.unit
def test_is_retryable_exception_consts(http_client: HttpClient) -> None:
    assert http_client._is_retryable_exception(httpx.HTTPError("x")) is True
    assert http_client._is_retryable_exception(asyncio.TimeoutError("x")) is True


# --- _build_headers ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_default(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, None, None, None, None)
    assert headers["User-Agent"] == "HttpClient/2.0"
    assert headers["Accept"] == "*/*"
    assert headers["Accept-Encoding"] == "gzip, deflate, br"
    assert "Authorization" not in headers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_auth_token(http_client: HttpClient) -> None:
    headers = await http_client._build_headers("tok", None, None, None, None)
    assert headers["Authorization"] == "Bearer tok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_custom_override(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, {"User-Agent": "custom"}, None, None, None)
    assert headers["User-Agent"] == "custom"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_json_content_type(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, None, {"a": 1}, None, None)
    assert headers["Content-Type"] == "application/json"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_data_str_content_type(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, None, None, "text", None)
    assert headers["Content-Type"] == "application/octet-stream"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_data_bytes_content_type(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, None, None, b"bin", None)
    assert headers["Content-Type"] == "application/octet-stream"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_custom_content_type_preserved(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, {"Content-Type": "text/xml"}, {"a": 1}, None, None)
    assert headers["Content-Type"] == "text/xml"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_headers_files_removes_content_type(http_client: HttpClient) -> None:
    headers = await http_client._build_headers(None, {"Content-Type": "application/json"}, None, None, {"f": {"content": b"x"}})
    assert "Content-Type" not in headers


# --- _prepare_request_kwargs ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_json_and_data_raises(http_client: HttpClient) -> None:
    with pytest.raises(ValueError, match="json нельзя передавать вместе с data/files"):
        await http_client._prepare_request_kwargs({"a": 1}, {"b": 2}, None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_files(http_client: HttpClient) -> None:
    files = {"file": {"content": b"data", "filename": "x.txt", "content_type": "text/plain"}}
    kwargs = await http_client._prepare_request_kwargs(None, None, files)
    assert kwargs["files"]["file"] == ("x.txt", b"data", "text/plain")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_files_with_data_dict(http_client: HttpClient) -> None:
    files = {"file": {"content": b"data"}}
    kwargs = await http_client._prepare_request_kwargs({"key": None, "ok": 1}, None, files)
    assert kwargs["files"]["file"] == ("file", b"data", "application/octet-stream")
    assert kwargs["data"] == {"key": "", "ok": "1"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_json(http_client: HttpClient) -> None:
    with patch(
        "src.backend.infrastructure.clients.transport.http.json_dumps",
        return_value=b'{"a":1}',
    ):
        kwargs = await http_client._prepare_request_kwargs(None, {"a": 1}, None)
        assert kwargs["content"] == b'{"a":1}'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_data_dict(http_client: HttpClient) -> None:
    kwargs = await http_client._prepare_request_kwargs({"a": 1}, None, None)
    assert kwargs["data"] == {"a": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_content_str(http_client: HttpClient) -> None:
    kwargs = await http_client._prepare_request_kwargs("text", None, None)
    assert kwargs["content"] == "text"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_content_bytes(http_client: HttpClient) -> None:
    kwargs = await http_client._prepare_request_kwargs(b"bytes", None, None)
    assert kwargs["content"] == b"bytes"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_request_kwargs_empty(http_client: HttpClient) -> None:
    kwargs = await http_client._prepare_request_kwargs(None, None, None)
    assert kwargs == {}


# --- _update_metrics ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_metrics(http_client: HttpClient) -> None:
    await http_client._update_metrics(start_time=0.0, success=True)
    assert http_client.metrics["total_requests"] == 1
    assert http_client.metrics["successful_requests"] == 1
    assert http_client.metrics["failed_requests"] == 0

    await http_client._update_metrics(start_time=0.0, success=False)
    assert http_client.metrics["total_requests"] == 2
    assert http_client.metrics["failed_requests"] == 1


# --- _build_response_object ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_response_object(http_client: HttpClient) -> None:
    resp = MagicMock()
    resp.status_code = 201
    resp.headers = {"Content-Type": "application/json; charset=utf-8"}
    result = await http_client._build_response_object(resp, {"a": 1}, start_time=0.0)
    assert result["status_code"] == 201
    assert result["data"] == {"a": 1}
    assert result["content_type"] == "application/json"
    assert "headers" in result
    assert "elapsed" in result


# --- _handle_final_error ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_final_error_status_error(http_client: HttpClient) -> None:
    exc = _status_error(500, headers={"X-Err": "fail"})
    result = await http_client._handle_final_error(exc, start_time=0.0)
    assert result["status_code"] == 500
    assert result["headers"] == {"X-Err": "fail"}
    assert result["error"] == "err"
    assert "elapsed" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_final_error_generic(http_client: HttpClient) -> None:
    result = await http_client._handle_final_error(ValueError("oops"), start_time=0.0)
    assert result["status_code"] is None
    assert result["headers"] == {}
    assert result["error"] == "oops"


# --- _process_response ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_bytes(http_client: HttpClient) -> None:
    resp = MagicMock()
    resp.content = b"bin"
    assert await http_client._process_response(resp, "bytes") == b"bin"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_text(http_client: HttpClient) -> None:
    resp = MagicMock()
    resp.text = "txt"
    assert await http_client._process_response(resp, "text") == "txt"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_json(http_client: HttpClient) -> None:
    resp = MagicMock()
    resp.json = MagicMock(return_value={"j": 1})
    assert await http_client._process_response(resp, "json") == {"j": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_auto_json(http_client: HttpClient) -> None:
    resp = MagicMock()
    resp.headers = {"Content-Type": "application/json"}
    resp.json = MagicMock(return_value={"j": 1})
    assert await http_client._process_response(resp, "auto") == {"j": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_auto_text(http_client: HttpClient) -> None:
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/plain"}
    resp.text = "plain"
    assert await http_client._process_response(resp, "auto") == "plain"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_response_invalid_type_raises(http_client: HttpClient) -> None:
    with pytest.raises(ValueError, match="Неподдерживаемый тип ответа"):
        await http_client._process_response(MagicMock(), "xml")


# --- session lifecycle ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_session_creates_client(http_client: HttpClient) -> None:
    with patch("src.backend.infrastructure.clients.transport.http.httpx.AsyncClient") as MockClient:
        mock = AsyncMock()
        mock.is_closed = False
        MockClient.return_value = mock
        await http_client._ensure_session()
        assert http_client.client is mock
        MockClient.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_session_reuses_open_client(http_client: HttpClient) -> None:
    with patch("src.backend.infrastructure.clients.transport.http.httpx.AsyncClient") as MockClient:
        mock = AsyncMock()
        mock.is_closed = False
        MockClient.return_value = mock
        await http_client._ensure_session()
        await http_client._ensure_session()
        MockClient.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_session_recreates_closed_client(http_client: HttpClient) -> None:
    with patch("src.backend.infrastructure.clients.transport.http.httpx.AsyncClient") as MockClient:
        mock1 = AsyncMock()
        mock1.is_closed = True
        mock2 = AsyncMock()
        mock2.is_closed = False
        MockClient.side_effect = [mock1, mock2]
        await http_client._ensure_session()
        first = http_client.client
        await http_client._ensure_session()
        assert http_client.client is mock2
        assert first is mock1
        assert MockClient.call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_session(http_client: HttpClient) -> None:
    mock = AsyncMock()
    mock.is_closed = False
    http_client.client = mock
    await http_client._close_session()
    mock.aclose.assert_awaited_once()
    assert http_client.client is None


# --- purger ---


@pytest.mark.unit
def test_start_purger_creates_when_none(http_client: HttpClient) -> None:
    reg = MagicMock()
    reg.create_task = MagicMock(return_value=MagicMock())
    with patch(
        "src.backend.infrastructure.clients.transport.http.get_task_registry",
        return_value=reg,
    ):
        http_client._start_purger_if_needed()
    reg.create_task.assert_called_once()


@pytest.mark.unit
def test_start_purger_skips_when_alive(http_client: HttpClient) -> None:
    mock_task = MagicMock()
    mock_task.done.return_value = False
    http_client.purger_task = mock_task
    reg = MagicMock()
    with patch(
        "src.backend.infrastructure.clients.transport.http.get_task_registry",
        return_value=reg,
    ):
        http_client._start_purger_if_needed()
    reg.create_task.assert_not_called()


@pytest.mark.unit
def test_start_purger_replaces_when_done(http_client: HttpClient) -> None:
    mock_task = MagicMock()
    mock_task.done.return_value = True
    http_client.purger_task = mock_task
    reg = MagicMock()
    reg.create_task = MagicMock(return_value=MagicMock())
    with patch(
        "src.backend.infrastructure.clients.transport.http.get_task_registry",
        return_value=reg,
    ):
        http_client._start_purger_if_needed()
    reg.create_task.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_cancels_purger_and_closes_session(http_client: HttpClient) -> None:
    mock_task = _FakeTask()
    http_client.purger_task = mock_task

    mock_client = AsyncMock()
    mock_client.is_closed = False
    http_client.client = mock_client

    await http_client.close()

    assert mock_task.done() is True
    assert http_client.purger_task is None
    mock_client.aclose.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_purger_closes_idle_session(http_client: HttpClient) -> None:
    http_client.settings.enable_connection_purging = True
    http_client.settings.keepalive_timeout = 1
    http_client.settings.purging_interval = 0.1

    mock_client = AsyncMock()
    mock_client.is_closed = False
    http_client.client = mock_client
    http_client.last_activity = 0.0
    http_client.active_requests = 0

    calls = 0

    async def fake_sleep(_: float) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", fake_sleep):
        await http_client._connection_purger()

    mock_client.aclose.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_purger_skips_when_disabled(http_client: HttpClient) -> None:
    http_client.settings.enable_connection_purging = False

    mock_client = AsyncMock()
    http_client.client = mock_client

    async def fake_sleep(_: float) -> None:
        raise asyncio.CancelledError()

    with patch("asyncio.sleep", fake_sleep):
        await http_client._connection_purger()

    mock_client.aclose.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_purger_skips_when_active_requests(http_client: HttpClient) -> None:
    http_client.settings.enable_connection_purging = True
    http_client.active_requests = 1
    http_client.last_activity = 0.0

    mock_client = AsyncMock()
    http_client.client = mock_client

    async def fake_sleep(_: float) -> None:
        raise asyncio.CancelledError()

    with patch("asyncio.sleep", fake_sleep):
        await http_client._connection_purger()

    mock_client.aclose.assert_not_called()


# --- logging ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_request(http_client: HttpClient) -> None:
    logger = http_client.logger
    await http_client._log_request(
        method="POST",
        url="http://example.com",
        headers={
            "Authorization": "secret",
            "X-Api-Key": "key",
            "Cookie": "c=1",
            "Normal": "ok",
        },
        params={"q": 1},
        data="data",
        files=None,
    )
    logger.debug.assert_called_once()
    extra = logger.debug.call_args.kwargs["extra"]
    assert extra["method"] == "POST"
    assert extra["headers"]["Authorization"] == "***MASKED***"
    assert extra["headers"]["Cookie"] == "***MASKED***"
    assert extra["headers"]["Normal"] == "ok"
    assert extra["data"] == "data"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_request_with_files(http_client: HttpClient) -> None:
    logger = http_client.logger
    files = {"doc": {"content": b"12345", "filename": "doc.txt", "content_type": "text/plain"}}
    await http_client._log_request(
        method="POST",
        url="http://example.com",
        headers={},
        params=None,
        data={"key": "value"},
        files=files,
    )
    extra = logger.debug.call_args.kwargs["extra"]
    assert extra["files"]["doc"]["filename"] == "doc.txt"
    assert extra["files"]["doc"]["size"] == 5
    assert extra["data"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_request_truncates_long_data(http_client: HttpClient) -> None:
    logger = http_client.logger
    long_data = "x" * 250
    await http_client._log_request("GET", "http://x", {}, None, long_data, None)
    extra = logger.debug.call_args.kwargs["extra"]
    assert extra["data"].endswith("...")
    assert len(extra["data"]) == 203


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_response(http_client: HttpClient) -> None:
    logger = http_client.logger
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/json"}
    await http_client._log_response(resp, {"key": "value"})
    extra = logger.debug.call_args.kwargs["extra"]
    assert extra["status"] == 200
    assert extra["content"] == "{'key': 'value'}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_response_truncates_long_content(http_client: HttpClient) -> None:
    logger = http_client.logger
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    long_content = "x" * 600
    await http_client._log_response(resp, long_content)
    extra = logger.debug.call_args.kwargs["extra"]
    assert extra["content"].endswith("...")
    assert len(extra["content"]) == 503


# --- public helpers ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_http_client_yields_client() -> None:
    async with get_http_client() as client:
        assert isinstance(client, HttpClient)


@pytest.mark.unit
def test_get_http_client_dependency_returns_singleton() -> None:
    c1 = get_http_client_dependency()
    c2 = get_http_client_dependency()
    assert c1 is c2
    assert isinstance(c1, HttpClient)
