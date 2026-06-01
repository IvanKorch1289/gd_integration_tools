"""Unit tests for JdbcQueryProcessor (GAP-INT-1 S35)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.jdbc_query import JdbcQueryProcessor


def _make_exchange(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class TestJdbcQueryProcessorSqlValidation:
    """SQL validation tests — forbid DDL, DROP, GRANT, multi-statement."""

    def test_jdbc_query_validates_sql_rejects_drop(self) -> None:
        """DROP is forbidden."""
        with pytest.raises(ValueError, match="DROP"):
            JdbcQueryProcessor._validate_sql("DROP TABLE users")

    def test_jdbc_query_validates_sql_rejects_alter(self) -> None:
        """ALTER is forbidden."""
        with pytest.raises(ValueError, match="ALTER"):
            JdbcQueryProcessor._validate_sql("ALTER TABLE users ADD COLUMN age INT")

    def test_jdbc_query_validates_sql_rejects_truncate(self) -> None:
        """TRUNCATE is forbidden."""
        with pytest.raises(ValueError, match="TRUNCATE"):
            JdbcQueryProcessor._validate_sql("TRUNCATE TABLE users")

    def test_jdbc_query_validates_sql_rejects_create(self) -> None:
        """CREATE is forbidden."""
        with pytest.raises(ValueError, match="CREATE"):
            JdbcQueryProcessor._validate_sql("CREATE TABLE users (id INT)")

    def test_jdbc_query_validates_sql_rejects_grant(self) -> None:
        """GRANT is forbidden."""
        with pytest.raises(ValueError, match="GRANT"):
            JdbcQueryProcessor._validate_sql("GRANT SELECT ON users TO public")

    def test_jdbc_query_validates_sql_rejects_revoke(self) -> None:
        """REVOKE is forbidden."""
        with pytest.raises(ValueError, match="REVOKE"):
            JdbcQueryProcessor._validate_sql("REVOKE SELECT ON users FROM public")

    def test_jdbc_query_rejects_multi_statement(self) -> None:
        """Semicolon-separated statements are rejected."""
        with pytest.raises(ValueError, match="Multi-statement"):
            JdbcQueryProcessor._validate_sql("SELECT * FROM users; SELECT * FROM orders")

    def test_jdbc_query_accepts_valid_select(self) -> None:
        """Valid SELECT is accepted and doesn't raise."""
        JdbcQueryProcessor._validate_sql("SELECT id, name FROM users WHERE status = :status")

    def test_jdbc_query_accepts_valid_insert(self) -> None:
        """Valid INSERT is accepted (not in forbidden list)."""
        JdbcQueryProcessor._validate_sql("INSERT INTO users (name, email) VALUES (:name, :email)")

    def test_jdbc_query_accepts_select_with_leading_whitespace(self) -> None:
        """SELECT with leading whitespace is accepted."""
        JdbcQueryProcessor._validate_sql("  SELECT * FROM users")


class TestJdbcQueryProcessorConstructor:
    """Constructor argument validation."""

    def test_empty_profile_raises(self) -> None:
        """Empty profile name raises ValueError at construction."""
        with pytest.raises(ValueError, match="profile must be non-empty"):
            JdbcQueryProcessor(sql="SELECT 1", profile="")

    def test_empty_sql_raises(self) -> None:
        """Empty SQL raises ValueError at construction."""
        with pytest.raises(ValueError, match="sql must be non-empty"):
            JdbcQueryProcessor(sql="", profile="test_profile")

    def test_default_params_from_is_body(self) -> None:
        """Default params_from is 'body'."""
        proc = JdbcQueryProcessor(sql="SELECT 1", profile="test_profile")
        assert proc._params_from == "body"

    def test_default_result_property(self) -> None:
        """Default result_property is 'jdbc_result'."""
        proc = JdbcQueryProcessor(sql="SELECT 1", profile="test_profile")
        assert proc._result_property == "jdbc_result"


class TestJdbcQueryProcessorSelectSetsResultProperty:
    """SELECT query places rows list in result_property."""

    @pytest.mark.asyncio
    async def test_jdbc_query_select_sets_result_property(self) -> None:
        """On SELECT, result_property is set to list[dict] of rows."""
        proc = JdbcQueryProcessor(
            sql="SELECT id, name FROM users WHERE id = :id",
            profile="test_profile",
            params_from="body",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"id": 42})

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(_mapping={"id": 42, "name": "Alice"}),
            MagicMock(_mapping={"id": 43, "name": "Bob"}),
        ]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("jdbc_result") == [
            {"id": 42, "name": "Alice"},
            {"id": 43, "name": "Bob"},
        ]
        assert exchange.out_message.body == [
            {"id": 42, "name": "Alice"},
            {"id": 43, "name": "Bob"},
        ]

    @pytest.mark.asyncio
    async def test_jdbc_query_select_empty_result(self) -> None:
        """On SELECT with no rows, result_property is set to empty list."""
        proc = JdbcQueryProcessor(
            sql="SELECT * FROM users WHERE id = :id",
            profile="test_profile",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"id": 999})

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("jdbc_result") == []


