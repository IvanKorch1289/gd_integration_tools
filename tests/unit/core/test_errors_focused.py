"""Focused tests for ``core.errors`` (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/core/errors.py`` с ~60% до ≥90%
путём детального покрытия BaseError + 12 наследников + build_error_envelope.

Контракт API:
- ``BaseError(*_, message='', status_code=500)`` — message + http status.
- ``BaseError.grpc_status_code`` — маппинг HTTP → gRPC.
- ``BaseError.soap_fault_code`` — 'Client' <500, 'Server' >=500.
- ``BaseError.to_dict(*, include_type=False)`` — JSON-сериализация.
- ``build_error_envelope(code, detail, *, scope=None, error_id=None)`` — envelope.
- Специализированные классы: BadRequest/Unprocessable/NotFound/Database/
  ProductionWiring/Authentication/Authorization/Service/RouteDisabled/
  TenantContextRequired/RoutePermissionDenied.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette import status

from src.backend.core.errors import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    BaseError,
    DatabaseError,
    NotFoundError,
    ProductionWiringError,
    RouteDisabledError,
    RoutePermissionDeniedError,
    ServiceError,
    TenantContextRequiredError,
    UnprocessableError,
    build_error_envelope,
)


class TestBuildErrorEnvelope:
    """``build_error_envelope()`` — унифицированный envelope."""

    def test_minimal(self) -> None:
        """Минимальный envelope без scope и error_id."""
        env = build_error_envelope(code="ERR_001", detail="Something failed")
        assert env["code"] == "ERR_001"
        assert env["detail"] == "Something failed"
        # UUID генерируется автоматически.
        assert "error_id" in env
        import uuid as uuid_mod
        # error_id — валидный UUID.
        uuid_mod.UUID(env["error_id"])
        # correlation/request_id — None без scope.
        assert env["correlation_id"] is None
        assert env["request_id"] is None

    def test_explicit_error_id(self) -> None:
        """``error_id`` явно переданный сохраняется."""
        env = build_error_envelope(
            code="ERR_002", detail="msg", error_id="my-error-id-123"
        )
        assert env["error_id"] == "my-error-id-123"

    def test_with_scope_correlation_id(self) -> None:
        """``scope.state.correlation_id`` извлекается."""
        scope = {"state": {"correlation_id": "trace-abc"}}
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["correlation_id"] == "trace-abc"

    def test_with_scope_request_id(self) -> None:
        """``scope.request_id`` извлекается."""
        scope = {"request_id": "req-xyz"}
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["request_id"] == "req-xyz"

    def test_with_full_scope(self) -> None:
        """``scope`` с обоими полями."""
        scope = {
            "state": {"correlation_id": "cid-1"},
            "request_id": "rid-1",
        }
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["correlation_id"] == "cid-1"
        assert env["request_id"] == "rid-1"

    def test_scope_state_non_dict(self) -> None:
        """``scope.state`` non-dict (e.g., object) — безопасно."""
        scope: dict[str, Any] = {"state": MagicMock()}
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["correlation_id"] is None

    def test_scope_correlation_id_non_str(self) -> None:
        """``state.correlation_id`` non-str → None."""
        scope = {"state": {"correlation_id": 123}}  # type: ignore[dict-item]
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["correlation_id"] is None

    def test_scope_request_id_non_str(self) -> None:
        """``scope.request_id`` non-str → None."""
        scope = {"request_id": []}
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["request_id"] is None

    def test_scope_empty_state_dict(self) -> None:
        """``scope.state`` пустой dict."""
        scope = {"state": {}}
        env = build_error_envelope(code="X", detail="y", scope=scope)
        assert env["correlation_id"] is None


class TestBaseError:
    """``BaseError`` — базовый класс."""

    def test_init_default(self) -> None:
        """Default: message='', status_code=500."""
        err = BaseError()
        assert err.message == ""
        assert err.status_code == 500
        assert str(err) == ""

    def test_init_with_message(self) -> None:
        """Message сохраняется."""
        err = BaseError(message="custom error")
        assert err.message == "custom error"

    def test_init_with_status_code(self) -> None:
        """status_code сохраняется."""
        err = BaseError(message="x", status_code=418)
        assert err.status_code == 418

    def test_init_positional_message_absorbed(self) -> None:
        """Positional args (после *_) absorbed; message='' remains."""
        # BaseError.__init__(*_, message='', status_code=500).
        # Positional args after *_ are absorbed (discarded).
        err = BaseError("positional", "another")  # type: ignore[misc]
        assert err.message == ""  # positional absorbed, no message set.

    def test_is_exception(self) -> None:
        """BaseError — подкласс Exception."""
        assert issubclass(BaseError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """BaseError ловится как Exception."""
        with pytest.raises(Exception):
            raise BaseError(message="x")

    def test_grpc_status_code_mapping(self) -> None:
        """``grpc_status_code`` — маппинг HTTP → gRPC."""
        assert BaseError(status_code=400).grpc_status_code == 3
        assert BaseError(status_code=401).grpc_status_code == 16
        assert BaseError(status_code=403).grpc_status_code == 7
        assert BaseError(status_code=404).grpc_status_code == 5
        assert BaseError(status_code=422).grpc_status_code == 3
        assert BaseError(status_code=500).grpc_status_code == 13
        assert BaseError(status_code=503).grpc_status_code == 14

    def test_grpc_status_code_unknown(self) -> None:
        """Неизвестный status → default 13 (INTERNAL)."""
        assert BaseError(status_code=418).grpc_status_code == 13

    def test_soap_fault_code_client(self) -> None:
        """``status_code < 500`` → SOAP 'Client'."""
        assert BaseError(status_code=400).soap_fault_code == "Client"
        assert BaseError(status_code=404).soap_fault_code == "Client"

    def test_soap_fault_code_server(self) -> None:
        """``status_code >= 500`` → SOAP 'Server'."""
        assert BaseError(status_code=500).soap_fault_code == "Server"
        assert BaseError(status_code=503).soap_fault_code == "Server"

    def test_to_dict_default(self) -> None:
        """``to_dict()`` без include_type."""
        err = BaseError(message="x", status_code=400)
        result = err.to_dict()
        assert result["message"] == "x"
        assert result["status_code"] == 400
        assert result["hasErrors"] is True
        assert "error_type" not in result

    def test_to_dict_with_include_type(self) -> None:
        """``to_dict(include_type=True)`` добавляет error_type."""
        err = BadRequestError(message="bad")
        result = err.to_dict(include_type=True)
        assert result["error_type"] == "BadRequestError"


class TestSpecificErrors:
    """Специализированные классы ошибок."""

    def test_bad_request_error(self) -> None:
        """BadRequestError → 400."""
        err = BadRequestError()
        assert err.status_code == 400
        assert err.message == "Bad request"

    def test_bad_request_error_custom_message(self) -> None:
        """BadRequestError(message=...)."""
        err = BadRequestError(message="custom bad")
        assert err.message == "custom bad"
        assert err.status_code == 400

    def test_unprocessable_error(self) -> None:
        """UnprocessableError → 422."""
        err = UnprocessableError()
        assert err.status_code == 422
        assert err.message == "Validation error"

    def test_not_found_error(self) -> None:
        """NotFoundError → 404."""
        err = NotFoundError()
        assert err.status_code == 404
        assert err.message == "Not found"

    def test_database_error(self) -> None:
        """DatabaseError → 500."""
        err = DatabaseError()
        assert err.status_code == 500
        assert err.message == "Database error"

    def test_authentication_error(self) -> None:
        """AuthenticationError → 401."""
        err = AuthenticationError()
        assert err.status_code == 401
        assert err.message == "Authentication error"

    def test_authorization_error(self) -> None:
        """AuthorizationError → 403."""
        err = AuthorizationError()
        assert err.status_code == 403
        assert err.message == "Authorization error"


class TestProductionWiringError:
    """``ProductionWiringError`` — composition root."""

    def test_default(self) -> None:
        """Default — 503 + default message."""
        err = ProductionWiringError()
        assert err.status_code == 503
        assert err.message == "Production wiring is incomplete"
        assert err.missing == ()

    def test_with_missing(self) -> None:
        """``missing=tuple`` → message расширен."""
        err = ProductionWiringError(missing=("opa_url", "casbin_model_path"))
        assert err.missing == ("opa_url", "casbin_model_path")
        assert "opa_url" in err.message
        assert "casbin_model_path" in err.message

    def test_with_empty_missing_tuple(self) -> None:
        """``missing=()`` — default message остаётся."""
        err = ProductionWiringError(missing=())
        assert err.message == "Production wiring is incomplete"


class TestServiceError:
    """``ServiceError`` — внешние сервисы."""

    def test_default(self) -> None:
        """Default — detail='Ошибка обработки запроса'."""
        err = ServiceError()
        assert err.status_code == 500
        assert err.message == "Ошибка обработки запроса"
        assert err.detail == "Ошибка обработки запроса"

    def test_custom_detail(self) -> None:
        """Custom detail."""
        err = ServiceError(detail="Downstream timeout")
        assert err.detail == "Downstream timeout"
        assert err.message == "Downstream timeout"


class TestRouteDisabledError:
    """``RouteDisabledError`` — feature-flag disabled route."""

    def test_with_route_id_and_flag(self) -> None:
        """route_id и feature_flag сохраняются."""
        err = RouteDisabledError(route_id="r-1", feature_flag="beta_routes")
        assert err.route_id == "r-1"
        assert err.feature_flag == "beta_routes"
        assert err.status_code == 503
        assert "r-1" in err.message
        assert "beta_routes" in err.message

    def test_default(self) -> None:
        """Default — пустые route_id/feature_flag."""
        err = RouteDisabledError()
        assert err.route_id == ""
        assert err.feature_flag == ""
        assert err.status_code == 503


class TestTenantContextRequiredError:
    """``TenantContextRequiredError`` — tenant_id отсутствует."""

    def test_with_route_id(self) -> None:
        """route_id сохраняется в message."""
        err = TenantContextRequiredError(route_id="r-1")
        assert err.route_id == "r-1"
        assert err.status_code == 400
        assert "r-1" in err.message
        assert "tenant_aware=True" in err.message

    def test_default(self) -> None:
        """Default — пустой route_id."""
        err = TenantContextRequiredError()
        assert err.route_id == ""
        assert err.status_code == 400


class TestRoutePermissionDeniedError:
    """``RoutePermissionDeniedError`` — requires_permission denied."""

    def test_with_reason(self) -> None:
        """route_id + reason сохраняются."""
        err = RoutePermissionDeniedError(route_id="r-1", reason="missing role admin")
        assert err.route_id == "r-1"
        assert err.reason == "missing role admin"
        assert err.status_code == 403
        assert "r-1" in err.message
        assert "missing role admin" in err.message

    def test_default(self) -> None:
        """Default — пустые route_id и reason."""
        err = RoutePermissionDeniedError()
        assert err.route_id == ""
        assert err.reason == ""
        assert err.status_code == 403


class TestErrorInheritance:
    """Все ошибки наследуют BaseError + Exception."""

    def test_all_inherit_base_error(self) -> None:
        """Все специализированные классы — подклассы BaseError."""
        classes = [
            BadRequestError,
            UnprocessableError,
            NotFoundError,
            DatabaseError,
            ProductionWiringError,
            AuthenticationError,
            AuthorizationError,
            ServiceError,
            RouteDisabledError,
            TenantContextRequiredError,
            RoutePermissionDeniedError,
        ]
        for cls in classes:
            assert issubclass(cls, BaseError), f"{cls.__name__} should inherit BaseError"

    def test_all_inherit_exception(self) -> None:
        """Все специализированные классы — подклассы Exception."""
        classes = [
            BadRequestError,
            UnprocessableError,
            NotFoundError,
            DatabaseError,
            ProductionWiringError,
            AuthenticationError,
            AuthorizationError,
            ServiceError,
            RouteDisabledError,
            TenantContextRequiredError,
            RoutePermissionDeniedError,
        ]
        for cls in classes:
            assert issubclass(cls, Exception), f"{cls.__name__} should inherit Exception"


class TestModuleExports:
    """``__all__`` экспортирует 13 symbols."""

    def test_all_count(self) -> None:
        """13 symbols в ``__all__``."""
        from src.backend.core import errors

        assert len(errors.__all__) == 13

    def test_all_callable_or_classes(self) -> None:
        """Все exports — классы или функции."""
        from src.backend.core import errors

        for name in errors.__all__:
            obj = getattr(errors, name)
            assert isinstance(obj, type) or callable(obj)
