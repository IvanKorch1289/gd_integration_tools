# ruff: noqa: S101
"""Unit-тесты для ``src.backend.dsl.engine.versioning``.

Покрывает PipelineVersionManager, PipelineSnapshot, get_pipeline_version_manager.
Мокают SQLAlchemy-сессии и DslSnapshot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.versioning import (
    PipelineSnapshot,
    PipelineVersionManager,
    get_pipeline_version_manager,
)


class _FakePipeline:
    """Минимальный pipeline-stand-in."""

    def __init__(self, route_id: str = "r1") -> None:
        self.route_id = route_id
        self.feature_flag = "flag_a"
        self.source = "src"
        self.description = "desc"
        self.processors = []


def _make_fake_processor(name: str, cls_name: str = "FakeProc") -> Any:
    cls = type(cls_name, (), {"name": ""})
    proc = object.__new__(cls)
    proc.name = name  # type: ignore[attr-defined]
    return proc


def _make_snapshot_row(
    *,
    route_id: str = "r1",
    version: int = 1,
    spec: dict[str, Any] | None = None,
    feature_flag: str | None = None,
    source: str | None = None,
    description: str | None = None,
    api_version: str = "v2",
    created_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.route_id = route_id
    row.version = version
    row.spec = spec or {}
    row.feature_flag = feature_flag
    row.source = source
    row.description = description
    row.api_version = api_version
    row.created_at = created_at or datetime.utcnow()
    return row


class TestPipelineSnapshot:
    """Dataclass PipelineSnapshot."""

    def test_to_dict(self) -> None:
        snap = PipelineSnapshot(
            route_id="r1",
            version=3,
            processors=[{"type": "T", "name": "n"}],
            feature_flag="f",
            source="s",
            description="d",
            created_at=123.0,
            api_version="v2",
        )
        d = snap.to_dict()
        assert d["route_id"] == "r1"
        assert d["version"] == 3
        assert d["processors"] == [{"type": "T", "name": "n"}]
        assert d["api_version"] == "v2"


class TestSerializePipeline:
    """Сериализация processor chain."""

    def test_empty_processors(self) -> None:
        mgr = PipelineVersionManager()
        pipeline = _FakePipeline()
        assert mgr._serialize_pipeline(pipeline) == []

    def test_with_processors(self) -> None:
        mgr = PipelineVersionManager()
        pipeline = _FakePipeline()
        pipeline.processors = [
            _make_fake_processor("p1", "ProcA"),
            _make_fake_processor("p2", "ProcB"),
        ]
        assert mgr._serialize_pipeline(pipeline) == [
            {"type": "ProcA", "name": "p1"},
            {"type": "ProcB", "name": "p2"},
        ]


@pytest.mark.asyncio
class TestNextVersion:
    """``_next_version`` — возвращает max+1 или 1."""

    async def test_no_existing_versions_returns_1(self) -> None:
        mgr = PipelineVersionManager()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch(
            "src.backend.dsl.engine.versioning.main_session_manager"
        ) as mock_mgr:
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )
            assert await mgr._next_version("r1") == 1

    async def test_existing_version_returns_incremented(self) -> None:
        mgr = PipelineVersionManager()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 7
        mock_session.execute.return_value = mock_result

        with patch(
            "src.backend.dsl.engine.versioning.main_session_manager"
        ) as mock_mgr:
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )
            assert await mgr._next_version("r1") == 8


@pytest.mark.asyncio
class TestSnapshot:
    """``snapshot`` — создаёт PipelineSnapshot и пишет в БД."""

    async def test_snapshot_creates_version_1(self) -> None:
        mgr = PipelineVersionManager()
        pipeline = _FakePipeline()
        pipeline.processors = [_make_fake_processor("p1")]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with (
            patch("src.backend.dsl.engine.versioning.main_session_manager") as mock_mgr,
            patch("src.backend.dsl.versioning.CURRENT_VERSION", "v2"),
        ):
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )
            mock_mgr.transaction = MagicMock()
            mock_mgr.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
            mock_mgr.transaction.return_value.__aexit__ = AsyncMock(return_value=False)

            snap = await mgr.snapshot(pipeline)

        assert snap.route_id == "r1"
        assert snap.version == 1
        assert snap.processors == [{"type": "FakeProc", "name": "p1"}]
        assert snap.api_version == "v2"
        # session.add должен быть вызван с экземпляром DslSnapshot
        assert mock_session.add.call_count == 1
        added = mock_session.add.call_args[0][0]
        assert added.route_id == "r1"
        assert added.version == 1

    async def test_snapshot_logs_warning_on_db_error(self) -> None:
        mgr = PipelineVersionManager()
        pipeline = _FakePipeline()

        with (
            patch.object(mgr, "_next_version", return_value=1),
            patch("src.backend.dsl.engine.versioning.main_session_manager") as mock_mgr,
            patch("src.backend.dsl.versioning.CURRENT_VERSION", "v2"),
            patch("src.backend.dsl.engine.versioning.logger") as mock_logger,
        ):
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("db down")
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )
            mock_mgr.transaction = MagicMock()
            mock_mgr.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
            mock_mgr.transaction.return_value.__aexit__ = AsyncMock(return_value=False)

            snap = await mgr.snapshot(pipeline)
            assert snap.version == 1
            mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
class TestGetHistory:
    """``get_history`` — возвращает список версий."""

    async def test_history_returns_rows(self) -> None:
        mgr = PipelineVersionManager()
        row = _make_snapshot_row(
            route_id="r1",
            version=2,
            spec={"processors": [{"type": "T", "name": "n"}]},
            feature_flag="f",
        )
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        mock_session.execute.return_value = mock_result

        with patch(
            "src.backend.dsl.engine.versioning.main_session_manager"
        ) as mock_mgr:
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            history = await mgr.get_history("r1")

        assert len(history) == 1
        assert history[0]["version"] == 2
        assert history[0]["processors"] == [{"type": "T", "name": "n"}]

    async def test_history_returns_empty_on_error(self) -> None:
        mgr = PipelineVersionManager()
        with (
            patch("src.backend.dsl.engine.versioning.main_session_manager") as mock_mgr,
            patch("src.backend.dsl.engine.versioning.logger") as mock_logger,
        ):
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("fail")
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            history = await mgr.get_history("r1")
            assert history == []
            mock_logger.error.assert_called_once()


@pytest.mark.asyncio
class TestCompare:
    """``compare`` — diff двух версий."""

    async def test_versions_not_found(self) -> None:
        mgr = PipelineVersionManager()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        with patch(
            "src.backend.dsl.engine.versioning.main_session_manager"
        ) as mock_mgr:
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            result = await mgr.compare("r1", 1, 2)
            assert result == {"error": "Version not found"}

    async def test_compare_same_processors(self) -> None:
        mgr = PipelineVersionManager()
        row1 = _make_snapshot_row(
            version=1,
            spec={"processors": [{"name": "p1", "type": "A"}]},
            api_version="v2",
        )
        row2 = _make_snapshot_row(
            version=2,
            spec={"processors": [{"name": "p1", "type": "A"}]},
            api_version="v2",
        )
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row1, row2]
        mock_session.execute.return_value = mock_result

        with (
            patch("src.backend.dsl.engine.versioning.main_session_manager") as mock_mgr,
            patch("src.backend.dsl.versioning.CURRENT_VERSION", "v2"),
        ):
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            result = await mgr.compare("r1", 1, 2)

        assert result["added_processors"] == []
        assert result["removed_processors"] == []
        assert result["changed_processors"] == []
        assert result["feature_flag_changed"] is False

    async def test_compare_added_removed_changed(self) -> None:
        mgr = PipelineVersionManager()
        row1 = _make_snapshot_row(
            version=1,
            spec={
                "processors": [{"name": "p1", "type": "A"}, {"name": "p2", "type": "B"}]
            },
            api_version="v2",
            feature_flag="f1",
        )
        row2 = _make_snapshot_row(
            version=2,
            spec={
                "processors": [{"name": "p2", "type": "C"}, {"name": "p3", "type": "D"}]
            },
            api_version="v2",
            feature_flag="f2",
        )
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row1, row2]
        mock_session.execute.return_value = mock_result

        with (
            patch("src.backend.dsl.engine.versioning.main_session_manager") as mock_mgr,
            patch("src.backend.dsl.versioning.CURRENT_VERSION", "v2"),
        ):
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            result = await mgr.compare("r1", 1, 2)

        assert result["added_processors"] == ["p3"]
        assert result["removed_processors"] == ["p1"]
        assert result["changed_processors"] == ["p2"]
        assert result["feature_flag_changed"] is True

    async def test_compare_with_migration(self) -> None:
        mgr = PipelineVersionManager()
        row1 = _make_snapshot_row(version=1, spec={"processors": []}, api_version="v1")
        row2 = _make_snapshot_row(version=2, spec={"processors": []}, api_version="v2")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row1, row2]
        mock_session.execute.return_value = mock_result

        def fake_migrate(
            spec: dict[str, Any], *, target_version: str
        ) -> dict[str, Any]:
            spec["apiVersion"] = target_version
            return spec

        with (
            patch("src.backend.dsl.engine.versioning.main_session_manager") as mock_mgr,
            patch("src.backend.dsl.versioning.CURRENT_VERSION", "v2"),
            patch(
                "src.backend.dsl.versioning.apply_migrations", side_effect=fake_migrate
            ) as mock_migrate,
        ):
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            await mgr.compare("r1", 1, 2)

        assert mock_migrate.call_count == 1  # только v1 мигрируется

    async def test_compare_returns_error_on_exception(self) -> None:
        mgr = PipelineVersionManager()
        with patch(
            "src.backend.dsl.engine.versioning.main_session_manager"
        ) as mock_mgr:
            mock_mgr.create_session = MagicMock()
            mock_mgr.create_session.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("boom")
            )
            mock_mgr.create_session.return_value.__aexit__ = AsyncMock(
                return_value=False
            )

            result = await mgr.compare("r1", 1, 2)
            assert "error" in result


class TestSpecWithVersion:
    """``_spec_with_version`` — helper."""

    def test_adds_api_version_when_missing(self) -> None:
        row = MagicMock()
        row.spec = {"processors": []}
        row.api_version = "v3"
        spec = PipelineVersionManager._spec_with_version(row)
        assert spec["apiVersion"] == "v3"

    def test_keeps_existing_api_version(self) -> None:
        row = MagicMock()
        row.spec = {"apiVersion": "v1"}
        row.api_version = "v2"
        spec = PipelineVersionManager._spec_with_version(row)
        assert spec["apiVersion"] == "v1"


class TestGetPipelineVersionManager:
    """Singleton getter."""

    def test_returns_same_instance(self) -> None:
        m1 = get_pipeline_version_manager()
        m2 = get_pipeline_version_manager()
        assert isinstance(m1, PipelineVersionManager)
        assert m1 is m2
