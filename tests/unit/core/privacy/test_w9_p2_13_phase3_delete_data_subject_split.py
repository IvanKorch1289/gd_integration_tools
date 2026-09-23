"""Focused tests: W9 P2-13 Phase 3 — core/privacy/delete_data_subject god-module split.

Проверяет:
1. Все 11 публичных имён доступны из обоих путей (core.privacy + core.privacy.delete_data_subject).
2. Каждый submodule экспортирует ожидаемые классы.
3. Все 5 адаптеров реализуют ErasureAdapter Protocol (duck typing).
4. Shim `delete_data_subject.py` (file) работает как back-compat.
"""

from __future__ import annotations

from typing import get_type_hints

import pytest

from src.backend.core.privacy import (
    AdapterResult,
    DeleteDataSubject,
    ErasureAdapter,
    ErasureResultStatus,
    ErasureStrategy,
    LangMemErasureAdapter,
    OrchestratorResult,
    PostgresErasureAdapter,
    QdrantErasureAdapter,
    RedisErasureAdapter,
    S3ErasureAdapter,
    TombstonePublisher,
)
from src.backend.core.privacy import delete_data_subject as dds_package
from src.backend.core.privacy.delete_data_subject import (
    AdapterResult as ShimAdapterResult,
    DeleteDataSubject as ShimDeleteDataSubject,
    ErasureAdapter as ShimErasureAdapter,
    ErasureResultStatus as ShimErasureResultStatus,
    ErasureStrategy as ShimErasureStrategy,
    LangMemErasureAdapter as ShimLangMemErasureAdapter,
    OrchestratorResult as ShimOrchestratorResult,
    PostgresErasureAdapter as ShimPostgresErasureAdapter,
    QdrantErasureAdapter as ShimQdrantErasureAdapter,
    RedisErasureAdapter as ShimRedisErasureAdapter,
    S3ErasureAdapter as ShimS3ErasureAdapter,
    TombstonePublisher as ShimTombstonePublisher,
)
from src.backend.core.privacy.delete_data_subject._langmem import (
    LangMemErasureAdapter as LangMemFromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._orchestrator import (
    DeleteDataSubject as DeleteDataSubjectFromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._postgres import (
    PostgresErasureAdapter as PostgresFromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._qdrant import (
    QdrantErasureAdapter as QdrantFromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._redis import (
    RedisErasureAdapter as RedisFromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._s3 import (
    S3ErasureAdapter as S3FromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._tombstone import (
    TombstonePublisher as TombstoneFromSubmodule,
)
from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult as TypesAdapterResult,
    ErasureAdapter as TypesErasureAdapter,
    ErasureResultStatus as TypesErasureResultStatus,
    ErasureStrategy as TypesErasureStrategy,
    OrchestratorResult as TypesOrchestratorResult,
)


class TestBackCompatImports:
    """Все 11 публичных имён доступны из обоих путей (shim + package)."""

    @pytest.mark.parametrize(
        "shim_obj,canonical_obj,name",
        [
            (ShimAdapterResult, AdapterResult, "AdapterResult"),
            (ShimDeleteDataSubject, DeleteDataSubject, "DeleteDataSubject"),
            (ShimErasureAdapter, ErasureAdapter, "ErasureAdapter"),
            (ShimErasureResultStatus, ErasureResultStatus, "ErasureResultStatus"),
            (ShimErasureStrategy, ErasureStrategy, "ErasureStrategy"),
            (ShimLangMemErasureAdapter, LangMemErasureAdapter, "LangMemErasureAdapter"),
            (ShimOrchestratorResult, OrchestratorResult, "OrchestratorResult"),
            (ShimPostgresErasureAdapter, PostgresErasureAdapter, "PostgresErasureAdapter"),
            (ShimQdrantErasureAdapter, QdrantErasureAdapter, "QdrantErasureAdapter"),
            (ShimRedisErasureAdapter, RedisErasureAdapter, "RedisErasureAdapter"),
            (ShimS3ErasureAdapter, S3ErasureAdapter, "S3ErasureAdapter"),
            (ShimTombstonePublisher, TombstonePublisher, "TombstonePublisher"),
        ],
    )
    def test_shim_returns_same_class(
        self, shim_obj, canonical_obj, name: str
    ) -> None:
        """Shim импортирует тот же class (id-equal)."""
        assert shim_obj is canonical_obj, (
            f"{name}: shim identity {shim_obj.__name__}@{id(shim_obj)} != "
            f"canonical {canonical_obj.__name__}@{id(canonical_obj)}"
        )


class TestSubmoduleExports:
    """Каждый submodule экспортирует ожидаемые классы."""

    def test_types_submodule(self) -> None:
        """_types экспортирует ErasureStrategy/Status/Adapter/Orchestrator/ErasureAdapter."""
        from src.backend.core.privacy.delete_data_subject import _types

        assert _types.ErasureStrategy is ErasureStrategy
        assert _types.ErasureResultStatus is ErasureResultStatus
        assert _types.AdapterResult is AdapterResult
        assert _types.OrchestratorResult is OrchestratorResult
        assert _types.ErasureAdapter is ErasureAdapter

    def test_postgres_submodule(self) -> None:
        """_postgres экспортирует PostgresErasureAdapter."""
        from src.backend.core.privacy.delete_data_subject import _postgres

        assert _postgres.PostgresErasureAdapter is PostgresErasureAdapter

    def test_redis_submodule(self) -> None:
        """_redis экспортирует RedisErasureAdapter."""
        from src.backend.core.privacy.delete_data_subject import _redis

        assert _redis.RedisErasureAdapter is RedisErasureAdapter

    def test_s3_submodule(self) -> None:
        """_s3 экспортирует S3ErasureAdapter."""
        from src.backend.core.privacy.delete_data_subject import _s3

        assert _s3.S3ErasureAdapter is S3ErasureAdapter

    def test_qdrant_submodule(self) -> None:
        """_qdrant экспортирует QdrantErasureAdapter."""
        from src.backend.core.privacy.delete_data_subject import _qdrant

        assert _qdrant.QdrantErasureAdapter is QdrantErasureAdapter

    def test_langmem_submodule(self) -> None:
        """_langmem экспортирует LangMemErasureAdapter."""
        from src.backend.core.privacy.delete_data_subject import _langmem

        assert _langmem.LangMemErasureAdapter is LangMemErasureAdapter

    def test_tombstone_submodule(self) -> None:
        """_tombstone экспортирует TombstonePublisher."""
        from src.backend.core.privacy.delete_data_subject import _tombstone

        assert _tombstone.TombstonePublisher is TombstonePublisher

    def test_orchestrator_submodule(self) -> None:
        """_orchestrator экспортирует DeleteDataSubject."""
        from src.backend.core.privacy.delete_data_subject import _orchestrator

        assert _orchestrator.DeleteDataSubject is DeleteDataSubject


class TestProtocolConformance:
    """Все 5 адаптеров реализуют ErasureAdapter Protocol (duck typing)."""

    @pytest.mark.parametrize(
        "adapter_cls",
        [
            PostgresErasureAdapter,
            RedisErasureAdapter,
            S3ErasureAdapter,
            QdrantErasureAdapter,
            LangMemErasureAdapter,
        ],
    )
    def test_adapter_implements_protocol(self, adapter_cls: type) -> None:
        """Adapter имеет `name` attribute + `execute` async method."""
        instance = adapter_cls()
        assert hasattr(instance, "name"), (
            f"{adapter_cls.__name__} missing 'name' attribute"
        )
        assert isinstance(instance.name, str)
        assert hasattr(instance, "execute"), (
            f"{adapter_cls.__name__} missing 'execute' method"
        )
        assert callable(instance.execute)


class TestPackageMetadata:
    """Package metadata correctness."""

    def test_package_module_exists(self) -> None:
        """delete_data_subject — package, не module."""
        # import работатает (smoke test)
        assert dds_package is not None

    def test_all_submodule_split_under_500_loc(self) -> None:
        """Каждый submodule < 500 LOC (V15 forbidden pattern compliance)."""
        from pathlib import Path

        dds_dir = Path("src/backend/core/privacy/delete_data_subject")
        for py_file in sorted(dds_dir.glob("_*.py")):
            loc = sum(1 for _ in py_file.open())
            assert loc < 500, (
                f"{py_file.name} = {loc} LOC (V15 forbidden: >500 = god-module)"
            )


class TestShimReduction:
    """Shim file dramatically reduced (691 → 56 LOC)."""

    def test_shim_under_100_loc(self) -> None:
        """Shim file < 100 LOC."""
        from pathlib import Path

        shim_path = Path("src/backend/core/privacy/delete_data_subject.py")
        loc = sum(1 for _ in shim_path.open())
        assert loc < 100, f"shim {loc} LOC (target: <100, было 691)"
