"""Admin REST для реестра embedding-провайдеров (ADR-0422).

* ``GET /admin/embedding-providers`` — список имён зарегистрированных
  embedding-провайдеров.

Зачем
----
Streamlit-клиент (``api_clients/k4.py`` → ``list_embedding_providers``) и
страница «Мастер загрузки RAG» запрашивали ``/api/v1/admin/embedding-providers``,
но такого маршрута на сервере не было — UI молча получал 404 и пустой
список. ADR-0422: канонический источник правды — роутер сервера, поэтому
недостающий маршрут добавлен здесь, а не «задокументирован» как 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.backend.core.auth.admin_roles import AdminRole, require_admin

__all__ = ("router",)

# S202 audit fix: require admin role для read-only endpoint.
_ADMIN_GUARD_READ = Depends(
    require_admin((AdminRole.OPERATOR, AdminRole.READ_ONLY, AdminRole.SUPER_ADMIN))
)

router = APIRouter(dependencies=[_ADMIN_GUARD_READ], tags=["admin", "ai"])


@router.get(
    "/embedding-providers",
    summary="Список зарегистрированных embedding-провайдеров",
    description=(
        "Возвращает имена провайдеров из "
        "``services.ai.embedding_registry.EmbeddingProviderRegistry``."
    ),
)
async def list_embedding_providers() -> dict[str, Any]:
    """Вернуть список embedding-провайдеров, зарегистрированных в процессе."""
    from src.backend.services.ai.embedding_registry import get_embedding_registry

    providers = get_embedding_registry().list()
    return {"providers": providers, "count": len(providers)}
