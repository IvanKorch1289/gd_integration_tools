"""Privacy/data-subject erasure subpackage (W9 P2-13 Phase 3).

W9 P2-13 Phase 3 (cycle 153, MINIMAX plan): извлечено из
``core/privacy/delete_data_subject.py`` (691 LOC god-module) в package
с 8 cohesion-focused submodules (см. ADR-0328).

Back-compat: ``core/privacy/delete_data_subject.py`` (singular, файл) →
thin re-export shim, продолжает экспортировать все 11 публичных имён.
``core/privacy/__init__.py`` (public API facade) без изменений.

Public API:
    from src.backend.core.privacy import (  # noqa: F401 — re-export
        DeleteDataSubject, ErasureAdapter,
        ErasureStrategy, ErasureResultStatus,
        PostgresErasureAdapter, RedisErasureAdapter,
        S3ErasureAdapter, QdrantErasureAdapter,
        LangMemErasureAdapter, TombstonePublisher,
        AdapterResult, OrchestratorResult,
    )

Submodules:
    _types.py — ErasureStrategy, ErasureResultStatus, AdapterResult,
                OrchestratorResult, ErasureAdapter (Protocol)
    _postgres.py — PostgresErasureAdapter (stub)
    _redis.py — RedisErasureAdapter (SCAN + UNLINK)
    _s3.py — S3ErasureAdapter (delete objects + versions)
    _qdrant.py — QdrantErasureAdapter (delete vectors)
    _langmem.py — LangMemErasureAdapter (delete episodic + procedural)
    _tombstone.py — TombstonePublisher
    _orchestrator.py — DeleteDataSubject (main)
"""

from __future__ import annotations

from src.backend.core.privacy.delete_data_subject._langmem import (  # noqa: F401 — re-export
    LangMemErasureAdapter as LangMemErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._orchestrator import (  # noqa: F401 — re-export
    DeleteDataSubject as DeleteDataSubject,
)
from src.backend.core.privacy.delete_data_subject._postgres import (  # noqa: F401 — re-export
    PostgresErasureAdapter as PostgresErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._qdrant import (  # noqa: F401 — re-export
    QdrantErasureAdapter as QdrantErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._redis import (  # noqa: F401 — re-export
    RedisErasureAdapter as RedisErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._s3 import (  # noqa: F401 — re-export
    S3ErasureAdapter as S3ErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._tombstone import (  # noqa: F401 — re-export
    TombstonePublisher as TombstonePublisher,
)
from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    AdapterResult as AdapterResult,
)
from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    ErasureAdapter as ErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    ErasureResultStatus as ErasureResultStatus,
)
from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    ErasureStrategy as ErasureStrategy,
)
from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    OrchestratorResult as OrchestratorResult,
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
