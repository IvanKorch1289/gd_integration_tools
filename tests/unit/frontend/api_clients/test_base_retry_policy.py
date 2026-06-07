"""Tests for TD-012: per-path retry policy в BaseAPIClient.

Sprint 46 W1: configurable retry policy per-endpoint.

Покрывает:
- Default health paths (``/health``, ``/ready``, ``/api/v1/health/components``) → 0 retries.
- Constructor arg ``retry_overrides`` (exact path → max_retries) применяется.
- Default paths → ``self._max_retries``.
- Overrides can disable retry (value 0).
- Built-in no-retry paths не могут быть re-enabled (для упрощения политики).
- Retry на 5xx/408/429 НЕ происходит при ``_get_max_retries_for_path`` = 0.
- Retry происходит при default policy.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient


def _make_503_response() -> MagicMock:
    """Build a mock httpx.Response with status 503."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 503
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = {"error": "service unavailable"}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=resp
    )
    return resp


def _make_200_response(body: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock httpx.Response with status 200."""
    body = body if body is not None else {"ok": True}
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = body
    resp.text = ""
    resp.raise_for_status.return_value = None
    return resp


def _count_httpx_calls(client: BaseAPIClient, path: str, side_effect: Any) -> int:
    """Подсчитать количество HTTP-вызовов через мок httpx.Client.

    Args:
        client: инстанс клиента.
        path: URL path для запроса.
        side_effect: mock response или список (для sequence).

    Returns:
        Количество фактических HTTP-запросов.
    """
    mock_client = MagicMock()
    mock_client.request.return_value = side_effect
    with patch.object(httpx, "Client", return_value=mock_client):
        # Disable backoff sleep для скорости тестов
        with patch.object(client, "_sleep_backoff"):
            try:
                if isinstance(side_effect, list):
                    # Multiple attempts
                    for r in side_effect:
                        try:
                            if isinstance(r, Exception):
                                raise r
                            return r
                        except httpx.HTTPStatusError:
                            continue
                # Single-shot path
                if isinstance(side_effect, Exception):
                    raise side_effect
                return side_effect
            except Exception:
                pass
    return mock_client.request.call_count


def _make_context_mock(request_response: Any) -> MagicMock:
    """Build a MagicMock that mimics ``httpx.Client`` context manager.

    ``httpx.Client(timeout=...) as client:`` — ``client`` is the result of
    ``__enter__``. By default MagicMock's ``__enter__`` returns a NEW mock,
    so we explicitly set ``__enter__.return_value = self`` and
    ``__exit__.return_value = False`` to wire calls to ``request`` correctly.
    """
    m = MagicMock()
    m.request.return_value = request_response
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def _count_calls(m: MagicMock) -> int:
    return m.request.call_count


class TestGetMaxRetriesForPath:
    """Pure unit tests для ``_get_max_retries_for_path``."""

    def test_health_path_returns_zero(self) -> None:
        c = BaseAPIClient(max_retries=5)
        assert c._get_max_retries_for_path("/health") == 0

    def test_ready_path_returns_zero(self) -> None:
        c = BaseAPIClient(max_retries=5)
        assert c._get_max_retries_for_path("/ready") == 0

    def test_health_components_path_returns_zero(self) -> None:
        c = BaseAPIClient(max_retries=5)
        assert c._get_max_retries_for_path("/api/v1/health/components") == 0

    def test_default_path_uses_max_retries(self) -> None:
        c = BaseAPIClient(max_retries=3)
        assert c._get_max_retries_for_path("/api/v1/admin/metrics") == 3

    def test_default_path_uses_max_retries_5(self) -> None:
        c = BaseAPIClient(max_retries=5)
        assert c._get_max_retries_for_path("/api/v1/admin/feature-flags") == 5

    def test_override_path_used(self) -> None:
        c = BaseAPIClient(
            max_retries=3, retry_overrides={"/api/v1/admin/feature-flags": 7}
        )
        assert c._get_max_retries_for_path("/api/v1/admin/feature-flags") == 7

    def test_override_path_can_disable(self) -> None:
        c = BaseAPIClient(max_retries=3, retry_overrides={"/api/v1/admin/audit": 0})
        assert c._get_max_retries_for_path("/api/v1/admin/audit") == 0

    def test_override_does_not_apply_to_unrelated_path(self) -> None:
        c = BaseAPIClient(
            max_retries=3, retry_overrides={"/api/v1/admin/feature-flags": 7}
        )
        # /metrics not in overrides → fallthrough to default
        assert c._get_max_retries_for_path("/api/v1/admin/metrics") == 3

    def test_health_path_override_takes_precedence(self) -> None:
        """Built-in no-retry для health — это default, не safety constraint.

        Явный ``retry_overrides={"/health": N}`` позволяет переопределить
        (например, для flaky liveness probe retry помогает). Built-in 0
        срабатывает только если path не указан в ``retry_overrides``.
        """
        c = BaseAPIClient(max_retries=3, retry_overrides={"/health": 10})
        # Explicit override выигрывает над built-in default
        assert c._get_max_retries_for_path("/health") == 10
        # Other health paths сохраняют built-in 0
        assert c._get_max_retries_for_path("/ready") == 0
        assert c._get_max_retries_for_path("/api/v1/health/components") == 0

    def test_constructor_default_no_overrides(self) -> None:
        c = BaseAPIClient()
        assert c._retry_overrides == {}

    def test_constructor_accepts_overrides(self) -> None:
        overrides = {"/x": 5, "/y": 0}
        c = BaseAPIClient(retry_overrides=overrides)
        assert c._retry_overrides == overrides

    def test_constructor_does_not_alias_caller_dict(self) -> None:
        """Mutating original dict после init не должно влиять на client."""
        d = {"/x": 5}
        c = BaseAPIClient(retry_overrides=d)
        d["/y"] = 10
        assert "/y" not in c._retry_overrides


class TestRetryBehaviorWithPathPolicy:
    """Integration: ``_request`` использует ``_get_max_retries_for_path``."""

    def test_health_path_503_makes_single_call(self) -> None:
        """``/health`` + 503 → ровно 1 HTTP-вызов (no retry)."""
        c = BaseAPIClient(max_retries=3)
        resp_503 = _make_503_response()
        mock_client = _make_context_mock(resp_503)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff") as sleep_mock:
                with pytest.raises(httpx.HTTPStatusError):
                    c.get("/health")
        # Exactly 1 attempt: 1 initial + 0 retries
        assert _count_calls(mock_client) == 1
        sleep_mock.assert_not_called()

    def test_default_path_503_makes_4_calls(self) -> None:
        """``/api/v1/x`` + 503 → 1 initial + 3 retries = 4 calls (max_retries=3)."""
        c = BaseAPIClient(max_retries=3)
        resp_503 = _make_503_response()
        mock_client = _make_context_mock(resp_503)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff") as sleep_mock:
                with pytest.raises(httpx.HTTPStatusError):
                    c.get("/api/v1/x")
        assert _count_calls(mock_client) == 4
        # Backoff slept 3 times (between attempts 0→1, 1→2, 2→3)
        assert sleep_mock.call_count == 3

    def test_override_5_makes_6_calls(self) -> None:
        """``retry_overrides={path: 5}`` + 503 → 6 calls (1 + 5)."""
        path = "/api/v1/admin/feature-flags/x"
        c = BaseAPIClient(max_retries=3, retry_overrides={path: 5})
        resp_503 = _make_503_response()
        mock_client = _make_context_mock(resp_503)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff"):
                with pytest.raises(httpx.HTTPStatusError):
                    c.get(path)
        assert _count_calls(mock_client) == 6

    def test_override_0_makes_single_call(self) -> None:
        """``retry_overrides={path: 0}`` + 503 → 1 call (no retry)."""
        path = "/api/v1/admin/audit"
        c = BaseAPIClient(max_retries=3, retry_overrides={path: 0})
        resp_503 = _make_503_response()
        mock_client = _make_context_mock(resp_503)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff") as sleep_mock:
                with pytest.raises(httpx.HTTPStatusError):
                    c.get(path)
        assert _count_calls(mock_client) == 1
        sleep_mock.assert_not_called()

    def test_health_path_200_succeeds(self) -> None:
        """``/health`` + 200 → success без retry."""
        c = BaseAPIClient(max_retries=3)
        resp_200 = _make_200_response({"status": "ok"})
        mock_client = _make_context_mock(resp_200)
        with patch.object(httpx, "Client", return_value=mock_client):
            result = c.get("/health")
        assert result == {"status": "ok"}
        assert _count_calls(mock_client) == 1

    def test_429_rate_limit_respects_path_policy(self) -> None:
        """``/health`` + 429 → 1 call (no retry — path policy wins)."""
        c = BaseAPIClient(max_retries=3)
        resp_429 = MagicMock(spec=httpx.Response)
        resp_429.status_code = 429
        resp_429.headers = {"content-type": "application/json"}
        resp_429.json.return_value = {"error": "rate limited"}
        resp_429.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=resp_429
        )
        mock_client = _make_context_mock(resp_429)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff") as sleep_mock:
                with pytest.raises(httpx.HTTPStatusError):
                    c.get("/health")
        assert _count_calls(mock_client) == 1
        sleep_mock.assert_not_called()

    def test_408_timeout_retries_on_default_path(self) -> None:
        """``/api/v1/x`` + 408 → 4 calls (408 — retryable)."""
        c = BaseAPIClient(max_retries=3)
        resp_408 = MagicMock(spec=httpx.Response)
        resp_408.status_code = 408
        resp_408.headers = {"content-type": "application/json"}
        resp_408.raise_for_status.side_effect = httpx.HTTPStatusError(
            "408", request=MagicMock(), response=resp_408
        )
        mock_client = _make_context_mock(resp_408)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff"):
                with pytest.raises(httpx.HTTPStatusError):
                    c.get("/api/v1/x")
        assert _count_calls(mock_client) == 4

    def test_404_not_retried(self) -> None:
        """``/api/v1/missing`` + 404 → 1 call (404 not retryable)."""
        c = BaseAPIClient(max_retries=3)
        resp_404 = MagicMock(spec=httpx.Response)
        resp_404.status_code = 404
        resp_404.headers = {"content-type": "application/json"}
        resp_404.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=resp_404
        )
        mock_client = _make_context_mock(resp_404)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff") as sleep_mock:
                with pytest.raises(httpx.HTTPStatusError):
                    c.get("/api/v1/missing")
        assert _count_calls(mock_client) == 1
        sleep_mock.assert_not_called()


class TestSubclassOverride:
    """Subclass может override ``_get_max_retries_for_path`` для domain policy."""

    def test_subclass_override_increases_retries(self) -> None:
        class RAGClient(BaseAPIClient):
            """RAG long-running endpoints — больше retries."""

            def _get_max_retries_for_path(self, path: str) -> int:
                if path.startswith("/api/v1/rag/"):
                    return 7
                return super()._get_max_retries_for_path(path)

        c = RAGClient(max_retries=3)
        assert c._get_max_retries_for_path("/api/v1/rag/ingest") == 7
        assert c._get_max_retries_for_path("/api/v1/rag/search") == 7
        # Other paths use default
        assert c._get_max_retries_for_path("/api/v1/admin/x") == 3
        # Health paths still 0
        assert c._get_max_retries_for_path("/health") == 0

    def test_subclass_503_uses_increased_retries(self) -> None:
        class ImportantEndpointClient(BaseAPIClient):
            def _get_max_retries_for_path(self, path: str) -> int:
                if path == "/api/v1/critical":
                    return 5
                return super()._get_max_retries_for_path(path)

        c = ImportantEndpointClient(max_retries=3)
        resp_503 = _make_503_response()
        mock_client = _make_context_mock(resp_503)
        with patch.object(httpx, "Client", return_value=mock_client):
            with patch.object(c, "_sleep_backoff"):
                with pytest.raises(httpx.HTTPStatusError):
                    c.get("/api/v1/critical")
        # 1 initial + 5 retries = 6 calls
        assert _count_calls(mock_client) == 6
