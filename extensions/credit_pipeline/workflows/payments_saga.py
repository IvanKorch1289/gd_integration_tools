"""Payments saga (Sprint 4 К3-D §3): two-phase capture карты.

Декларативный saga-pattern через :class:`WorkflowBuilder` / :class:`SagaBuilder`:
демонстрирует двух-фазную авторизацию (authorize → capture) с откатом
при failure любой фазы.

Forward (3 шага):
    1. ``payments.validate_card`` — валидировать карту через PSP.
    2. ``payments.authorize`` — авторизовать списание (output_key=``auth_id``).
    3. ``payments.capture`` — захватить авторизованную сумму
       (output_key=``charge_id``).

Compensate (2 шага):
    * ``payments.void_authorization`` — отменить авторизацию.
    * ``payments.void_capture`` — отменить captured-charge (chargeback path).

Asymmetric forward/compensate: validate_card не требует отката,
поэтому compensate-цепочка короче (2 vs 3). Compiler корректно
обрабатывает разные длины (см. :func:`compile_saga_step` —
compensation для completed forward шагов с `idx < len(compensate)`).
"""

from __future__ import annotations

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = ("build_payments_saga_workflow",)


def build_payments_saga_workflow() -> WorkflowDeclaration:
    """Собрать декларацию workflow ``payments.charge_card``.

    Returns:
        Иммутабельная :class:`WorkflowDeclaration`, готовая к
        :func:`compile_workflow` или регистрации в Worker'е.
    """
    return (
        WorkflowBuilder("payments.charge_card")
        .description("Зарядка карты с двух-фазной авторизацией")
        .saga()
        .forward("payments.validate_card")
        .forward("payments.authorize", output_key="auth_id")
        .forward("payments.capture", output_key="charge_id")
        .compensate("payments.void_authorization")
        .compensate("payments.void_capture")
        .end_saga()
        .build()
    )
