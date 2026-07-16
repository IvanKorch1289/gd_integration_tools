"""LangMem service — DEPRECATED re-export shim (S210).

Canonical implementation: :mod:`src.backend.services.ai.memory.langmem_service`
(3-tier: episodic + semantic + procedural с feature-flag + inMemory fallback).
Этот файл оставлен как backward-compat shim — все 6 исторических importers
(``scheduler/scheduled_tasks``, ``plugins/composition/setup_ai_stack``,
``entrypoints/api/v1/endpoints/langmem_admin``, ``memory/langmem/{consolidation,rlm}``,
``tests/unit/services/ai/test_langmem_smoke``) продолжают работать через
re-export canonical API.

S210: добавлены ``LangMemDisabled`` exception, ``consolidate()`` и ``stats()``
в canonical — теперь legacy API полностью покрывается canonical. Shim можно
удалить после явной миграции всех 6 importers на ``memory.langmem_service``.

Использование для нового кода (рекомендуется)::

    from src.backend.services.ai.memory.langmem_service import (
        LangMemService, LangMemDisabled, get_langmem_service,
    )

Использование legacy (deprecated)::

    from src.backend.services.ai.langmem_service import (
        LangMemService, LangMemDisabled, get_langmem_service,
    )  # works, но canonical location предпочтительнее
"""

from __future__ import annotations

# S210: backward-compat re-export shim.
# Canonical: src.backend.services.ai.memory.langmem_service
# Deprecated: this module (will be removed after 6 importers migrate).

from src.backend.services.ai.memory.langmem_service import (  # noqa: F401
    LangMemDisabled,
    LangMemService,
    MemoryEntry,
    get_langmem_service,
)

__all__ = (
    "LangMemDisabled",
    "LangMemService",
    "MemoryEntry",
    "get_langmem_service",
)