"""Инверсия зависимостей в ``utilities/admin_panel`` (ADR-0457, аудит 2026-11-18).

``src/backend/utilities/admin_panel/setup_admin.py`` больше не импортирует
``extensions.core_entities.*`` статически: ModelView-классы расширений
регистрируются в core-реестре ресурсов и забираются оттуда по ключу
``(domain, "admin", name)``.

Проверки:
* в ``src/backend/utilities/**`` нет статических импортов ``extensions.*``;
* ``setup_admin`` берёт views из core-реестра (5 views);
* каждое расширение core_entities регистрирует свой admin-view.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
UTILITIES_ROOT = REPO_ROOT / "src" / "backend" / "utilities"


def _extension_imports(path: Path) -> list[str]:
    """Статические импорты ``extensions.*`` в одном Python-файле."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return [
        name for name in found if name == "extensions" or name.startswith("extensions.")
    ]


def test_utilities_have_no_static_extension_imports() -> None:
    """Ни один модуль ``utilities`` не импортирует ``extensions.*`` статически."""
    offenders: list[str] = []
    for path in UTILITIES_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        imports = _extension_imports(path)
        if imports:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {imports}")
    assert not offenders, offenders


def test_setup_admin_uses_core_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """``setup_admin`` забирает views из core-реестра, а не импортом."""
    from src.backend.utilities.admin_panel import setup_admin as module

    requested: list[tuple[str, str, str]] = []
    registered: list[object] = []

    class _FakeAdmin:
        def __init__(self, app: object, engine: object) -> None:
            self.app = app
            self.engine = engine

        def add_view(self, view: object) -> None:
            registered.append(view)

    class _FakeInitializer:
        async_engine = object()

    def _fake_get(domain: str, kind: str, name: str) -> object:
        requested.append((domain, kind, name))
        return f"{domain}:{kind}:{name}"

    monkeypatch.setattr(module, "Admin", _FakeAdmin)
    monkeypatch.setattr(module, "get_db_initializer", lambda: _FakeInitializer())
    monkeypatch.setattr(module, "get_extension_resource", _fake_get)

    module.setup_admin(app=object())

    assert requested == [
        ("users", "admin", "user"),
        ("orders", "admin", "order"),
        ("orderkinds", "admin", "orderkind"),
        ("files", "admin", "order_file"),
        ("files", "admin", "file"),
    ]
    assert registered == [
        "users:admin:user",
        "orders:admin:order",
        "orderkinds:admin:orderkind",
        "files:admin:order_file",
        "files:admin:file",
    ]


@pytest.fixture
def _clean_extension_registry() -> None:
    """Сбросить core-реестр ресурсов расширений до и после теста."""
    from src.backend.core.extension_registry import reset_extension_resources

    reset_extension_resources()
    yield
    reset_extension_resources()


@pytest.mark.usefixtures("_clean_extension_registry")
def test_core_entities_register_admin_views() -> None:
    """Расширения core_entities отдают свои admin-view в core-реестр."""
    from extensions.core_entities.files.resources import register as register_files
    from extensions.core_entities.orderkinds.resources import (
        register as register_orderkinds,
    )
    from extensions.core_entities.orders.resources import register as register_orders
    from extensions.core_entities.users.resources import register as register_users
    from src.backend.core.extension_registry import get_extension_resource

    for register in (
        register_users,
        register_orders,
        register_files,
        register_orderkinds,
    ):
        register()

    expected = {
        ("users", "user"): "UserAdmin",
        ("orders", "order"): "OrderAdmin",
        ("orderkinds", "orderkind"): "OrderKindAdmin",
        ("files", "file"): "FileAdmin",
        ("files", "order_file"): "OrderFileAdmin",
    }
    for (domain, name), class_name in expected.items():
        view = get_extension_resource(domain, "admin", name)
        assert view.__name__ == class_name, (domain, name, view)
