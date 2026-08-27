"""P0 regression test (Cycle 26, REVIEW_2026-08-27 W-3).

ai_costs router был restrict'нут до (OPERATOR, SUPER_ADMIN) — без
READ_ONLY (cost telemetry = sensitive financial data, READ_ONLY выдаётся
monitoring tools без write capability).

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/entrypoints/api/test_ai_costs_role_restriction.py -v
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.admin_roles import AdminRole
from src.backend.entrypoints.api.v1.endpoints import ai_costs


class TestAiCostsRoleRestriction:
    """Cycle 26: ai_costs router НЕ принимает READ_ONLY."""

    def test_router_does_not_accept_read_only(self) -> None:
        """READ_ONLY НЕ в allowed roles."""
        # Извлекаем allowed roles из router dependencies
        deps = ai_costs.router.dependencies
        assert len(deps) > 0, "ai_costs router без dependencies"
        # Парсим require_admin(roles) из first dep
        dep = deps[0]
        # FastAPI Depends object
        dependency = dep.dependency
        # extract roles tuple из require_admin call (frozenset или tuple)
        roles_call = dependency.__closure__[0].cell_contents
        assert frozenset({AdminRole.OPERATOR, AdminRole.SUPER_ADMIN}) == frozenset(
            roles_call
        ), (
            f"Expected roles=(OPERATOR, SUPER_ADMIN), got {roles_call!r}. "
            f"W-3: cost telemetry должен быть restricted."
        )
        assert AdminRole.READ_ONLY not in roles_call, (
            "READ_ONLY НЕ должен иметь доступ к cost telemetry"
        )
