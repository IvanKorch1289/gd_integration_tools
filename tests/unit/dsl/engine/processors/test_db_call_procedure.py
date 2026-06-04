"""Unit-тесты DbCallProcedureProcessor — Wave [wave:s5/k3-w8-db-call-procedure]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.db_call_procedure import DbCallProcedureProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "db_call_procedure_enabled", True)


def test_validates_constructor() -> None:
    with pytest.raises(ValueError, match="profile"):
        DbCallProcedureProcessor(profile="", name="proc")
    with pytest.raises(ValueError, match="name"):
        DbCallProcedureProcessor(profile="prof", name="")
    with pytest.raises(ValueError, match="dialect"):
        DbCallProcedureProcessor(profile="p", name="n", dialect="invalid")


def test_build_call_sql_dialects() -> None:
    proc_pg = DbCallProcedureProcessor(profile="p", name="recalc", dialect="postgres")
    assert proc_pg._build_call_sql({"id": 1}) == "CALL public.recalc(:id)"
    proc_mssql = DbCallProcedureProcessor(
        profile="p", name="recalc", dialect="mssql", schema="dbo"
    )
    assert proc_mssql._build_call_sql({"id": 1}) == "EXEC dbo.recalc :id"
    proc_oracle = DbCallProcedureProcessor(profile="p", name="recalc", dialect="oracle")
    assert proc_oracle._build_call_sql({"id": 1}) == "BEGIN public.recalc(:id); END;"


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "db_call_procedure_enabled", False)
    proc = DbCallProcedureProcessor(profile="p", name="proc")
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("db_call_procedure_status") == "skipped"
