"""Tests for core/enums/external_db.py (S97 — coverage push).

Покрывает: StrEnum, Pydantic BaseModel валидаторы, Enum whitelist,
property methods (qualified_name, is_read_operation).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_object_type_choices() -> None:
    """ExternalDBObjectTypeChoices: view, function, procedure, query."""
    from src.backend.core.enums.external_db import ExternalDBObjectTypeChoices

    assert ExternalDBObjectTypeChoices.view.value == "view"
    assert ExternalDBObjectTypeChoices.function.value == "function"
    assert ExternalDBObjectTypeChoices.procedure.value == "procedure"
    assert ExternalDBObjectTypeChoices.query.value == "query"
    assert len(ExternalDBObjectTypeChoices) == 4


def test_parameter_mode_choices() -> None:
    """ExternalDBParameterModeChoices: named, positional."""
    from src.backend.core.enums.external_db import ExternalDBParameterModeChoices

    assert ExternalDBParameterModeChoices.named.value == "named"
    assert ExternalDBParameterModeChoices.positional.value == "positional"
    assert len(ExternalDBParameterModeChoices) == 2


def test_parameter_meta_minimal() -> None:
    """ExternalDBParameterMeta: минимальный кейс (только body_field)."""
    from src.backend.core.enums.external_db import ExternalDBParameterMeta

    p = ExternalDBParameterMeta(body_field="x")
    assert p.body_field == "x"
    assert p.db_name is None  # default
    assert p.bind_name is None
    assert p.required is True  # default
    assert p.default is None
    assert p.exclude_if_none is False  # default


def test_parameter_meta_full() -> None:
    """ExternalDBParameterMeta: все поля заданы."""
    from src.backend.core.enums.external_db import ExternalDBParameterMeta

    p = ExternalDBParameterMeta(
        body_field="user_id",
        db_name="p_user_id",
        bind_name="user_id",
        required=False,
        default=42,
        exclude_if_none=True,
    )
    assert p.body_field == "user_id"
    assert p.db_name == "p_user_id"
    assert p.bind_name == "user_id"
    assert p.required is False
    assert p.default == 42
    assert p.exclude_if_none is True


def test_parameter_meta_empty_body_field_rejected() -> None:
    """body_field='' → ValidationError (min_length=1)."""
    from src.backend.core.enums.external_db import ExternalDBParameterMeta

    with pytest.raises(ValidationError):
        ExternalDBParameterMeta(body_field="")


def test_object_meta_minimal_view() -> None:
    """ExternalDBObjectMeta: minimal view (только required fields)."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    m = ExternalDBObjectMeta(
        profile_name="p1",
        object_name="V_TEST",
        object_type=ExternalDBObjectTypeChoices.view,
    )
    assert m.profile_name == "p1"
    assert m.object_name == "V_TEST"
    assert m.object_type == ExternalDBObjectTypeChoices.view
    assert m.schema_ is None  # alias 'schema'
    assert m.request_schema is None
    assert m.response_schema is None
    assert m.oracle_package is None
    assert m.sql_text is None
    assert m.cache_enabled is False
    assert m.returns_rows is False
    assert m.parameters == []


def test_object_meta_query_requires_sql_text() -> None:
    """object_type=query требует sql_text."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    with pytest.raises(ValidationError, match="sql_text"):
        ExternalDBObjectMeta(
            profile_name="p1",
            object_name="q",
            object_type=ExternalDBObjectTypeChoices.query,
        )


def test_object_meta_sql_text_only_for_query() -> None:
    """sql_text допустим только для object_type=query."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    with pytest.raises(ValidationError, match="sql_text"):
        ExternalDBObjectMeta(
            profile_name="p1",
            object_name="v",
            object_type=ExternalDBObjectTypeChoices.view,
            sql_text="SELECT 1",
        )


def test_object_meta_view_cannot_have_parameters() -> None:
    """view не должен иметь parameters."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBParameterMeta,
        ExternalDBObjectTypeChoices,
    )

    with pytest.raises(ValidationError, match="parameters"):
        ExternalDBObjectMeta(
            profile_name="p1",
            object_name="v",
            object_type=ExternalDBObjectTypeChoices.view,
            parameters=[ExternalDBParameterMeta(body_field="x")],
        )


def test_object_meta_function_requires_parameters() -> None:
    """function/procedure требует parameters."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    with pytest.raises(ValidationError, match="parameters"):
        ExternalDBObjectMeta(
            profile_name="p1",
            object_name="f",
            object_type=ExternalDBObjectTypeChoices.function,
        )


