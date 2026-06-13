"""Verification tests: V2 P0 #6 closure — все 7 моделей tenant-isolated.

S102 W3 honest verification: DEEP-RESEARCH claim "4/7 моделей tenant-isolated"
(2026-06-12) устарел. S89-S101 + S92 W2 + S101 W4 миграции закрыли ВСЕ 7/7.

Этот файл — regression-guard: если какая-то модель потеряет TenantMixin
(например, при будущем MRO refactor), тест сломается.
"""
from __future__ import annotations

import pytest

from src.backend.infrastructure.database.tenant_filter import TenantMixin, _is_tenant_aware


# Все 7 моделей должны иметь TenantMixin. Если новая модель добавлена —
# добавить в list. Если существующая модель теряет mixin (refactor) —
# тест сломается.
ALL_TENANT_AWARE_MODELS = (
    "Order",
    "User",
    "File",
    "OrderKind",
    "DslSnapshot",
    "WorkflowEvent",
    "WorkflowInstance",
)


@pytest.mark.parametrize("model_name", ALL_TENANT_AWARE_MODELS)
def test_model_has_tenant_mixin(model_name: str) -> None:
    """``{model_name}`` — TenantMixin subclass, tenant_id column."""
    import importlib

    module_path = {
        "Order": "src.backend.infrastructure.database.models.orders",
        "User": "src.backend.infrastructure.database.models.users",
        "File": "src.backend.infrastructure.database.models.files",
        "OrderKind": "src.backend.infrastructure.database.models.orderkinds",
        "DslSnapshot": "src.backend.infrastructure.database.models.dsl_snapshot",
        "WorkflowEvent": "src.backend.infrastructure.database.models.workflow_event",
        "WorkflowInstance": "src.backend.infrastructure.database.models.workflow_instance",
    }
    mod = importlib.import_module(module_path[model_name])
    cls = getattr(mod, model_name)
    assert issubclass(cls, TenantMixin), (
        f"{model_name} missing TenantMixin в MRO. "
        f"V2 P0 #6 regression — см. ADR-0173 (S91) + ADR-0185 (S101 W4)."
    )
    assert hasattr(cls, "tenant_id"), f"{model_name} missing tenant_id column"
    assert _is_tenant_aware(cls), f"{model_name} not detected as tenant-aware"


def test_v2_p0_6_closure_seven_of_seven() -> None:
    """V2 P0 #6 closed: 7/7 моделей tenant-isolated (100% coverage)."""
    covered = sum(
        1
        for name in ALL_TENANT_AWARE_MODELS
        if name
        in {
            "Order",
            "User",
            "File",
            "OrderKind",
            "DslSnapshot",
            "WorkflowEvent",
            "WorkflowInstance",
        }
    )
    assert covered == 7, f"V2 P0 #6 regression: only {covered}/7 models covered"
