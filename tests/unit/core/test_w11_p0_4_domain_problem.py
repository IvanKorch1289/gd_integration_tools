"""Focused tests: W11 P0-4 — DomainProblem + transport adapters.

Validation:
1. DomainProblem construction + validation (SCREAMING_SNAKE_CASE code).
2. ProblemCategory enum (8 categories, value == GraphQL canonical_errors values).
3. Transport adapters: to_rfc9457, to_graphql_extensions, to_grpc_status,
   to_soap_fault, to_mcp_error, to_dlq_envelope.
4. Auto-derive status_code from category.
5. is_retryable property (explicit OR category default).
6. Factory methods: from_exception (BaseError + generic), from_base_error.
7. safe_details sanitization (free-form dict).
8. cause field: preserved for in-process debugging, не сериализуется.
9. Backward-compat: existing BaseError imports work без изменений.

ADR-0337: canonical error contract (transport-neutral).
"""

from __future__ import annotations

import pytest
from starlette import status

from src.backend.core.errors import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    BaseError,
    DomainProblem,
    NotFoundError,
    ProblemCategory,
    ProductionWiringError,
    ServiceError,
    TenantContextRequiredError,
    UnprocessableError,
    build_error_envelope,
)


class TestProblemCategory:
    """ProblemCategory enum: 8 canonical categories."""

    def test_eight_categories(self) -> None:
        assert len(ProblemCategory) == 8

    @pytest.mark.parametrize(
        "category,expected_value",
        [
            (ProblemCategory.VALIDATION, "validation"),
            (ProblemCategory.AUTHENTICATION, "authentication"),
            (ProblemCategory.AUTHORIZATION, "authorization"),
            (ProblemCategory.NOT_FOUND, "not_found"),
            (ProblemCategory.CONFLICT, "conflict"),
            (ProblemCategory.RATE_LIMIT, "rate_limit"),
            (ProblemCategory.UNAVAILABLE, "unavailable"),
            (ProblemCategory.INTERNAL, "internal"),
        ],
    )
    def test_category_value(
        self, category: ProblemCategory, expected_value: str
    ) -> None:
        """Значения совпадают с GraphQL canonical_errors.ErrorCategory для compat."""
        assert category.value == expected_value

    def test_inherits_str(self) -> None:
        """ProblemCategory — str-enum (JSON-serializable as string)."""
        assert isinstance(ProblemCategory.NOT_FOUND, str)
        assert ProblemCategory.NOT_FOUND == "not_found"


