"""RPA Workflow — state machine + checkpoint + HITL + selector resilience (Wave 3).

Проблема (EP-R1):
    RPA-скрипты:
    - Не могут безопасно продолжиться после падения (нет checkpoints).
    - Хрупкие CSS/XPath селекторы ломаются при UI-изменениях.
    - Нет возможности pause для human takeover (CAPTCHA, MFA).
    - Сложно replay failed scenario с diagnostic context.

Решение:
    ``RPAWorkflow`` — state machine + checkpoint store:

    1. States: PENDING → RUNNING → PAUSED → COMPLETED/FAILED.
    2. Checkpoints: snapshot state в каждом transition.
    3. Selector chain: priority/fallback (CSS → ARIA → data-testid).
    4. HITL: pause + human action + resume с audit.
    5. Evidence vault: screenshot, trace, DOM (sanitized) на fail.

Использование::

    from src.backend.core.rpa_workflow import (
        get_rpa_workflow, SelectorChain,
    )

    wf = get_rpa_workflow()

    # Selector chain.
    selectors = SelectorChain([
        ("css", "button.submit"),
        ("aria", "Submit"),
        ("data-testid", "submit-btn"),
    ])

    # Workflow.
    run = await wf.start(workflow_id="payment-flow")
    state = await wf.run_step(run, "navigate", navigate_fn)
    await wf.pause(run, reason="MFA required")
    # ... operator action ...
    await wf.resume(run)
"""

from __future__ import annotations

from src.backend.core.rpa_workflow.selector import (
    Selector,
    SelectorChain,
    SelectorStrategy,
    SelectorType,
)
from src.backend.core.rpa_workflow.workflow import (
    Checkpoint,
    RPAState,
    RPAWorkflow,
    WorkflowRun,
    get_rpa_workflow,
)

__all__ = (
    "Checkpoint",
    "RPAState",
    "RPAWorkflow",
    "Selector",
    "SelectorChain",
    "SelectorStrategy",
    "SelectorType",
    "WorkflowRun",
    "get_rpa_workflow",
)
