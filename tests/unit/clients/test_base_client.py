"""Тесты ``BaseExternalAPIClient`` и базового ``HttpClient``.

Покрывает:
- ``BaseExternalAPIClient``: построение URL, headers (auth/extra/WAF
  passthrough), делегирование в ``HttpClient.make_request``,
  обработка SecretStr-API key, _auth_scheme подмена.
- ``HttpClient``: retry policy (3 попытки, exponential backoff через
  ``tenacity``), circuit-breaker fail counter, проброс custom headers,
  поведение на retry-able vs non-retry-able ошибках.

Для retry/CB-тестов используется ``httpx.MockTransport``: реальный
``httpx.AsyncClient`` создаётся через ``HttpClient._create_new_session``
и заменяется уже сконфигурированным транспортом.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.services.core.base_external_api import BaseExternalAPIClient

# ---------------------------------------------------------------------------
# BaseExternalAPIClient — wrapper-level тесты (mock HttpClient)
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Минимальные settings для ``BaseExternalAPIClient``."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.test/",
        prod_url: str | None = None,
        api_key: Any = None,
        endpoints: dict[str, str] | None = None,
        use_waf: bool = False,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url
        if prod_url is not None:
            self.prod_url = prod_url
        self.api_key = api_key
        self.endpoints = endpoints or {}
        self.use_waf = use_waf
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout


@pytest.fixture
def fake_settings() -> _FakeSettings:
    return _FakeSettings(
        base_url="https://api.test/",
        api_key="secret-key",
        endpoints={"items": "v1/items", "ping": "v1/ping"},
    )


@pytest.fixture
def client_with_mock(
    fake_settings: _FakeSettings, monkeypatch: pytest.MonkeyPatch
) -> tuple[BaseExternalAPIClient, AsyncMock]:
    """``BaseExternalAPIClient`` с подменённым ``self.client`` на AsyncMock.

    Позволяет проверять wrapper-логику без реальных HTTP-запросов.
    """
    client = BaseExternalAPIClient(settings=fake_settings, name="test_svc")
    mock_http = MagicMock()
    mock_http.make_request = AsyncMock(
        return_value={"status_code": 200, "data": {"ok": True}}
    )
    client.client = mock_http
    return client, mock_http.make_request


def test_url_resolves_endpoint_key(fake_settings: _FakeSettings) -> None:
    """``_url(key)`` склеивает base_url и endpoints[key]."""
    client = BaseExternalAPIClient(settings=fake_settings, name="t")
    assert client._url("items") == "https://api.test/v1/items"


def test_url_unknown_endpoint_returns_base(
    fake_settings: _FakeSettings,
) -> None:
    """Неизвестный endpoint key → возвращается base_url (без падения)."""
    client = BaseExternalAPIClient(settings=fake_settings, name="t")
    # urljoin с пустой строкой = base_url
    assert client._url("missing") == "https://api.test/"


def test_prod_url_takes_precedence_over_base_url() -> None:
    """Если есть prod_url — он приоритетнее base_url."""
    settings = _FakeSettings(
        base_url="https://dev.test/", prod_url="https://prod.test/"
    )
    client = BaseExternalAPIClient(settings=settings)
    assert client.base_url == "https://prod.test/"


def test_headers_include_auth_and_content_type(
    fake_settings: _FakeSettings,
) -> None:
    """По умолчанию формируются Authorization (Bearer) + Content-Type."""
    client = BaseExternalAPIClient(settings=fake_settings, name="t")
    headers = client._headers(use_waf=False)
    assert headers["Authorization"] == "Bearer secret-key"
    assert headers["Content-Type"] == "application/json"


def test_headers_custom_auth_scheme() -> None:
    """``_auth_scheme`` можно переопределить (Token / etc)."""

    class TokenClient(BaseExternalAPIClient):
        _auth_scheme = "Token"

    client = TokenClient(
        settings=_FakeSettings(api_key="abc"), name="token_svc"
    )
    headers = client._headers(use_waf=False)
    assert headers["Authorization"] == "Token abc"


def test_headers_secret_str_api_key_unwrapped() -> None:
    """SecretStr-подобный объект разворачивается через get_secret_value()."""

    class _Secret:
        def __init__(self, value: str) -> None:
            self._value = value

        def get_secret_value(self) -> str:
            return self._value

    client = BaseExternalAPIClient(
        settings=_FakeSettings(api_key=_Secret("hidden")), name="t"
    )
    headers = client._headers(use_waf=False)
    assert headers["Authorization"] == "Bearer hidden"


def test_headers_extra_passthrough(fake_settings: _FakeSettings) -> None:
    """Custom headers через ``extra=`` пробрасываются и могут переопределять."""
    client = BaseExternalAPIClient(settings=fake_settings, name="t")
    headers = client._headers(
        extra={"X-Trace-Id": "abc-123", "Content-Type": "text/plain"},
        use_waf=False,
    )
    assert headers["X-Trace-Id"] == "abc-123"
    assert headers["Content-Type"] == "text/plain"  # extra перезаписал default
    assert headers["Authorization"] == "Bearer secret-key"


def test_headers_no_api_key_no_authorization() -> None:
    """Если api_key отсутствует — header Authorization не выставляется."""
    settings = _FakeSettings(api_key=None)
    client = BaseExternalAPIClient(settings=settings, name="t")
    headers = client._headers(use_waf=False)
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"


def test_timeouts_from_settings(fake_settings: _FakeSettings) -> None:
    """``_timeouts`` использует значения из settings."""
    client = BaseExternalAPIClient(settings=fake_settings, name="t")
    timeouts = client._timeouts()
    assert timeouts["connect_timeout"] == 5.0
    assert timeouts["read_timeout"] == 10.0
    assert timeouts["total_timeout"] == 15.0


async def test_request_delegates_to_http_client(
    client_with_mock: tuple[BaseExternalAPIClient, AsyncMock],
) -> None:
    """``_request`` вызывает ``client.make_request`` с правильными параметрами."""
    client, make_request = client_with_mock
    result = await client._request(
        "GET", "https://api.test/v1/items", params={"q": "x"}
    )
    assert result == {"status_code": 200, "data": {"ok": True}}

    make_request.assert_awaited_once()
    kwargs = make_request.await_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "https://api.test/v1/items"
    assert kwargs["params"] == {"q": "x"}
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"
    # timeout-параметры тоже пробрасываются
    assert kwargs["connect_timeout"] == 5.0
    assert kwargs["read_timeout"] == 10.0


async def test_request_passes_custom_headers(
    client_with_mock: tuple[BaseExternalAPIClient, AsyncMock],
) -> None:
    """Custom headers через ``headers=`` пробрасываются в HttpClient."""
    client, make_request = client_with_mock
    await client._request(
        "POST",
        "https://api.test/v1/items",
        json={"a": 1},
        headers={"X-Trace-Id": "trace-7"},
    )
    headers = make_request.await_args.kwargs["headers"]
    assert headers["X-Trace-Id"] == "trace-7"


async def test_request_propagates_response_type_and_raise(
    client_with_mock: tuple[BaseExternalAPIClient, AsyncMock],
) -> None:
    """``response_type`` / ``raise_for_status`` пробрасываются только если заданы."""
    client, make_request = client_with_mock

    await client._request(
        "GET", "https://api.test/v1/items", response_type="json"
    )
    kwargs1 = make_request.await_args.kwargs
    assert kwargs1.get("response_type") == "json"

    make_request.reset_mock()
    await client._request("GET", "https://api.test/v1/items")
    kwargs2 = make_request.await_args.kwargs
    # без явного указания — параметры не передаются
    assert "response_type" not in kwargs2
    assert "raise_for_status" not in kwargs2


async def test_request_logs_and_reraises_on_failure(
    client_with_mock: tuple[BaseExternalAPIClient, AsyncMock],
) -> None:
    """Ошибка из ``make_request`` логируется и пробрасывается выше."""
    client, make_request = client_with_mock
    make_request.side_effect = httpx.HTTPError("boom")

    with pytest.raises(httpx.HTTPError, match="boom"):
        await client._request("GET", "https://api.test/v1/items")


# ---------------------------------------------------------------------------
# HttpClient — retry / circuit-breaker / custom headers
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает реальные задержки tenacity (multiplier=0 → wait≈0)."""
    from src.core.config.settings import settings as app_settings

    monkeypatch.setattr(
        app_settings.http_base_settings, "retry_backoff_factor", 0.0
    )