class TestDomainProblemConstruction:
    """Базовый контракт: construction + validation."""

    def test_minimal_construction(self) -> None:
        """Минимум: code, category, title."""
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X not found"
        )
        assert p.code == "X_NOT_FOUND"
        assert p.category == ProblemCategory.NOT_FOUND
        assert p.title == "X not found"
        # retryable default is None (auto-derive from category)
        assert p.retryable is None
        assert p.safe_details == {}
        assert p.correlation_id == ""
        assert p.cause is None

    def test_status_code_auto_derived(self) -> None:
        """status_code == 0 → автодеривация из category."""
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X not found"
        )
        assert p.status_code == status.HTTP_404_NOT_FOUND

    def test_status_code_explicit_overrides(self) -> None:
        """Explicit status_code перебивает category default."""
        p = DomainProblem(
            code="X_RETRY",
            category=ProblemCategory.NOT_FOUND,
            title="X retry",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        assert p.status_code == 503

    def test_empty_code_raises(self) -> None:
        """Пустой code → ValueError."""
        with pytest.raises(ValueError, match="code обязателен"):
            DomainProblem(code="", category=ProblemCategory.NOT_FOUND, title="X")

    def test_lowercase_code_raises(self) -> None:
        """Non-SCREAMING_SNAKE_CASE code → ValueError."""
        with pytest.raises(ValueError, match="SCREAMING_SNAKE_CASE"):
            DomainProblem(
                code="order_not_found", category=ProblemCategory.NOT_FOUND, title="X"
            )

    def test_code_with_special_chars_raises(self) -> None:
        """Code с special chars → ValueError."""
        with pytest.raises(ValueError, match="SCREAMING_SNAKE_CASE"):
            DomainProblem(
                code="ORDER-NOT-FOUND", category=ProblemCategory.NOT_FOUND, title="X"
            )

    def test_code_with_numbers_ok(self) -> None:
        """Code с цифрами — допустимо (e.g., ``HTTP_404``)."""
        p = DomainProblem(
            code="HTTP_404_TEST", category=ProblemCategory.NOT_FOUND, title="Test"
        )
        assert p.code == "HTTP_404_TEST"

    def test_frozen_instance_immutable(self) -> None:
        """DomainProblem — frozen dataclass, attrs immutable."""
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X"
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            p.code = "OTHER"  # type: ignore[misc]

    def test_safe_details_is_mapping(self) -> None:
        """safe_details принимает произвольный Mapping (dict, MappingProxy, etc.)."""
        details = {"resource_id": "123", "tenant_id": "t1"}
        p = DomainProblem(
            code="X_NOT_FOUND",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            safe_details=details,
        )
        assert p.safe_details == details


class TestIsRetryable:
    """is_retryable property — explicit OR category default."""

    def test_explicit_retryable_true(self) -> None:
        p = DomainProblem(
            code="X", category=ProblemCategory.NOT_FOUND, title="X", retryable=True
        )
        assert p.is_retryable is True

    def test_category_default_retryable(self) -> None:
        """UNAVAILABLE, RATE_LIMIT, INTERNAL → retryable по умолчанию."""
        for cat in (
            ProblemCategory.UNAVAILABLE,
            ProblemCategory.RATE_LIMIT,
            ProblemCategory.INTERNAL,
        ):
            p = DomainProblem(code="X", category=cat, title="X")
            assert p.is_retryable is True, f"{cat} should be retryable"

    def test_category_default_non_retryable(self) -> None:
        """VALIDATION, AUTHENTICATION, AUTHORIZATION, NOT_FOUND, CONFLICT → non-retryable."""
        for cat in (
            ProblemCategory.VALIDATION,
            ProblemCategory.AUTHENTICATION,
            ProblemCategory.AUTHORIZATION,
            ProblemCategory.NOT_FOUND,
            ProblemCategory.CONFLICT,
        ):
            p = DomainProblem(code="X", category=cat, title="X")
            assert p.is_retryable is False, f"{cat} should NOT be retryable"

    def test_explicit_false_overrides_category(self) -> None:
        """Explicit retryable=False перебивает category default."""
        p = DomainProblem(
            code="X",
            category=ProblemCategory.UNAVAILABLE,  # would default retryable=True
            title="X",
            retryable=False,
        )
        assert p.is_retryable is False


class TestToRfc9457:
    """to_rfc9457: Problem Details for HTTP APIs (RFC 9457)."""

    def test_minimal(self) -> None:
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X not found"
        )
        result = p.to_rfc9457()
        assert result["type"] == "https://errors.gd-integration-tools/not_found"
        assert result["title"] == "X not found"
        assert result["status"] == 404
        assert result["code"] == "X_NOT_FOUND"
        assert result["category"] == "not_found"
        assert result["retryable"] is False
        # Optional fields отсутствуют
        assert "instance" not in result
        assert "correlation_id" not in result
        assert "details" not in result

    def test_with_instance(self) -> None:
        p = DomainProblem(code="X", category=ProblemCategory.NOT_FOUND, title="X")
        result = p.to_rfc9457(instance="/orders/123")
        assert result["instance"] == "/orders/123"

    def test_with_correlation_id(self) -> None:
        p = DomainProblem(
            code="X",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            correlation_id="corr-abc",
        )
        result = p.to_rfc9457()
        assert result["correlation_id"] == "corr-abc"

    def test_with_safe_details(self) -> None:
        p = DomainProblem(
            code="X",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            safe_details={"order_id": "123"},
        )
        result = p.to_rfc9457()
        assert result["details"] == {"order_id": "123"}

    def test_cause_not_serialized(self) -> None:
        """cause — для in-process debugging, НЕ сериализуется."""
        p = DomainProblem(
            code="X",
            category=ProblemCategory.INTERNAL,
            title="X",
            cause=ValueError("original"),
        )
        result = p.to_rfc9457()
        assert "cause" not in result


