"""Tests for S127 W3 — ExternalDBFacade (TD-021).

Covers:
- Facade singleton pattern (get_default / configure)
- query / execute / call_procedure methods (with mocked registry)
- transaction context manager (open/commit/rollback semantics)
- Lazy registry getter (custom DI vs default import)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.db.external_facade import ExternalDBFacade, TransactionContext

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class FakeDatabaseBundle:
    """Mock for ``DatabaseBundle`` exposing ``session`` for query/execute."""

    def __init__(self, session: Any | None = None) -> None:
        self.session = session or MagicMock()
        self._entered = False

    async def __aenter__(self) -> "FakeDatabaseBundle":
        self._entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._entered = False


class FakeRegistry:
    """Mock for ``ExternalDatabaseRegistry`` exposing ``get_bundle``."""

    def __init__(self, bundles: dict[str, Any] | None = None) -> None:
        self._bundles = bundles or {}
        self.get_bundle = MagicMock(side_effect=self._get_bundle)

    def _get_bundle(self, profile: str) -> Any:
        if profile not in self._bundles:
            from src.backend.core.errors import DatabaseError

            raise DatabaseError(message=f"Profile {profile!r} not registered")
        return self._bundles[profile]


class FakeSession:
    """Mock for SQLAlchemy AsyncSession."""

    def __init__(self, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self._rowcount = rowcount
        self.execute = AsyncMock(side_effect=self._execute)
        self.committed = False

    async def _execute(self, stmt: Any, params: dict | None = None) -> Any:
        result = MagicMock()
        if "SELECT" in str(stmt).upper():
            result.mappings.return_value.all.return_value = self._rows
        else:
            result.rowcount = self._rowcount
        return result

    async def commit(self) -> None:
        self.committed = True


# ---------------------------------------------------------------------------
# Singleton + registry tests
# ---------------------------------------------------------------------------


class TestExternalDBFacadeSingleton:
    def setup_method(self) -> None:
        # Reset singleton between tests.
        ExternalDBFacade._instance = None

    def test_get_default_returns_singleton(self) -> None:
        a = ExternalDBFacade.get_default()
        b = ExternalDBFacade.get_default()
        assert a is b

    def test_configure_resets_singleton(self) -> None:
        registry = FakeRegistry()
        a = ExternalDBFacade.configure(lambda: registry)
        b = ExternalDBFacade.get_default()
        assert a is b
        # Custom registry stored.
        assert b._registry_getter is not None


# ---------------------------------------------------------------------------
# query / execute / call_procedure tests
# ---------------------------------------------------------------------------


class TestExternalDBFacadeQueryExecute:
    def setup_method(self) -> None:
        ExternalDBFacade._instance = None

    @pytest.mark.asyncio
    async def test_query_returns_list_of_dicts(self) -> None:
        rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        session = FakeSession(rows=rows)
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        result = await facade.query("pg", "SELECT * FROM users")
        assert result == rows
        registry.get_bundle.assert_called_with("pg")

    @pytest.mark.asyncio
    async def test_query_with_params(self) -> None:
        rows = [{"id": 42, "name": "alice"}]
        session = FakeSession(rows=rows)
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        result = await facade.query(
            "pg", "SELECT * FROM users WHERE id = :id", {"id": 42}
        )
        assert result == rows
        # Verify params passed to session.execute.
        call_args = session.execute.call_args
        assert call_args[0][1] == {"id": 42}

    @pytest.mark.asyncio
    async def test_execute_returns_rowcount(self) -> None:
        session = FakeSession(rowcount=3)
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        n = await facade.execute(
            "pg", "DELETE FROM users WHERE active = :a", {"a": False}
        )
        assert n == 3

    @pytest.mark.asyncio
    async def test_query_unknown_profile_raises(self) -> None:
        registry = FakeRegistry(bundles={})
        facade = ExternalDBFacade.configure(lambda: registry)
        with pytest.raises(Exception, match="not registered"):
            await facade.query("missing", "SELECT 1")

    @pytest.mark.asyncio
    async def test_call_procedure_unsupported_raises(self) -> None:
        bundle = FakeDatabaseBundle(session=FakeSession())
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)
        with pytest.raises(NotImplementedError, match="not supported"):
            await facade.call_procedure("pg", "my_proc", {"p": 1})


# ---------------------------------------------------------------------------
# transaction context manager tests
# ---------------------------------------------------------------------------


class TestExternalDBFacadeTransaction:
    def setup_method(self) -> None:
        ExternalDBFacade._instance = None

    @pytest.mark.asyncio
    async def test_transaction_context_commits_on_success(self) -> None:
        session = FakeSession()
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        async with facade.transaction("pg") as tx:
            await tx.execute("INSERT INTO audit VALUES (1)")

        # session.execute was called (INSERT).
        assert session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_transaction_context_rollback_on_exception(self) -> None:
        session = FakeSession()
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        with pytest.raises(RuntimeError, match="test error"):
            async with facade.transaction("pg") as tx:
                await tx.execute("INSERT INTO audit VALUES (1)")
                raise RuntimeError("test error")

        # Bundle exited (rollback path).
        assert not bundle._entered

    @pytest.mark.asyncio
    async def test_transaction_query_returns_rows(self) -> None:
        rows = [{"id": 1}]
        session = FakeSession(rows=rows)
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        async with facade.transaction("pg") as tx:
            result = await tx.query("SELECT 1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_transaction_query_outside_context_raises(self) -> None:
        session = FakeSession()
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})
        facade = ExternalDBFacade.configure(lambda: registry)

        # Acquire tx without entering.
        async with facade.transaction("pg") as tx:
            # OK while in context
            await tx.query("SELECT 1")

        # Outside context — no tx object; check via direct creation
        tx = TransactionContext(_bundle=bundle)
        # _in_transaction is False initially
        with pytest.raises(RuntimeError, match="not in transaction"):
            await tx.query("SELECT 1")


# ---------------------------------------------------------------------------
# Lazy registry getter tests
# ---------------------------------------------------------------------------


class TestExternalDBFacadeLazyRegistry:
    def setup_method(self) -> None:
        ExternalDBFacade._instance = None

    @pytest.mark.asyncio
    async def test_custom_registry_getter_used(self) -> None:
        """When configured, custom getter is used (DI-friendly)."""
        session = FakeSession(rows=[{"id": 1}])
        bundle = FakeDatabaseBundle(session=session)
        registry = FakeRegistry(bundles={"pg": bundle})

        # Configure with custom getter.
        facade = ExternalDBFacade.configure(lambda: registry)
        result = await facade.query("pg", "SELECT 1")
        assert result == [{"id": 1}]