def _patched_http_client(handler: httpx.MockTransport):
    """Создаёт HttpClient с подменённой ``_create_new_session`` под MockTransport."""
    from src.infrastructure.clients.transport.http import HttpClient

    client = HttpClient()

    def _fake_create_new_session() -> None:
        client.client = httpx.AsyncClient(transport=handler)

    client._create_new_session = _fake_create_new_session
    return client


class _FlakyHandler:
    """Транспорт, отдающий ошибку первые ``fail_first_n`` раз."""

    def __init__(self, fail_first_n: int = 2, fail_status: int = 503) -> None:
        self.calls = 0
        self.fail_first_n = fail_first_n
        self.fail_status = fail_status
        self.last_request: httpx.Request | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.last_request = request
        if self.calls <= self.fail_first_n:
            return httpx.Response(self.fail_status, text="busy")
        return httpx.Response(200, json={"ok": True})


async def test_http_client_retries_until_success(
    fast_retry: None,
) -> None:
    """3 попытки: первая и вторая — 503, третья — 200."""
    handler = _FlakyHandler(fail_first_n=2)
    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        result = await client.make_request(
            method="GET", url="http://x.test/path"
        )
        assert result["status_code"] == 200
        assert result["data"] == {"ok": True}
        assert handler.calls == 3
    finally:
        await client.close()