class TestToGraphqlExtensions:
    """to_graphql_extensions: совместимость с existing canonical_errors."""

    def test_minimal_schema(self) -> None:
        """Возвращает dict с required keys для GraphQLError.extensions."""
        p = DomainProblem(
            code="ORDER_NOT_FOUND",
            category=ProblemCategory.NOT_FOUND,
            title="Order not found",
        )
        result = p.to_graphql_extensions()
        assert result["code"] == "ORDER_NOT_FOUND"
        assert result["status_code"] == 404
        assert result["category"] == "not_found"
        assert result["retryable"] is False

    def test_with_correlation_id(self) -> None:
        p = DomainProblem(
            code="X",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            correlation_id="corr-abc",
        )
        assert p.to_graphql_extensions()["correlation_id"] == "corr-abc"

    def test_with_details(self) -> None:
        p = DomainProblem(
            code="X",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            safe_details={"resource": "order"},
        )
        assert p.to_graphql_extensions()["details"] == {"resource": "order"}


class TestToGrpcStatus:
    """to_grpc_status: (StatusCode, message, details-dict)."""

    def test_returns_tuple(self) -> None:
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X"
        )
        result = p.to_grpc_status()
        assert isinstance(result, tuple)
        assert len(result) == 3
        code, message, details = result
        assert isinstance(code, int)
        assert isinstance(message, str)
        assert isinstance(details, dict)

    @pytest.mark.parametrize(
        "category,expected_grpc_code",
        [
            (ProblemCategory.VALIDATION, 3),  # INVALID_ARGUMENT
            (ProblemCategory.AUTHENTICATION, 16),  # UNAUTHENTICATED
            (ProblemCategory.AUTHORIZATION, 7),  # PERMISSION_DENIED
            (ProblemCategory.NOT_FOUND, 5),  # NOT_FOUND
            (ProblemCategory.CONFLICT, 6),  # ALREADY_EXISTS
            (ProblemCategory.RATE_LIMIT, 8),  # RESOURCE_EXHAUSTED
            (ProblemCategory.UNAVAILABLE, 14),  # UNAVAILABLE
            (ProblemCategory.INTERNAL, 13),  # INTERNAL
        ],
    )
    def test_grpc_code_mapping(
        self, category: ProblemCategory, expected_grpc_code: int
    ) -> None:
        p = DomainProblem(code="X", category=category, title="X")
        grpc_code, _, _ = p.to_grpc_status()
        assert grpc_code == expected_grpc_code

    def test_details_dict_shape(self) -> None:
        p = DomainProblem(
            code="X",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            correlation_id="corr-abc",
        )
        _, _, details = p.to_grpc_status()
        assert details["code"] == "X"
        assert details["category"] == "not_found"
        assert details["retryable"] in ("true", "false")
        assert details["correlation_id"] == "corr-abc"


class TestToSoapFault:
    """to_soap_fault: SOAP 1.1 Fault envelope."""

    def test_client_fault_4xx(self) -> None:
        """4xx → soap:Client."""
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X not found"
        )
        result = p.to_soap_fault()
        assert result["faultcode"] == "soap:Client"
        assert result["faultstring"] == "X not found"
        assert result["detail"]["code"] == "X_NOT_FOUND"

    def test_server_fault_5xx(self) -> None:
        """5xx → soap:Server."""
        p = DomainProblem(
            code="X_INTERNAL",
            category=ProblemCategory.INTERNAL,
            title="X internal",
            status_code=500,
        )
        result = p.to_soap_fault()
        assert result["faultcode"] == "soap:Server"

    def test_with_safe_details(self) -> None:
        p = DomainProblem(
            code="X",
            category=ProblemCategory.NOT_FOUND,
            title="X",
            safe_details={"resource_id": "123"},
        )
        result = p.to_soap_fault()
        assert result["detail"]["details"] == {"resource_id": "123"}


