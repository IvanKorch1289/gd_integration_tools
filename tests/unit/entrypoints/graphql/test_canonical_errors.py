"""Tests for ``src.backend.entrypoints.graphql.canonical_errors``.

Sprint 3: GraphQL canonical error formatting with extensions.code,
status_code, category, retryable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from graphql.error import GraphQLError

from src.backend.entrypoints.graphql import canonical_errors as mod
from src.backend.entrypoints.graphql.canonical_errors import (
    ErrorCategory,
    _classify_error,
    _retryable,
    format_graphql_error,
    install_canonical_formatter,
)


class TestErrorCategory:
    """ErrorCategory class — string constants."""

    def test_not_found(self) -> None:
        assert ErrorCategory.NOT_FOUND == "not_found"

    def test_validation(self) -> None:
        assert ErrorCategory.VALIDATION == "validation"

    def test_authentication(self) -> None:
        assert ErrorCategory.AUTHENTICATION == "authentication"

    def test_authorization(self) -> None:
        assert ErrorCategory.AUTHORIZATION == "authorization"

    def test_conflict(self) -> None:
        assert ErrorCategory.CONFLICT == "conflict"

    def test_rate_limit(self) -> None:
        assert ErrorCategory.RATE_LIMIT == "rate_limit"

    def test_internal(self) -> None:
        assert ErrorCategory.INTERNAL == "internal"

    def test_unavailable(self) -> None:
        assert ErrorCategory.UNAVAILABLE == "unavailable"

    def test_all_seven_categories(self) -> None:
        # 7 categories
        attrs = [a for a in dir(ErrorCategory) if not a.startswith("_")]
        assert len(attrs) == 8  # 7 categories + class itself has 0 attrs, only constants

        values = [getattr(ErrorCategory, a) for a in attrs]
        # All values are strings
        assert all(isinstance(v, str) for v in values)


class TestRetryable:
    """_retryable() — transport-level retry semantics."""

    def test_unavailable_retryable(self) -> None:
        assert _retryable(ErrorCategory.UNAVAILABLE) is True

    def test_rate_limit_retryable(self) -> None:
        assert _retryable(ErrorCategory.RATE_LIMIT) is True

    def test_internal_retryable(self) -> None:
        assert _retryable(ErrorCategory.INTERNAL) is True

    def test_not_found_not_retryable(self) -> None:
        assert _retryable(ErrorCategory.NOT_FOUND) is False

    def test_validation_not_retryable(self) -> None:
        assert _retryable(ErrorCategory.VALIDATION) is False

    def test_authentication_not_retryable(self) -> None:
        assert _retryable(ErrorCategory.AUTHENTICATION) is False

    def test_authorization_not_retryable(self) -> None:
        assert _retryable(ErrorCategory.AUTHORIZATION) is False

    def test_conflict_not_retryable(self) -> None:
        assert _retryable(ErrorCategory.CONFLICT) is False


class TestClassifyErrorBaseError:
    """_classify_error() — BaseError mapping."""

    def _make_orig(self, name: str, status: int | None = None) -> Any:
        """Создаёт exception class с заданным именем и опциональным status_code."""

        class _OrigError(Exception):
            pass

        _OrigError.__name__ = name
        if status is not None:
            _OrigError.status_code = status
        return _OrigError("error")

    def test_not_found_error(self) -> None:
        orig = self._make_orig("NotFoundError", 404)
        error = GraphQLError("not found", original_error=orig)
        code, category, status = _classify_error(error)

        assert code == "NOT_FOUND"
        assert category == ErrorCategory.NOT_FOUND
        assert status == 404

    def test_authentication_error(self) -> None:
        orig = self._make_orig("AuthenticationError", 401)
        error = GraphQLError("auth failed", original_error=orig)
        code, category, status = _classify_error(error)

        assert code == "UNAUTHENTICATED"
        assert category == ErrorCategory.AUTHENTICATION
        assert status == 401

    def test_authorization_error(self) -> None:
        orig = self._make_orig("AuthorizationError", 403)
        error = GraphQLError("forbidden", original_error=orig)
        code, category, status = _classify_error(error)

        assert code == "PERMISSION_DENIED"
        assert category == ErrorCategory.AUTHORIZATION
        assert status == 403

    def test_database_error(self) -> None:
        orig = self._make_orig("DatabaseError", 500)
        error = GraphQLError("db error", original_error=orig)
        code, category, status = _classify_error(error)

        assert code == "DATABASE_ERROR"
        assert category == ErrorCategory.INTERNAL
        assert status == 500

    def test_unprocessable_error(self) -> None:
        orig = self._make_orig("UnprocessableError", 422)
        error = GraphQLError("validation", original_error=orig)
        code, category, status = _classify_error(error)

        assert code == "VALIDATION_FAILED"
        assert category == ErrorCategory.VALIDATION
        assert status == 422

    def test_status_code_default_500(self) -> None:
        # Если status_code атрибут отсутствует → дефолт 500
        orig = self._make_orig("NotFoundError", status=None)
        error = GraphQLError("not found", original_error=orig)
        _, _, status = _classify_error(error)
        assert status == 500


class TestClassifyErrorGeneric:
    """_classify_error() — generic GraphQLError без original_error."""

    def test_not_found_in_message(self) -> None:
        error = GraphQLError("Resource not found")
        code, category, status = _classify_error(error)

        assert code == "NOT_FOUND"
        assert category == ErrorCategory.NOT_FOUND
        assert status == 404

    def test_does_not_exist_in_message(self) -> None:
        error = GraphQLError("The user does not exist")
        code, category, status = _classify_error(error)

        assert code == "NOT_FOUND"
        assert status == 404

    def test_unauthorized_in_message(self) -> None:
        error = GraphQLError("User is unauthorized")
        code, category, status = _classify_error(error)

        assert code == "UNAUTHENTICATED"
        assert category == ErrorCategory.AUTHENTICATION
        assert status == 401

    def test_auth_in_message(self) -> None:
        error = GraphQLError("Authentication failed")
        code, category, status = _classify_error(error)

        assert code == "UNAUTHENTICATED"
        assert status == 401

    def test_forbidden_in_message(self) -> None:
        error = GraphQLError("Access is forbidden")
        code, category, status = _classify_error(error)

        assert code == "PERMISSION_DENIED"
        assert category == ErrorCategory.AUTHORIZATION
        assert status == 403

    def test_permission_in_message(self) -> None:
        error = GraphQLError("No permission for this action")
        code, category, status = _classify_error(error)

        assert code == "PERMISSION_DENIED"
        assert status == 403

    def test_validation_in_message(self) -> None:
        error = GraphQLError("Validation failed")
        code, category, status = _classify_error(error)

        assert code == "VALIDATION_FAILED"
        assert category == ErrorCategory.VALIDATION
        assert status == 422

    def test_invalid_in_message(self) -> None:
        error = GraphQLError("Invalid input")
        code, category, status = _classify_error(error)

        assert code == "VALIDATION_FAILED"
        assert status == 422

    def test_unknown_message_internal(self) -> None:
        error = GraphQLError("Something completely unrelated")
        code, category, status = _classify_error(error)

        assert code == "INTERNAL_ERROR"
        assert category == ErrorCategory.INTERNAL
        assert status == 500


class TestClassifyErrorUnknownClass:
    """_classify_error() — unknown subclass of GraphQLError."""

    def test_custom_subclass(self) -> None:
        class _CustomError(GraphQLError):
            pass

        error = _CustomError("custom message")
        # class name != "GraphQLError" → upper case, INTERNAL, 500
        code, category, status = _classify_error(error)

        assert code == "_CUSTOMERROR"  # class name uppercased
        assert category == ErrorCategory.INTERNAL
        assert status == 500


class TestFormatGraphQLError:
    """format_graphql_error() — canonical output schema."""

    def test_returns_dict(self) -> None:
        error = GraphQLError("not found")
        result = format_graphql_error(error)
        assert isinstance(result, dict)

    def test_contains_required_keys(self) -> None:
        error = GraphQLError("not found")
        result = format_graphql_error(error)

        assert "message" in result
        assert "path" in result
        assert "extensions" in result

    def test_extensions_has_required_fields(self) -> None:
        error = GraphQLError("not found")
        result = format_graphql_error(error)
        ext = result["extensions"]

        assert "code" in ext
        assert "status_code" in ext
        assert "category" in ext
        assert "retryable" in ext
        assert "correlation_id" in ext

    def test_message_preserved(self) -> None:
        error = GraphQLError("specific error message")
        result = format_graphql_error(error)
        assert result["message"] == "specific error message"

    def test_path_none_when_no_path(self) -> None:
        error = GraphQLError("no path")
        result = format_graphql_error(error)
        assert result["path"] is None

    def test_correlation_id_none_default(self) -> None:
        error = GraphQLError("test")
        result = format_graphql_error(error)
        # set by middleware — дефолт None
        assert result["extensions"]["correlation_id"] is None


class TestFormatGraphQLErrorWithOriginalError:
    """format_graphql_error() с original_error (BaseError)."""

    def test_not_found_original(self) -> None:
        # Custom class with name "NotFoundError" and to_dict
        class _NotFoundErr(Exception):
            def __init__(self) -> None:
                super().__init__("error")
                self.status_code = 404

            def to_dict(self, include_type: bool = True) -> dict[str, Any]:  # noqa: ARG002
                return {"resource": "user", "id": 42}

        _NotFoundErr.__name__ = "NotFoundError"
        error = GraphQLError("not found", original_error=_NotFoundErr())
        result = format_graphql_error(error)

        assert result["extensions"]["code"] == "NOT_FOUND"
        assert result["extensions"]["status_code"] == 404
        assert result["extensions"]["category"] == ErrorCategory.NOT_FOUND
        # retryable: NOT_FOUND → False
        assert result["extensions"]["retryable"] is False
        # details из to_dict
        assert result["extensions"]["details"] == {"resource": "user", "id": 42}

    def test_to_dict_failure_ignored(self) -> None:
        # Если to_dict бросает — не падаем, details не добавляется
        class _NotFoundErr(Exception):
            def __init__(self) -> None:
                super().__init__("error")
                self.status_code = 404

            def to_dict(self, include_type: bool = True) -> dict[str, Any]:  # noqa: ARG002
                raise RuntimeError("boom")

        _NotFoundErr.__name__ = "NotFoundError"
        error = GraphQLError("not found", original_error=_NotFoundErr())
        # Не должно бросить
        result = format_graphql_error(error)
        # details отсутствует (т.к. to_dict упал)
        assert "details" not in result["extensions"]

    def test_no_to_dict_no_details(self) -> None:
        class _NotFoundErr(Exception):
            def __init__(self) -> None:
                super().__init__("error")
                self.status_code = 404

        _NotFoundErr.__name__ = "NotFoundError"
        error = GraphQLError("not found", original_error=_NotFoundErr())
        result = format_graphql_error(error)
        assert "details" not in result["extensions"]


class TestFormatGraphQLErrorRetryable:
    """format_graphql_error() retryable field."""

    def test_internal_retryable_true(self) -> None:
        class _ServiceErr(Exception):
            def __init__(self) -> None:
                super().__init__("error")
                self.status_code = 503

        _ServiceErr.__name__ = "ServiceError"  # → INTERNAL → retryable
        error = GraphQLError("service down", original_error=_ServiceErr())
        result = format_graphql_error(error)
        assert result["extensions"]["retryable"] is True

    def test_not_found_retryable_false(self) -> None:
        class _NotFoundErr(Exception):
            def __init__(self) -> None:
                super().__init__("error")
                self.status_code = 404

        _NotFoundErr.__name__ = "NotFoundError"
        error = GraphQLError("not found", original_error=_NotFoundErr())
        result = format_graphql_error(error)
        assert result["extensions"]["retryable"] is False


class TestInstallCanonicalFormatter:
    """install_canonical_formatter() — module-level side-effect."""

    def test_callable(self) -> None:
        assert callable(install_canonical_formatter)

    def test_callable_no_exception(self) -> None:
        # Не должно бросить
        install_canonical_formatter()


class TestAllExports:
    """__all__ проверка."""

    def test_exports_three_symbols(self) -> None:
        assert "ErrorCategory" in mod.__all__
        assert "format_graphql_error" in mod.__all__
        assert "install_canonical_formatter" in mod.__all__
        assert len(mod.__all__) == 3


class TestModuleImport:
    """Smoke import."""

    def test_module_imports(self) -> None:
        from src.backend.entrypoints.graphql import canonical_errors as m

        assert m is mod


class TestIntegration:
    """End-to-end: format_graphql_error() с разными error types."""

    @pytest.mark.parametrize(
        "cls_name,expected_code,expected_status",
        [
            ("NotFoundError", "NOT_FOUND", 404),
            ("BadRequestError", "BAD_REQUEST", 500),  # default status_code
            ("AuthenticationError", "UNAUTHENTICATED", 500),
            ("AuthorizationError", "PERMISSION_DENIED", 500),
            ("DatabaseError", "DATABASE_ERROR", 500),
            ("ServiceError", "SERVICE_ERROR", 500),
            ("RoutePermissionDeniedError", "ROUTE_PERMISSION_DENIED", 500),
            ("RouteDisabledError", "ROUTE_DISABLED", 500),
            ("TenantContextRequiredError", "TENANT_REQUIRED", 500),
            ("ProductionWiringError", "WIRING_ERROR", 500),
        ],
    )
    def test_all_known_base_errors(self, cls_name: str, expected_code: str, expected_status: int) -> None:
        # Real class with custom name
        _Cls = type(cls_name, (Exception,), {"status_code": expected_status})
        orig = _Cls("test")

        error = GraphQLError("test", original_error=orig)
        result = format_graphql_error(error)

        assert result["extensions"]["code"] == expected_code
        assert result["extensions"]["status_code"] == expected_status