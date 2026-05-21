"""Stream E.7: advanced-alchemy backend для LangMem (Точка 1 плана).

Lazy-обёртка над :class:`advanced_alchemy.repository.SQLAlchemyAsyncRepository`
для моделей :class:`LangMemEpisodic` и :class:`LangMemProcedural`. Импорт
``advanced_alchemy`` лениво — без ``uv sync`` пакет может отсутствовать
в dev_light, тогда :func:`get_episodic_repository` и
:func:`get_procedural_repository` поднимут :class:`AdvancedAlchemyMissing`.

Полезные фишки advanced-alchemy, которые получаем "бесплатно":

* bulk: ``add_many``, ``update_many``, ``upsert_many``;
* фильтры: :class:`LimitOffset`, :class:`OrderBy`, :class:`SearchFilter`,
  :class:`CollectionFilter`, :class:`BeforeAfter`;
* pagination: :class:`OffsetPagination[ModelT]`;
* soft-delete (для GDPR-purge эпизодов).

Использование (когда uv sync поднимет колесо):

.. code-block:: python

    from advanced_alchemy.filters import BeforeAfter, LimitOffset

    repo = get_episodic_repository(session)
    items = await repo.list(
        BeforeAfter(field_name="occurred_at", before=until, after=since),
        LimitOffset(limit=50, offset=0),
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from advanced_alchemy.repository import SQLAlchemyAsyncRepository

    from src.backend.services.ai.langmem_models import (
        LangMemEpisodic,
        LangMemProcedural,
    )

__all__ = (
    "AdvancedAlchemyMissing",
    "get_episodic_repository",
    "get_procedural_repository",
)


class AdvancedAlchemyMissing(RuntimeError):
    """Raised when advanced_alchemy не установлен в окружении."""


def _resolve_repository_cls() -> type[Any]:
    try:
        from advanced_alchemy.repository import SQLAlchemyAsyncRepository
    except ImportError as exc:  # pragma: no cover — uv sync не пройден
        raise AdvancedAlchemyMissing(
            "advanced-alchemy не установлен; запустите 'uv sync' "
            "или используйте core EpisodicMemory/ProceduralMemory без bulk-API."
        ) from exc
    return SQLAlchemyAsyncRepository


def get_episodic_repository(session: Any) -> SQLAlchemyAsyncRepository[LangMemEpisodic]:
    """Возвращает Episodic-репозиторий для :class:`LangMemEpisodic`.

    Требует ``advanced_alchemy`` (поднимется через ``uv sync``).
    """
    from src.backend.services.ai.langmem_models import LangMemEpisodic

    base_cls = _resolve_repository_cls()

    class EpisodicRepo(base_cls):  # type: ignore[misc, valid-type]
        model_type = LangMemEpisodic

    return EpisodicRepo(session=session)


def get_procedural_repository(
    session: Any,
) -> SQLAlchemyAsyncRepository[LangMemProcedural]:
    """Возвращает Procedural-репозиторий для :class:`LangMemProcedural`."""
    from src.backend.services.ai.langmem_models import LangMemProcedural

    base_cls = _resolve_repository_cls()

    class ProceduralRepo(base_cls):  # type: ignore[misc, valid-type]
        model_type = LangMemProcedural

    return ProceduralRepo(session=session)