def test_object_meta_procedure_no_cache() -> None:
    """procedure не может иметь cache_enabled=True."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    with pytest.raises(ValidationError, match="cache"):
        ExternalDBObjectMeta(
            profile_name="p1",
            object_name="p",
            object_type=ExternalDBObjectTypeChoices.procedure,
            cache_enabled=True,
        )


def test_object_meta_procedure_no_returns_rows() -> None:
    """procedure не может иметь returns_rows=True."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    with pytest.raises(ValidationError, match="returns_rows"):
        ExternalDBObjectMeta(
            profile_name="p1",
            object_name="p",
            object_type=ExternalDBObjectTypeChoices.procedure,
            returns_rows=True,
        )


def test_object_meta_qualified_name_no_schema_no_package() -> None:
    """qualified_name без schema и package → просто object_name."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    m = ExternalDBObjectMeta(
        profile_name="p1",
        object_name="my_view",
        object_type=ExternalDBObjectTypeChoices.view,
    )
    assert m.qualified_name == "my_view"


def test_object_meta_qualified_name_with_schema() -> None:
    """qualified_name с schema → schema.object_name."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBObjectTypeChoices,
    )

    m = ExternalDBObjectMeta(
        profile_name="p1",
        schema="REPORTING",
        object_name="V_EMP",
        object_type=ExternalDBObjectTypeChoices.view,
    )
    assert m.qualified_name == "REPORTING.V_EMP"


def test_object_meta_qualified_name_with_package() -> None:
    """qualified_name с package → schema.package.object_name."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBParameterMeta,
        ExternalDBObjectTypeChoices,
    )

    m = ExternalDBObjectMeta(
        profile_name="p1",
        schema="REPORTING",
        oracle_package="PKG_EMP",
        object_name="REFRESH",
        object_type=ExternalDBObjectTypeChoices.procedure,
        parameters=[ExternalDBParameterMeta(body_field="x")],
    )
    assert m.qualified_name == "REPORTING.PKG_EMP.REFRESH"


def test_object_meta_is_read_operation() -> None:
    """is_read_operation True для view/function/query, False для procedure."""
    from src.backend.core.enums.external_db import (
        ExternalDBObjectMeta,
        ExternalDBParameterMeta,
        ExternalDBObjectTypeChoices,
    )

    view = ExternalDBObjectMeta(
        profile_name="p1", object_name="v", object_type=ExternalDBObjectTypeChoices.view
    )
    assert view.is_read_operation is True

    fn = ExternalDBObjectMeta(
        profile_name="p1",
        object_name="f",
        object_type=ExternalDBObjectTypeChoices.function,
        parameters=[ExternalDBParameterMeta(body_field="x")],
    )
    assert fn.is_read_operation is True

    proc = ExternalDBObjectMeta(
        profile_name="p1",
        object_name="p",
        object_type=ExternalDBObjectTypeChoices.procedure,
        parameters=[ExternalDBParameterMeta(body_field="x")],
    )
    assert proc.is_read_operation is False


def test_object_choices_whitelist() -> None:
    """ExternalDBObjectChoices: whitelist содержит 4 объекта (демо)."""
    from src.backend.core.enums.external_db import ExternalDBObjectChoices

    assert ExternalDBObjectChoices.ORACLE_EMPLOYEES_VIEW.value.object_name == "V_EMPLOYEES"
    assert (
        ExternalDBObjectChoices.ORACLE_REFRESH_EMPLOYEE_CACHE.value.oracle_package
        == "PKG_EMPLOYEES"
    )
    assert (
        ExternalDBObjectChoices.PG_ANALYTICS_REPORT_FUNCTION.value.object_name
        == "get_sales_report"
    )
    assert ExternalDBObjectChoices.PG_DAILY_REPORT_QUERY.value.sql_text is not None


def test_module_dunder_all() -> None:
    """__all__ содержит все 5 экспортов."""
    import src.backend.core.enums.external_db as mod

    assert mod.__all__ == (
        "ExternalDBObjectChoices",
        "ExternalDBObjectMeta",
        "ExternalDBObjectTypeChoices",
        "ExternalDBParameterMeta",
        "ExternalDBParameterModeChoices",
    )
