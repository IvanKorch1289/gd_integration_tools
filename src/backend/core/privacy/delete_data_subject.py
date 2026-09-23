"""Backward-compat shim — ``delete_data_subject`` стал package.

W9 P2-13 Phase 3 (cycle 153, MINIMAX plan): ``delete_data_subject.py``
(691 LOC god-module) → ``delete_data_subject/`` package с 8 cohesion-focused
submodules (см. ADR-0328). Этот модуль — thin re-export shim для
backward-compat: ``from src.backend.core.privacy.delete_data_subject import X``
продолжает работать для всех 11 публичных имён.

Migration::

    # До (W9 P2-13 Phase 3 — still works через этот shim):
    from src.backend.core.privacy.delete_data_subject import (
        DeleteDataSubject, PostgresErasureAdapter, RedisErasureAdapter,
    )

    # После (canonical, рекомендуется для нового кода):
    from src.backend.core.privacy.delete_data_subject import (
        DeleteDataSubject, PostgresErasureAdapter, RedisErasureAdapter,
    )
    # Тот же путь — split прозрачен для consumers.

Removal: запланирован на cycle 162 (отдельный cleanup wave после telemetry
audit consumer migration).
"""

from __future__ import annotations

from src.backend.core.privacy.delete_data_subject import (  # type: ignore[attr-defined]
    AdapterResult as AdapterResult,
)
from src.backend.core.privacy.delete_data_subject import (
    DeleteDataSubject as DeleteDataSubject,
)
from src.backend.core.privacy.delete_data_subject import (
    ErasureAdapter as ErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject import (
    ErasureResultStatus as ErasureResultStatus,
)
from src.backend.core.privacy.delete_data_subject import (
    ErasureStrategy as ErasureStrategy,
)
from src.backend.core.privacy.delete_data_subject import (
    LangMemErasureAdapter as LangMemErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject import (
    OrchestratorResult as OrchestratorResult,
)
from src.backend.core.privacy.delete_data_subject import (
    PostgresErasureAdapter as PostgresErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject import (
    QdrantErasureAdapter as QdrantErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject import (
    RedisErasureAdapter as RedisErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject import (
    S3ErasureAdapter as S3ErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject import (
    TombstonePublisher as TombstonePublisher,
)

__all__ = (
    "AdapterResult",
    "DeleteDataSubject",
    "ErasureAdapter",
    "ErasureResultStatus",
    "ErasureStrategy",
    "LangMemErasureAdapter",
    "OrchestratorResult",
    "PostgresErasureAdapter",
    "QdrantErasureAdapter",
    "RedisErasureAdapter",
    "S3ErasureAdapter",
    "TombstonePublisher",
)
