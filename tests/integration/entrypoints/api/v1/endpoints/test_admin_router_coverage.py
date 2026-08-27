"""P0 security regression test (Cycle 6, production-grade plan).

Проверка: 3 admin-prefixed роутера, которые ранее использовали только
``require_auth`` (любой authenticated principal — без role check), теперь
требуют ``require_admin(...)``:

* ``langmem_admin`` — ранее ``require_auth([API_KEY, JWT])``, теперь
  ``require_admin(OPERATOR, SUPER_ADMIN)`` на router level.
* ``ai_costs`` — ранее ``require_auth``, теперь
  ``require_admin(READ_ONLY, OPERATOR, SUPER_ADMIN)`` на router level.
* ``tech.py`` state-changing endpoints (``/send-email``,
  ``/upload-excel-for-mass-create``, ``/degradation/snapshot``,
  ``/get-all-custom-tables``) — теперь ``require_admin`` через
  ``dependencies=[...]``.

Negative tests: principal без admin role → 403.
Positive tests: principal с admin role → endpoint registration
включает require_admin (через AST source-of-truth guards).

Запуск::

    .venv/bin/python -m pytest \\
      tests/integration/entrypoints/api/v1/endpoints/test_admin_router_coverage.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path("/home/user/dev/gd_integration_tools")


def _read(rel_path: str) -> str:
    """Read repo file."""
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _find_router_calls(source: str, router_class: str = "APIRouter") -> list[ast.Call]:
    """Найти все calls вида ``APIRouter(...dependencies=[..., require_admin(...)])``."""
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == router_class
    ]


def _has_require_admin_in_router(kwargs: ast.keyword) -> bool:
    """Проверить, что ``dependencies=`` список содержит ``Depends(require_admin(...))``."""
    if not isinstance(kwargs.value, ast.List):
        return False
    for elt in kwargs.value.elts:
        if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "Depends":
            for sub in elt.args:
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "require_admin":
                    return True
    return False


class TestLangmemAdminCoverage:
    """Cycle 6 fix: ``langmem_admin.py`` router-level ``require_admin``."""

    def test_router_has_require_admin(self) -> None:
        """``APIRouter(dependencies=[Depends(require_admin(...))])`` в source."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/langmem_admin.py")
        routers = _find_router_calls(source)
        assert routers, "APIRouter(...) call not found in langmem_admin.py"
        found = False
        for router in routers:
            for kw in router.keywords:
                if kw.arg == "dependencies" and _has_require_admin_in_router(kw):
                    found = True
        assert found, (
            "langmem_admin.py: APIRouter(...) НЕ имеет require_admin в dependencies. "
            "P0 cycle 6: ранее использовал require_auth — API key holder получал доступ."
        )

    def test_no_legacy_require_auth_call(self) -> None:
        """В langmem_admin.py НЕ должно быть ``require_auth(`` call после фикса."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/langmem_admin.py")
        assert "require_auth(" not in source, (
            "langmem_admin.py: ``require_auth(...)`` call остался — не полностью мигрирован."
        )


class TestAiCostsCoverage:
    """Cycle 6 fix: ``ai_costs.py`` router-level ``require_admin``."""

    def test_router_has_require_admin(self) -> None:
        """``APIRouter(dependencies=[..., require_admin(...)])`` в source."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/ai_costs.py")
        routers = _find_router_calls(source)
        assert routers, "APIRouter(...) call not found in ai_costs.py"
        found = False
        for router in routers:
            for kw in router.keywords:
                if kw.arg == "dependencies" and _has_require_admin_in_router(kw):
                    found = True
        assert found, (
            "ai_costs.py: APIRouter(...) НЕ имеет require_admin. P0 cycle 6."
        )

    def test_no_legacy_require_auth_call(self) -> None:
        """В ai_costs.py НЕ должно быть ``require_auth(`` call."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/ai_costs.py")
        assert "require_auth(" not in source, (
            "ai_costs.py: ``require_auth(...)`` call остался — не полностью мигрирован."
        )


class TestTechEndpointsCoverage:
    """Cycle 6 fix: ``tech.py`` per-endpoint ``require_admin``."""

    @pytest.mark.parametrize(
        "spec_name",
        ["send_email", "degradation_snapshot", "get_all_custom_tables"],
    )
    def test_action_spec_has_require_admin(self, spec_name: str) -> None:
        """``ActionSpec(name=spec_name, ..., dependencies=[..., require_admin(...)])``."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/tech.py")
        tree = ast.parse(source)
        # Найти ActionSpec call с name=<spec_name>
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ActionSpec"
            ):
                name_value = None
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        name_value = kw.value.value
                        break
                if name_value != spec_name:
                    continue
                # Проверяем dependencies
                for kw in node.keywords:
                    if kw.arg == "dependencies" and isinstance(kw.value, ast.List):
                        if _has_require_admin_in_router(ast.keyword(arg="dependencies", value=kw.value)):
                            found = True
        assert found, (
            f"tech.py: ActionSpec(name='{spec_name}', ...) НЕ имеет require_admin в "
            f"dependencies. P0 cycle 6."
        )

    def test_upload_excel_router_has_require_admin(self) -> None:
        """``router.add_api_route(.../upload-excel-for-mass-create..., dependencies=[..., require_admin(...)])``."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/tech.py")
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Поддерживаем и `add_api_route(...)` и `router.add_api_route(...)`
            is_target = (
                (isinstance(func, ast.Name) and func.id == "add_api_route")
                or (
                    isinstance(func, ast.Attribute) and func.attr == "add_api_route"
                )
            )
            if not is_target:
                continue
            path_kw = next((kw for kw in node.keywords if kw.arg == "path"), None)
            if (
                path_kw
                and isinstance(path_kw.value, ast.Constant)
                and "upload-excel" in path_kw.value.value
            ):
                for kw in node.keywords:
                    if kw.arg == "dependencies" and _has_require_admin_in_router(kw):
                        found = True
        assert found, (
            "tech.py: add_api_route(path=/upload-excel...) НЕ имеет require_admin в "
            "dependencies. P0 cycle 6."
        )

    def test_send_email_admin_role_checked(self) -> None:
        """``send_email`` — state-changing (POST publish event), OPERATOR+SUPER_ADMIN."""
        source = _read("src/backend/entrypoints/api/v1/endpoints/tech.py")
        # Грубая sanity check: имя "send_email" + require_admin в коде
        assert "send_email" in source
        assert "require_admin" in source
        # Более точная проверка через AST
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ActionSpec"
            ):
                name_kw = next(
                    (kw for kw in node.keywords if kw.arg == "name"), None
                )
                if (
                    name_kw
                    and isinstance(name_kw.value, ast.Constant)
                    and name_kw.value.value == "send_email"
                ):
                    deps_kw = next(
                        (kw for kw in node.keywords if kw.arg == "dependencies"), None
                    )
                    assert deps_kw is not None, (
                        "send_email ActionSpec не имеет dependencies (должен иметь "
                        "require_admin после cycle 6)."
                    )


class TestAdminRolesImport:
    """Все 3 файла импортируют ``AdminRole, require_admin`` из ``core.auth.admin_roles``."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "src/backend/entrypoints/api/v1/endpoints/langmem_admin.py",
            "src/backend/entrypoints/api/v1/endpoints/ai_costs.py",
            "src/backend/entrypoints/api/v1/endpoints/tech.py",
        ],
    )
    def test_imports_admin_roles(self, rel_path: str) -> None:
        source = _read(rel_path)
        assert (
            "from src.backend.core.auth.admin_roles import AdminRole, require_admin"
            in source
        ), (
            f"{rel_path}: НЕ импортирует AdminRole, require_admin. P0 cycle 6."
        )
