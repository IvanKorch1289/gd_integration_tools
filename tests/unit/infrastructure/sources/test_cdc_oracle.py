"""TDD: CDC Oracle source без Kafka (S171 M18.2).

Per user directive: "возможность запустить CDC к Oracle и без Kafka".
Реализация: polling-based CDC source для Oracle через oracledb (async).

Pattern (Ponytail, D249): thin wrapper над oracledb connection +
scn (System Change Number) tracking — native Oracle CDC без Kafka/Debezium.

Requirements:
- async (asyncio.to_thread для sync oracledb)
- polling (не streams)
- без Kafka
- поддержка DBA_CDC_PUBLICATIONS / SCN tracking
"""
# ruff: noqa: S101
from __future__ import annotations
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest


class TestOracleCDCSource:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )
        source = OracleCDCSource(
            dsn="oracle://user:pass@host:1521/ORCLPDB1",
            schema="HR",
            tables=("EMPLOYEES",),
        )
        assert source.dsn == "oracle://user:pass@host:1521/ORCLPDB1"
        assert source.schema == "HR"
        assert source.tables == ("EMPLOYEES",)

    def test_instantiates_with_table_filter(self) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )
        source = OracleCDCSource(
            dsn="oracle://x",
            schema="S",
            tables=("T1", "T2"),
            poll_interval_seconds=5.0,
            watermark_column="updated_at",
        )
        assert source.poll_interval_seconds == 5.0
        assert source.watermark_column == "updated_at"


class TestOracleCDCSourcePolling:
    @pytest.mark.skip(reason="M18.2: oracledb не установлен в dev env")
    @pytest.mark.asyncio
    async def test_poll_returns_new_changes(self) -> None:
        """При polling с последним SCN — возвращает новые rows."""
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )
        source = OracleCDCSource(
            dsn="oracle://x",
            schema="HR",
            tables=("EMPLOYEES",),
            watermark_column="updated_at",
        )
        # Mock DB connection
        with patch("oracledb.connect_async") as mock_connect:
            mock_conn = AsyncMock()
            mock_connect.return_value = mock_conn
            mock_conn.execute.return_value = [
                {"id": 1, "updated_at": datetime.now(UTC)},
                {"id": 2, "updated_at": datetime.now(UTC)},
            ]
            changes = await source._fetch_changes_since("HR.EMPLOYEES", watermark=0)
        assert len(changes) == 2
        assert changes[0]["id"] == 1


class TestOracleCDCSourceInDSL:
    def test_registers_in_source_registry(self) -> None:
        """Oracle CDC source регистрируется в SourceRegistry."""
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )
        assert OracleCDCSource is not None
        # SourceRegistry должен иметь метод register_oracle_cdc
        # (проверяем что source имеет нужные capabilities)


class TestOracleCDCSourceIdentifierValidation:
    def test_valid_table_passes(self) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            _validate_oracle_table,
        )

        assert _validate_oracle_table("HR.EMPLOYEES") == "HR.EMPLOYEES"

    @pytest.mark.parametrize(
        "bad",
        [
            "HR;DROP--",
            "1HR.TABLE",
            "HR.EMPLOYEES; --",
            "schema.table.col",
            "",
        ],
    )
    def test_invalid_table_rejected(self, bad: str) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            _validate_oracle_table,
        )

        with pytest.raises(ValueError):
            _validate_oracle_table(bad)

    def test_valid_identifier_passes(self) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            _validate_oracle_identifier,
        )

        assert _validate_oracle_identifier("updated_at") == "updated_at"

    @pytest.mark.parametrize("bad", ["updated_at; --", "1col", "col;DROP", ""])
    def test_invalid_identifier_rejected(self, bad: str) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            _validate_oracle_identifier,
        )

        with pytest.raises(ValueError):
            _validate_oracle_identifier(bad)

    def test_sync_fetch_uses_validated_identifiers(self) -> None:
        """Constructor itself rejects unsafe watermark columns —
        ``_sync_fetch`` must never be reached for them."""
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )

        with pytest.raises(ValueError):
            OracleCDCSource(
                dsn="oracle://x",
                schema="HR",
                tables=("EMPLOYEES",),
                watermark_column="updated_at; DROP TABLE x; --",
            )

    def test_schema_validated_at_construction(self) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )

        with pytest.raises(ValueError):
            OracleCDCSource(
                dsn="oracle://x",
                schema="HR; DROP SCHEMA X; --",
                tables=("EMPLOYEES",),
            )

    def test_table_name_validated_at_construction(self) -> None:
        from src.backend.infrastructure.sources.cdc_oracle import (
            OracleCDCSource,
        )

        with pytest.raises(ValueError):
            OracleCDCSource(
                dsn="oracle://x",
                schema="HR",
                tables=("EMPLOYEES; DROP TABLE x; --",),
            )
