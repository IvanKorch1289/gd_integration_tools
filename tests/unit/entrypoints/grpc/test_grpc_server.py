"""Unit tests for grpc_server module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.errors import BaseError
from src.backend.entrypoints.grpc.grpc_server import (
    AuthInterceptor,
    BaseGRPCServicer,
    InvokerGRPCServicer,
    OrderGRPCServicer,
    _load_tls_credentials,
    _safe_error,
)


class TestSafeError:
    """Tests for _safe_error."""

    def test_base_error_returns_message(self) -> None:
        exc = BaseError(message="domain error")
        assert _safe_error(exc, "cid") == "domain error"

    def test_generic_error_masks(self) -> None:
        exc = RuntimeError("secret")
        assert _safe_error(exc, "abc123") == "Internal server error; ref=abc123"


class TestBaseGRPCServicer:
    """Tests for BaseGRPCServicer."""

    @pytest.fixture
    def servicer(self) -> BaseGRPCServicer:
        return BaseGRPCServicer()

    def test_serialize_none(self, servicer: BaseGRPCServicer) -> None:
        assert servicer._serialize(None) == "{}"

    def test_serialize_dict(self, servicer: BaseGRPCServicer) -> None:
        assert servicer._serialize({"a": 1}) == '{"a":1}'

    def test_serialize_pydantic(self, servicer: BaseGRPCServicer) -> None:
        class FakeModel:
            def model_dump(self, mode: str = "json") -> dict:
                return {"x": "y"}

        assert servicer._serialize(FakeModel()) == '{"x":"y"}'

    def test_serialize_primitive(self, servicer: BaseGRPCServicer) -> None:
        assert servicer._serialize(42) == "42"

    @pytest.mark.asyncio
    async def test_dispatch_with_correlation(self, servicer: BaseGRPCServicer) -> None:
        with patch(
            "src.backend.entrypoints.grpc.grpc_server.dispatch_action",
            AsyncMock(return_value={"ok": True}),
        ) as mock_dispatch:
            with patch(
                "src.backend.entrypoints.grpc.grpc_server.set_correlation_context",
                MagicMock(),
            ) as mock_set:
                result = await servicer._dispatch("test.action", {}, correlation_id="cid")
        assert result == {"ok": True}
        mock_set.assert_called_once_with(correlation_id="cid")
        mock_dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_extracts_from_context(self, servicer: BaseGRPCServicer) -> None:
        fake_context = MagicMock()
        with patch(
            "src.backend.entrypoints.grpc.grpc_server.extract_correlation_id_from_grpc_context",
            return_value="extracted-cid",
        ):
            with patch(
                "src.backend.entrypoints.grpc.grpc_server.dispatch_action",
                AsyncMock(return_value={}),
            ):
                with patch(
                    "src.backend.entrypoints.grpc.grpc_server.set_correlation_context",
                    MagicMock(),
                ) as mock_set:
                    await servicer._dispatch("a", context=fake_context)
        mock_set.assert_called_once_with(correlation_id="extracted-cid")


class TestOrderGRPCServicer:
    """Tests for OrderGRPCServicer."""

    @pytest.fixture
    def servicer(self) -> OrderGRPCServicer:
        return OrderGRPCServicer()

    @pytest.mark.asyncio
    async def test_create_order_success(self, servicer: OrderGRPCServicer) -> None:
        request = MagicMock()
        request.order_id = 1
        with patch.object(servicer, "_dispatch", AsyncMock(return_value={
            "instance": {"id": 1, "object_uuid": "uuid"},
            "response": {"status_code": 200},
        })):
            result = await servicer.CreateOrder(request, None)
        assert result.order_id == 1
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_create_order_error(self, servicer: OrderGRPCServicer) -> None:
        request = MagicMock()
        request.order_id = 1
        with patch.object(servicer, "_dispatch", AsyncMock(return_value=None)):
            result = await servicer.CreateOrder(request, None)
        assert "Не удалось" in result.error

    @pytest.mark.asyncio
    async def test_delete_order_success(self, servicer: OrderGRPCServicer) -> None:
        request = MagicMock()
        request.order_id = 1
        with patch.object(servicer, "_dispatch", AsyncMock(return_value=None)):
            result = await servicer.DeleteOrder(request, None)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_delete_order_exception(self, servicer: OrderGRPCServicer) -> None:
        request = MagicMock()
        request.order_id = 1
        with patch.object(servicer, "_dispatch", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await servicer.DeleteOrder(request, None)
        assert result.success is False
        assert "Internal server error" in result.error


class TestInvokerGRPCServicer:
    """Tests for InvokerGRPCServicer."""

    @pytest.fixture
    def servicer(self) -> InvokerGRPCServicer:
        return InvokerGRPCServicer()

    @pytest.mark.asyncio
    async def test_invalid_payload_json(self, servicer: InvokerGRPCServicer) -> None:
        request = MagicMock()
        request.payload_json = "not-json"
        request.metadata_json = ""
        request.mode = ""
        request.invocation_id = "id1"
        result = await servicer.Invoke(request, None)
        assert result.status == "error"
        assert "Invalid payload_json" in result.error

    @pytest.mark.asyncio
    async def test_invalid_mode(self, servicer: InvokerGRPCServicer) -> None:
        request = MagicMock()
        request.payload_json = '{}'
        request.metadata_json = ""
        request.mode = "bad_mode"
        request.invocation_id = "id1"
        result = await servicer.Invoke(request, None)
        assert result.status == "error"
        assert "Unknown mode" in result.error

    @pytest.mark.asyncio
    async def test_invoke_success(self, servicer: InvokerGRPCServicer) -> None:
        from src.backend.core.interfaces.invoker import InvocationMode, InvocationStatus

        request = MagicMock()
        request.payload_json = '{"x":1}'
        request.metadata_json = ""
        request.mode = InvocationMode.SYNC.value
        request.invocation_id = "id1"
        request.action = "test"
        request.reply_channel = ""

        fake_response = MagicMock()
        fake_response.invocation_id = "id1"
        fake_response.status = InvocationStatus.OK
        fake_response.mode = InvocationMode.SYNC
        fake_response.result = {"ok": True}
        fake_response.error = None

        with patch(
            "src.backend.entrypoints.grpc.grpc_server.get_invoker",
            return_value=AsyncMock(invoke=AsyncMock(return_value=fake_response)),
        ):
            result = await servicer.Invoke(request, None)
        assert result.status == InvocationStatus.OK.value


class TestLoadTlsCredentials:
    """Tests for _load_tls_credentials."""

    def test_returns_none_when_disabled(self) -> None:
        with patch(
            "src.backend.entrypoints.grpc.grpc_server.settings",
            MagicMock(grpc=MagicMock(tls_enabled=False)),
        ):
            assert _load_tls_credentials() is None

    def test_raises_when_files_missing(self) -> None:
        with patch(
            "src.backend.entrypoints.grpc.grpc_server.settings",
            MagicMock(
                grpc=MagicMock(
                    tls_enabled=True,
                    server_cert_path="/fake/cert.pem",
                    server_key_path="/fake/key.pem",
                )
            ),
        ):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(RuntimeError, match="TLS"):
                    _load_tls_credentials()


class TestAuthInterceptor:
    """Tests for AuthInterceptor."""

    @pytest.mark.asyncio
    async def test_valid_key(self) -> None:
        interceptor = AuthInterceptor(expected_key="secret")
        continuation = AsyncMock(return_value="handler")
        details = MagicMock()
        details.invocation_metadata = (("x-api-key", "secret"),)
        details.method = "/test"
        result = await interceptor.intercept_service(continuation, details)
        assert result == "handler"
        continuation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_key_aborts(self) -> None:
        interceptor = AuthInterceptor(expected_key="secret")
        continuation = AsyncMock()
        details = MagicMock()
        details.invocation_metadata = (("x-api-key", "wrong"),)
        details.method = "/test"
        result = await interceptor.intercept_service(continuation, details)
        assert callable(result)
        # abort function
        fake_context = AsyncMock()
        with pytest.raises(Exception):
            await result(None, fake_context)