class TestToMcpError:
    """to_mcp_error: JSON-RPC 2.0 error envelope (MCP)."""

    def test_basic_shape(self) -> None:
        p = DomainProblem(
            code="X_NOT_FOUND", category=ProblemCategory.NOT_FOUND, title="X not found"
        )
        result = p.to_mcp_error()
        assert "code" in result
        assert "message" in result
        assert "data" in result
        assert isinstance(result["code"], int)
        assert result["message"] == "X not found"

    @pytest.mark.parametrize(
        "category,expected_jsonrpc_code",
        [
            (ProblemCategory.VALIDATION, -32602),
            (ProblemCategory.AUTHENTICATION, -32001),
            (ProblemCategory.AUTHORIZATION, -32003),
            (ProblemCategory.NOT_FOUND, -32004),
            (ProblemCategory.CONFLICT, -32005),
            (ProblemCategory.RATE_LIMIT, -32006),
            (ProblemCategory.UNAVAILABLE, -32007),
            (ProblemCategory.INTERNAL, -32603),
        ],
    )
    def test_jsonrpc_code_mapping(
        self, category: ProblemCategory, expected_jsonrpc_code: int
    ) -> None:
        p = DomainProblem(code="X", category=category, title="X")
        assert p.to_mcp_error()["code"] == expected_jsonrpc_code

    def test_data_includes_domain_metadata(self) -> None:
        p = DomainProblem(
            code="X_NOT_FOUND",
            category=ProblemCategory.NOT_FOUND,
            title="X not found",
            correlation_id="corr-abc",
            safe_details={"resource": "order"},
        )
        data = p.to_mcp_error()["data"]
        assert data["code"] == "X_NOT_FOUND"
        assert data["category"] == "not_found"
        assert data["retryable"] is False
        assert data["correlation_id"] == "corr-abc"
        assert data["details"] == {"resource": "order"}


class TestToDlqEnvelope:
    """to_dlq_envelope: для DLQ topic/stream."""

    def test_full_envelope(self) -> None:
        p = DomainProblem(
            code="ORDER_NOT_FOUND",
            category=ProblemCategory.NOT_FOUND,
            title="Order not found",
            correlation_id="corr-abc",
            safe_details={"order_id": "123"},
        )
        result = p.to_dlq_envelope()
        assert result["code"] == "ORDER_NOT_FOUND"
        assert result["category"] == "not_found"
        assert result["title"] == "Order not found"
        assert result["retryable"] is False
        assert result["status_code"] == 404
        assert result["correlation_id"] == "corr-abc"
        assert result["details"] == {"order_id": "123"}


class TestFromException:
    """from_exception: factory для произвольных исключений."""

    def test_from_not_found_error(self) -> None:
        exc = NotFoundError(message="Order not found")
        p = DomainProblem.from_exception(exc, correlation_id="corr-1")
        assert p.code == "NOT_FOUND"
        assert p.category == ProblemCategory.NOT_FOUND
        assert p.status_code == 404
        assert p.title == "Order not found"
        assert p.correlation_id == "corr-1"
        assert p.cause is exc

    def test_from_authentication_error(self) -> None:
        exc = AuthenticationError(message="Bad token")
        p = DomainProblem.from_exception(exc)
        assert p.code == "UNAUTHENTICATED"
        assert p.category == ProblemCategory.AUTHENTICATION
        assert p.status_code == 401

    def test_from_authorization_error(self) -> None:
        exc = AuthorizationError(message="Forbidden")
        p = DomainProblem.from_exception(exc)
        assert p.code == "PERMISSION_DENIED"
        assert p.category == ProblemCategory.AUTHORIZATION
        assert p.status_code == 403

    def test_from_tenant_context_required_error(self) -> None:
        exc = TenantContextRequiredError(route_id="my_route")
        p = DomainProblem.from_exception(exc)
        assert p.code == "TENANT_REQUIRED"
        assert p.category == ProblemCategory.VALIDATION  # 400 → VALIDATION
        assert p.status_code == 400

    def test_from_production_wiring_error(self) -> None:
        exc = ProductionWiringError(message="missing config", missing=("opa_url",))
        p = DomainProblem.from_exception(exc)
        assert p.code == "WIRING_ERROR"
        assert p.category == ProblemCategory.UNAVAILABLE  # 503 → UNAVAILABLE
        assert p.status_code == 503

    def test_from_unknown_base_error(self) -> None:
        """Unknown BaseError → class-name uppercase без 'Error' suffix."""

        class CustomError(BaseError):
            def __init__(self) -> None:
                super().__init__(message="custom", status_code=418)

        exc = CustomError()
        p = DomainProblem.from_exception(exc)
        assert p.code == "CUSTOM"
        assert p.category == ProblemCategory.INTERNAL  # 418 → INTERNAL

    def test_from_generic_exception(self) -> None:
        """Generic Exception (не BaseError) → INTERNAL_ERROR."""
        exc = ValueError("something went wrong")
        p = DomainProblem.from_exception(exc)
        assert p.code == "INTERNAL_ERROR"
        assert p.category == ProblemCategory.INTERNAL
        assert p.status_code == 500
        assert p.cause is exc

    def test_from_exception_no_correlation(self) -> None:
        """Без correlation_id — пустая строка."""
        exc = NotFoundError(message="x")
        p = DomainProblem.from_exception(exc)
        assert p.correlation_id == ""


