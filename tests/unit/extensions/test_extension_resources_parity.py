# ruff: noqa: S101
"""Регресс-тест паритета core-реестра ресурсов расширений (ADR-0457).

ADR-0457 переворачивает зависимость ``src/ → extensions``: расширение
**отдаёт** свои ресурсы (схемы/сервисы/модели) в core-реестр
(:mod:`src.backend.core.extension_registry`), а потребитель (entrypoints,
DSL-слои, сервисы) **забирает** их по ключу ``(domain, kind, name)``.

Реестр — точка сбоя «молча»: если расширение не зарегистрировало ресурс,
потребитель падает с ``KeyError`` на импорте модуля (на старте приложения),
а если ресурс зарегистрирован, но не используется — инвентарь реестра
расходится с реальностью, и следующий потребитель получит ``None`` вместо
объекта.

Инварианты:
1. каждый ``get_extension_resource(...)`` в ``src/`` обеспечен регистрацией;
2. каждая регистрация используется (нет «сирот»);
3. рантайм-загрузка расширений реально наполняет реестр всеми объявленными
   ресурсами (объекты не ``None``, типы совпадают с ожидаемыми).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.backend.core.extension_registry import (
    get_extension_registry,
    load_extension_resources,
    reset_extension_resources,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXTENSIONS_DIR = _REPO_ROOT / "extensions"
_SRC_DIR = _REPO_ROOT / "src"

#: Ожидаемые пары ``(kind, имя ресурса)`` — потребители в src/.
_EXPECTED_CONSUMED = {
    ("core_admin", "schema", "cache_invalidate_pattern"),
    ("core_admin", "schema", "cache_invalidate_table"),
    ("core_admin", "schema", "cache_invalidate_tags"),
    ("core_admin", "schema", "cache_keys_query"),
    ("core_admin", "schema", "cache_value_path"),
    ("core_admin", "schema", "toggle_feature_flag"),
    ("core_admin", "schema", "toggle_route"),
    ("dadata", "schema", "geolocate"),
    # Admin-панель (ADR-0457): ModelView-классы расширений берутся из
    # core-реестра — прямых импортов ``extensions.*`` в utilities нет.
    ("files", "admin", "file"),
    ("files", "admin", "order_file"),
    ("files", "schema", "filter"),
    ("files", "schema", "schema_in"),
    ("files", "schema", "schema_out"),
    ("files", "schema", "version_schema"),
    ("files", "service", "files"),
    ("orderkinds", "admin", "orderkind"),
    ("orderkinds", "schema", "filter"),
    ("orderkinds", "schema", "schema_in"),
    ("orderkinds", "schema", "schema_out"),
    ("orderkinds", "schema", "version_schema"),
    ("orderkinds", "service", "orderkinds"),
    ("orders", "admin", "order"),
    ("orders", "schema", "filter"),
    ("orders", "schema", "id_path"),
    ("orders", "schema", "id_query"),
    ("orders", "schema", "schema_in"),
    ("orders", "schema", "schema_out"),
    ("orders", "schema", "version_schema"),
    ("orders", "service", "orders"),
    ("skb", "schema", "api_skb_order_in"),
    ("skb", "schema", "objects_by_address"),
    ("skb", "schema", "orders_list"),
    ("skb", "schema", "result"),
    ("skb", "service", "resolve_waf_route"),
    ("users", "admin", "user"),
    ("users", "model", "user"),
    ("users", "schema", "filter"),
    ("users", "schema", "schema_in"),
    ("users", "schema", "schema_out"),
    ("users", "schema", "version_schema"),
    ("users", "service", "users"),
}


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """Константы верхнего уровня модуля (для ``DOMAIN = "..."``)."""
    constants: dict[str, object] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def _literal(node: ast.expr, constants: dict[str, object]) -> object | None:
    """Значение литерала (в т.ч. имя константы модуля)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _registered_resources() -> dict[tuple[str, str, str], Path]:
    """Все регистрации из ``extensions/**/resources.py`` (AST)."""
    registered: dict[tuple[str, str, str], Path] = {}
    for path in sorted(_EXTENSIONS_DIR.rglob("resources.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "register_extension_resource"
            ):
                continue
            if len(node.args) < 3:
                continue
            values = [_literal(arg, constants) for arg in node.args[:3]]
            if not all(isinstance(value, str) for value in values):
                continue
            domain, kind, name = values
            assert isinstance(domain, str)
            assert isinstance(kind, str)
            assert isinstance(name, str)
            registered[(domain, kind, name)] = path
    return registered


def _consumed_resources() -> dict[tuple[str, str, str], list[str]]:
    """Все ``get_extension_resource(...)`` из ``src/`` (AST)."""
    consumed: dict[tuple[str, str, str], list[str]] = {}
    for path in sorted(_SRC_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — защита от не-парсящихся файлов
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "get_extension_resource"
            ):
                continue
            if len(node.args) < 3:
                continue
            values = []
            for arg in node.args[:3]:
                value = arg.value if isinstance(arg, ast.Constant) else None
                values.append(value)
            if not all(isinstance(value, str) for value in values):
                continue
            domain, kind, name = values
            assert isinstance(domain, str)
            assert isinstance(kind, str)
            assert isinstance(name, str)
            consumed.setdefault((domain, kind, name), []).append(
                f"{path}:{node.lineno}"
            )
    return consumed


def test_every_consumed_resource_is_registered() -> None:
    """Каждый запрошенный ресурс обеспечен регистрацией расширения."""
    registered = _registered_resources()
    consumed = _consumed_resources()
    missing = {key: sites for key, sites in consumed.items() if key not in registered}
    assert not missing, (
        "потребители запрашивают незарегистрированные ресурсы: "
        + "; ".join(f"{key} <- {sites}" for key, sites in sorted(missing.items()))
    )


def test_no_orphan_registrations() -> None:
    """Каждый зарегистрированный ресурс используется потребителем."""
    registered = _registered_resources()
    consumed = _consumed_resources()
    orphans = sorted(set(registered) - set(consumed))
    assert not orphans, (
        "зарегистрированные, но не используемые ресурсы (инвентарь реестра "
        f"разошёлся с реальностью): {orphans}"
    )


def test_consumed_resource_set_is_stable() -> None:
    """Набор потребляемых ресурсов соответствует ожидаемому."""
    consumed = set(_consumed_resources())
    assert consumed == _EXPECTED_CONSUMED, (
        "набор ресурсов изменился: "
        f"добавлены={sorted(consumed - _EXPECTED_CONSUMED)}, "
        f"удалены={sorted(_EXPECTED_CONSUMED - consumed)}"
    )


def test_runtime_registry_matches_declarations() -> None:
    """Рантайм-загрузка расширений наполняет реестр всеми ресурсами."""
    registered = _registered_resources()
    reset_extension_resources()
    try:
        load_extension_resources(force=True)
        registry = get_extension_registry()
        for key in registered:
            domain, kind, name = key
            found = registry.find(domain, kind, name)
            assert found is not None, f"{key} не попал в реестр при загрузке"
        assert set(registry.domains()) == {domain for domain, _, _ in registered}
    finally:
        reset_extension_resources()


@pytest.mark.parametrize(
    ("domain", "kind", "name"),
    [
        ("orders", "service", "orders"),
        ("users", "service", "users"),
        ("orderkinds", "service", "orderkinds"),
        ("files", "service", "files"),
        ("skb", "service", "resolve_waf_route"),
        ("users", "model", "user"),
    ],
)
def test_service_resources_are_callable(domain: str, kind: str, name: str) -> None:
    """Сервисные ресурсы — callable (getter'ы), модель — класс."""
    from src.backend.core.extension_registry import get_extension_resource

    obj = get_extension_resource(domain, kind, name)
    assert obj is not None
    if kind == "service":
        assert callable(obj), f"{domain}/{kind}/{name} должен быть callable"
    else:
        assert isinstance(obj, type), f"{domain}/{kind}/{name} должен быть классом"
