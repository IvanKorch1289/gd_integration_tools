"""ORM-модели LangMem — re-export facade.

Модели перенесены в ``infrastructure.database.models.langmem_models``
для соблюдения архитектурного слоя (services/ не должен импортировать
infrastructure напрямую).

Этот модуль остаётся для обратной совместимости импортёров.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.domain.models.langmem_models import (
        LangMemEpisodic,
        LangMemProcedural,
    )


def __getattr__(name: str):
    if not TYPE_CHECKING:
        if name in ("LangMemEpisodic", "LangMemProcedural"):
            from src.backend.infrastructure.database.models import langmem_models

            return getattr(langmem_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ("LangMemEpisodic", "LangMemProcedural")
