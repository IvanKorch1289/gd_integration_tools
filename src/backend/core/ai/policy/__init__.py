"""AI Policy DSL — декларативные политики AI per-workflow (ADR-NEW-20, S25 W2).

Назначение
----------
Пакет описывает декларативные политики AI:

* :class:`AIPolicySpec` — Pydantic v2 модель политики
  (``input_sanitizers``, ``input_guards``, ``output_guards``,
  ``output_sanitizers``, ``model_router``, ``memory``, ``budget``, ``audit``);
* :class:`PolicyResolver` — резолверы политик по ``workflow_id`` + ``tenant_id``
  из ``ai_policies/*.policy.yaml`` (+ per-tenant override
  ``extensions/<plugin>/ai_policies/``);
* :class:`AIPolicyEnforcer` — middleware-like enforcement-точка для AIGateway.

Использование (S25 W2+):

    from src.backend.core.ai.policy import AIPolicySpec, PolicyResolver

    resolver = PolicyResolver(roots=["ai_policies/", "extensions/*/ai_policies/"])
    policy = await resolver.resolve(workflow_id="credit_check", tenant_id="t-1")

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from src.backend.core.ai.policy.spec import (
    AIPolicySpec,
    AuditSpec,
    BackendSpec,
    BudgetSpec,
    GuardRef,
    MemorySpec,
    ModelRouterSpec,
    SanitizerRef,
)

__all__ = (
    "AIPolicySpec",
    "AuditSpec",
    "BackendSpec",
    "BudgetSpec",
    "GuardRef",
    "MemorySpec",
    "ModelRouterSpec",
    "SanitizerRef",
)
