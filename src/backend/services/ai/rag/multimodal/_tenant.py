"""Tenant resolution helper для MultimodalRAG (cycle 37, B-11).

Тонкий локальный wrapper вокруг ``_resolve_effective_tenant_id`` из
``src.backend.services.ai.rag_service.search_mixin`` — дубликат по
Ponytail (один ~20-LOC модуль, без разрастания фасадов).

Контракт идентичен каноническому:
    * Non-empty explicit (``"bank_x"``) → возвращается as-is,
      override'ит ``TenantContext``.
    * Empty explicit (``""``) → ``None`` (явный opt-out фильтра).
    * ``None`` без ``tenant_scope`` → ``None`` (legacy).
    * ``None`` внутри ``tenant_scope`` → ``ctx.tenant_id``.

Используется в service.py / _legacy.py / pipeline.py для post-filter
defence-in-depth.
"""

from __future__ import annotations

from src.backend.core.tenancy import current_tenant

__all__ = ("_resolve_effective_tenant_id",)


def _resolve_effective_tenant_id(tenant_id: str | None) -> str | None:
    """Резолвит эффективный ``tenant_id`` для multimodal retrieval-фильтра.

    Args:
        tenant_id: Явный kwarg (default ``None``).

    Returns:
        Эффективный tenant_id или ``None`` для legacy passthrough.
    """
    if tenant_id is not None:
        return tenant_id or None
    ctx = current_tenant()
    return ctx.tenant_id if ctx is not None else None