class TestFromBaseError:
    """from_base_error: явное преобразование с category override."""

    def test_default_category(self) -> None:
        exc = NotFoundError(message="x")
        p = DomainProblem.from_base_error(exc)
        assert p.category == ProblemCategory.NOT_FOUND

    def test_category_override(self) -> None:
        """Override category — use case: NotFoundError mapped to NOT_FOUND explicitly."""
        exc = NotFoundError(message="x")
        p = DomainProblem.from_base_error(exc, category=ProblemCategory.NOT_FOUND)
        assert p.category == ProblemCategory.NOT_FOUND

    def test_with_correlation(self) -> None:
        exc = BadRequestError(message="x")
        p = DomainProblem.from_base_error(exc, correlation_id="corr-1")
        assert p.correlation_id == "corr-1"

    def test_cause_preserved(self) -> None:
        exc = ServiceError(detail="x")
        p = DomainProblem.from_base_error(exc)
        assert p.cause is exc


class TestBackwardCompat:
    """Проверка что существующие импорты и API не сломаны."""

    def test_existing_imports_work(self) -> None:
        """Все существующие классы доступны из core.errors."""
        from src.backend.core.errors import BaseError, build_error_envelope

        # Sanity — все классы импортируются
        assert BaseError is not None
        assert build_error_envelope is not None

    def test_base_error_to_dict_unchanged(self) -> None:
        """BaseError.to_dict() работает как раньше."""
        exc = NotFoundError(message="x")
        d = exc.to_dict()
        assert d["message"] == "x"
        assert d["status_code"] == 404
        assert d["hasErrors"] is True

    def test_base_error_grpc_status_unchanged(self) -> None:
        """BaseError.grpc_status_code property работает."""
        exc = NotFoundError(message="x")
        assert exc.grpc_status_code == 5  # NOT_FOUND

    def test_build_error_envelope_unchanged(self) -> None:
        """build_error_envelope работает как раньше."""
        env = build_error_envelope(code="X", detail="d")
        assert env["code"] == "X"
        assert env["detail"] == "d"
        assert "error_id" in env
        assert "correlation_id" in env
        assert "request_id" in env


class TestRealWorldScenarios:
    """Интеграционные сценарии: реальные use cases."""

    def test_order_not_found_full_pipeline(self) -> None:
        """Order not found: raise BaseError → DomainProblem → все 6 транспортов."""
        exc = NotFoundError(message="Order not found")
        problem = DomainProblem.from_exception(exc, correlation_id="corr-1")

        # Все транспорты возвращают code=NOT_FOUND, category=NOT_FOUND, status=404
        rfc = problem.to_rfc9457(instance="/orders/123")
        assert rfc["status"] == 404
        assert rfc["code"] == "NOT_FOUND"

        graphql = problem.to_graphql_extensions()
        assert graphql["code"] == "NOT_FOUND"
        assert graphql["status_code"] == 404

        grpc_code, msg, details = problem.to_grpc_status()
        assert grpc_code == 5  # NOT_FOUND
        assert details["code"] == "NOT_FOUND"

        soap = problem.to_soap_fault()
        assert soap["detail"]["code"] == "NOT_FOUND"

        mcp = problem.to_mcp_error()
        assert mcp["code"] == -32004  # NOT_FOUND JSON-RPC code

        dlq = problem.to_dlq_envelope()
        assert dlq["code"] == "NOT_FOUND"

    def test_production_wiring_error_retryable(self) -> None:
        """WIRING_ERROR (503) — retryable=True (transient infrastructure issue)."""
        exc = ProductionWiringError(message="missing")
        problem = DomainProblem.from_exception(exc)
        assert problem.is_retryable is True  # UNAVAILABLE category default
        assert problem.to_grpc_status()[0] == 14  # UNAVAILABLE

    def test_validation_error_not_retryable(self) -> None:
        """VALIDATION_FAILED (422) — НЕ retryable (deterministic)."""
        exc = UnprocessableError(message="x")
        problem = DomainProblem.from_exception(exc)
        assert problem.is_retryable is False
        assert problem.category == ProblemCategory.VALIDATION
