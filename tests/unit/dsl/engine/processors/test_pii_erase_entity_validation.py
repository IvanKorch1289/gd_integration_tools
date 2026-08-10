"""Regression tests: ``PiiEraseProcessor._anonymize_db`` now validates
``entity_type`` against the same identifier whitelist as ``db_crud``
before interpolating it into DELETE/UPDATE SQL (S608 mitigation).

The module lives under ``src/backend/dsl/engine/processors/security/``
as a non-package directory (shadowed by ``security.py``), so we load
it explicitly via :mod:`importlib` to avoid namespace collisions.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _load_pii_erase_module() -> Any:
    src = (
        Path(__file__).resolve().parents[5]
        / "src/backend/dsl/engine/processors/security/pii_erase.py"
    )
    module_name = "_gd_pii_erase_under_test"
    spec = importlib.util.spec_from_file_location(module_name, src)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Dataclass machinery needs the module to live in ``sys.modules``
    # so ``cls.__module__`` resolves.
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestEntityTypeValidator:
    def test_valid_entity_type_passes(self) -> None:
        mod = _load_pii_erase_module()
        assert mod._validate_entity_type("user") == "user"
        assert mod._validate_entity_type("user_profile") == "user_profile"
        assert mod._validate_entity_type("_internal") == "_internal"

    @pytest.mark.parametrize(
        "bad",
        [
            "user; DROP TABLE x; --",
            "1user",
            "user-name",
            "user.name",
            "",
            "user DDL",
        ],
    )
    def test_invalid_entity_type_rejected(self, bad: str) -> None:
        mod = _load_pii_erase_module()
        with pytest.raises(ValueError):
            mod._validate_entity_type(bad)


class TestPiiEraseAnonymizeDbValidation:
    @pytest.mark.asyncio
    async def test_invalid_scope_rejected_before_sql(self) -> None:
        """Malformed scope (``entity_type`` fails whitelist) → no SQL
        statement is ever executed; cycle-8/D-AUDIT-804 fail-CLOSED
        propagates ValueError до outer process() (НЕ silent swallow).

        Security-relevant invariant: the dangerous identifier is not
        interpolated into a text() object passed to ``execute()``.
        """
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(
            scope="user; DROP TABLE x; --:1", hard_delete=True
        )

        executed: list[Any] = []

        class _Session:
            async def execute(self, sql_obj: Any, params: Any) -> Any:
                executed.append(sql_obj)
                raise AssertionError("execute() called for unsafe scope")

            async def commit(self) -> None:
                raise AssertionError("commit() called for unsafe scope")

        class _Ctx:
            async def __aenter__(self) -> _Session:
                return _Session()

            async def __aexit__(self, *a: Any) -> bool:
                return False

        fake_mgr = MagicMock()
        fake_mgr.get_session = MagicMock(return_value=_Ctx())
        with patch(
            "src.backend.infrastructure.database.session_manager.main_session_manager",
            fake_mgr,
        ):
            # cycle-8/D-AUDIT-804: fail-CLOSED — ValueError propagate
            # до outer process() (вместо silent return 0).
            with pytest.raises(ValueError, match="invalid entity_type"):
                await proc._anonymize_db("erasure-1")
        assert executed == [], "no SQL must reach execute() for unsafe scope"

    @pytest.mark.asyncio
    async def test_valid_scope_runs_constructed_sql(self) -> None:
        mod = _load_pii_erase_module()
        proc = mod.PiiEraseProcessor(scope="user:42", hard_delete=True)
        seen_sql: list[str] = []

        class _Exec:
            rowcount = 1

        class _Session:
            async def execute(self, sql_obj: Any, params: Any) -> _Exec:
                seen_sql.append(str(sql_obj))
                return _Exec()

            async def commit(self) -> None:
                return None

        class _Ctx:
            async def __aenter__(self) -> _Session:
                return _Session()

            async def __aexit__(self, *a: Any) -> bool:
                return False

        fake_mgr = MagicMock()
        fake_mgr.get_session = MagicMock(return_value=_Ctx())
        with patch(
            "src.backend.infrastructure.database.session_manager.main_session_manager",
            fake_mgr,
        ):
            count = await proc._anonymize_db("erasure-1")
        assert count == 1
        assert seen_sql, "expected at least one SQL statement"
        assert "user_pii" in seen_sql[0]
        assert "entity_id = :entity_id" in seen_sql[0]
