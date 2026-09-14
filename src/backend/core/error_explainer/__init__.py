"""Error Explainer — diagnostic helper для exceptions (Wave 2 DX #55).

Проблема:
    Когда возникает exception в production, разработчик тратит время:
    - Grep по codebase для поиска source файла.
    - Чтение ADR / runbook вручную.
    - Связывание trace ID с конкретным route.

Решение:
    ``ErrorExplainer`` — context-aware diagnostic helper:

    1. Parse traceback → extract file:line, function name.
    2. Grep codebase для related tests/ADRs/runbooks.
    3. Suggest возможные root causes based on exception type.
    4. Generate human-readable report с commands для reproduce.

Использование::

    from src.backend.core.error_explainer import ErrorExplainer, explain_error

    try:
        risky_operation()
    except Exception as exc:
        report = explain_error(exc, project_root=".")
        print(report.summary)
        print(report.suggested_commands)
"""

from __future__ import annotations

from src.backend.core.error_explainer.explainer import (
    ErrorExplainer,
    ErrorExplanation,
    explain_error,
    get_error_explainer,
)

__all__ = ("ErrorExplanation", "ErrorExplainer", "explain_error", "get_error_explainer")