async def test_http_client_exhausts_retries_and_raises(
    fast_retry: None,
) -> None:
    """max_retries=3 → итого 4 попытки; если все падают — исключение."""
    handler = _FlakyHandler(fail_first_n=99, fail_status=503)
    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        with pytest.raises(httpx.HTTPError):
            await client.make_request(method="GET", url="http://x.test/p")
        # max_retries (3) + 1 = 4 итоговых попытки
        assert handler.calls == 4
    finally:
        await client.close()


async def test_http_client_does_not_retry_on_non_retryable_status(
    fast_retry: None,
) -> None:
    """404 не входит в retry_status_codes — ровно 1 попытка."""
    handler = _FlakyHandler(fail_first_n=99, fail_status=404)
    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.make_request(method="GET", url="http://x.test/p")
        assert handler.calls == 1
    finally:
        await client.close()


async def test_http_client_circuit_breaker_records_failures(
    fast_retry: None,
) -> None:
    """После исчерпания retry CB фиксирует failure (failure_count > 0)."""
    handler = _FlakyHandler(fail_first_n=99, fail_status=503)
    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        with pytest.raises(httpx.HTTPError):
            await client.make_request(method="GET", url="http://x.test/p")
        assert client.circuit_breaker.failure_count >= 1
    finally:
        await client.close()


async def test_http_client_circuit_breaker_resets_on_success(
    fast_retry: None,
) -> None:
    """``record_success`` вызывается на 200-ответе — failure_count = 0."""
    handler = _FlakyHandler(fail_first_n=0)
    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        result = await client.make_request(
            method="GET", url="http://x.test/p"
        )
        assert result["status_code"] == 200
        assert client.circuit_breaker.failure_count == 0
    finally:
        await client.close()


async def test_http_client_circuit_breaker_opens_after_threshold(
    fast_retry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """После N последовательных провалов CB переходит в OPEN-состояние.

    ``record_failure`` сверяется с ``failure_threshold`` underlying breaker'а;
    адаптер устанавливает его только при ``check_state``. Чтобы первый
    провал гарантированно открыл CB, выставляем порог напрямую в impl.
    """
    from src.core.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings.http_base_settings, "max_retries", 0)

    handler = _FlakyHandler(fail_first_n=99, fail_status=503)
    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)
    # порог = 1: следующий же record_failure переключит CB в OPEN
    client.circuit_breaker._impl._config.failure_threshold = 1

    try:
        with pytest.raises(httpx.HTTPError):
            await client.make_request(method="GET", url="http://x.test/p")
        assert client.circuit_breaker.state == "OPEN"
    finally:
        await client.close()


async def test_http_client_passes_custom_headers(fast_retry: None) -> None:
    """Custom headers пробрасываются на выходящий запрос."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        await client.make_request(
            method="GET",
            url="http://x.test/p",
            headers={"X-Trace-Id": "trace-99", "X-Custom": "v"},
        )
        # httpx нормализует имена headers в lower-case
        assert captured.get("x-trace-id") == "trace-99"
        assert captured.get("x-custom") == "v"
        # default User-Agent тоже выставлен
        assert "user-agent" in captured
    finally:
        await client.close()


async def test_http_client_auth_token_sets_authorization(
    fast_retry: None,
) -> None:
    """``auth_token=`` транслируется в Authorization: Bearer <token>."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = _patched_http_client(transport)

    try:
        await client.make_request(
            method="GET",
            url="http://x.test/p",
            auth_token="my-token",  # noqa: S106 — тестовый токен
        )
        assert captured.get("authorization") == "Bearer my-token"
    finally:
        await client.close()