class TestJdbcQueryProcessorInsertReturnsAffectedCount:
    """INSERT/UPDATE/DELETE returns affected row count."""

    @pytest.mark.asyncio
    async def test_jdbc_query_insert_returns_affected_count(self) -> None:
        """On INSERT, result_property is set to int (affected row count)."""
        proc = JdbcQueryProcessor(
            sql="INSERT INTO users (name, email) VALUES (:name, :email)",
            profile="test_profile",
            params_from="body",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"name": "Alice", "email": "alice@example.com"})

        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("jdbc_result") == 1
        assert exchange.out_message.body == {"affected_count": 1}

    @pytest.mark.asyncio
    async def test_jdbc_query_update_returns_affected_count(self) -> None:
        """On UPDATE, result_property is set to int (affected row count)."""
        proc = JdbcQueryProcessor(
            sql="UPDATE users SET status = :status WHERE id = :id",
            profile="test_profile",
            params_from="body",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"id": 42, "status": "inactive"})

        mock_result = MagicMock()
        mock_result.rowcount = 3

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("jdbc_result") == 3

    @pytest.mark.asyncio
    async def test_jdbc_query_delete_returns_affected_count(self) -> None:
        """On DELETE, result_property is set to int (affected row count)."""
        proc = JdbcQueryProcessor(
            sql="DELETE FROM users WHERE id = :id",
            profile="test_profile",
            params_from="body",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"id": 42})

        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("jdbc_result") == 1


class TestJdbcQueryProcessorParamsFrom:
    """Parameter collection from various sources."""

    @pytest.mark.asyncio
    async def test_params_from_properties(self) -> None:
        """Parameters can be sourced from exchange.properties."""
        proc = JdbcQueryProcessor(
            sql="SELECT * FROM users WHERE id = :id",
            profile="test_profile",
            params_from="properties",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"name": "Alice"})
        exchange.set_property("id", 42)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [MagicMock(_mapping={"id": 42, "name": "Alice"})]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        # Verify the execute was called with params from properties
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        # call_args is ((text_sql, params_dict), {})
        _, call_kwargs = call_args
        assert call_kwargs.get("id") == 42 or (len(call_args[0]) > 1 and call_args[0][1].get("id") == 42)

    @pytest.mark.asyncio
    async def test_params_from_none(self) -> None:
        """params_from='none' passes empty params."""
        proc = JdbcQueryProcessor(
            sql="SELECT 1",
            profile="test_profile",
            params_from="none",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={"id": 42})

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [MagicMock(_mapping={"?column?": 1})]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_manager = MagicMock()
        mock_session_manager.create_session.return_value = mock_session

        with patch(
            "src.backend.core.di.providers.get_external_session_manager_provider",
            return_value=MagicMock(return_value=mock_session_manager),
        ):
            await proc.process(exchange, MagicMock())

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        assert call_args[1] == {}


class TestJdbcQueryProcessorToSpec:
    """to_spec() round-trip serialization."""

    def test_to_spec_basic(self) -> None:
        """Basic spec with default values."""
        proc = JdbcQueryProcessor(
            sql="SELECT * FROM users",
            profile="test_profile",
        )
        spec = proc.to_spec()
        assert spec == {
            "jdbc_query": {
                "profile": "test_profile",
                "sql": "SELECT * FROM users",
            }
        }

    def test_to_spec_custom_params_from(self) -> None:
        """Non-default params_from appears in spec."""
        proc = JdbcQueryProcessor(
            sql="SELECT * FROM users",
            profile="test_profile",
            params_from="properties",
        )
        spec = proc.to_spec()
        assert spec["jdbc_query"]["params_from"] == "properties"

    def test_to_spec_custom_result_property(self) -> None:
        """Non-default result_property appears in spec."""
        proc = JdbcQueryProcessor(
            sql="SELECT * FROM users",
            profile="test_profile",
            result_property="custom_result",
        )
        spec = proc.to_spec()
        assert spec["jdbc_query"]["result_property"] == "custom_result"


class TestJdbcQueryProcessorErrors:
    """Error handling."""

    @pytest.mark.asyncio
    async def test_invalid_sql_sets_failure(self) -> None:
        """Invalid SQL calls exchange.fail and does not execute query."""
        proc = JdbcQueryProcessor(
            sql="DROP TABLE users",
            profile="test_profile",
            result_property="jdbc_result",
        )

        exchange = _make_exchange(body={})

        await proc.process(exchange, MagicMock())

        assert exchange.status.name == "failed"
        assert "SQL validation failed" in str(exchange.error)
        assert exchange.properties.get("jdbc_result") is None
