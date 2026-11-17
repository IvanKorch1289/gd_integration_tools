"""Контракт-тесты инверсии ``dsl → extensions`` при регистрации action'ов (ADR-0457).

``src/backend/dsl/commands/setup/registers_domains.py`` не должен импортировать
``extensions.*`` напрямую: объекты расширений (схемы/сервисы) получаются из
core-реестра ``src.backend.core.extension_registry``. Публичная поверхность
(набор зарегистрированных action'ов) при этом не меняется.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator

import pytest

from src.backend.core.extension_registry import get_extension_resource
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.commands.setup import registers_domains

pytestmark = pytest.mark.unit

#: Ожидаемые action'ы по доменам — фиксируют публичную поверхность DSL.
EXPECTED_ACTIONS: dict[str, tuple[str, ...]] = {
    "orders": (
        "orders.add",
        "orders.create_skb_order",
        "orders.delete",
        "orders.get",
        "orders.get_file_and_json",
        "orders.get_file_base64",
        "orders.get_file_from_storage",
        "orders.get_file_link",
        "orders.get_result",
        "orders.list",
        "orders.send_order_data",
        "orders.update",
    ),
    "files": ("files.add", "files.delete", "files.get", "files.list", "files.update"),
    "users": ("users.add", "users.delete", "users.get", "users.list", "users.update"),
    "orderkinds": (
        "orderkinds.add",
        "orderkinds.delete",
        "orderkinds.get",
        "orderkinds.list",
        "orderkinds.update",
    ),
    "skb": (
        "skb.add_request",
        "skb.get_objects_by_address",
        "skb.get_orders_list",
        "skb.get_request_kinds",
        "skb.get_response_by_order",
    ),
    "dadata": ("dadata.get_geolocate",),
}


@pytest.fixture
def _isolated_registry() -> Iterator[None]:
    """Изолирует process-wide реестр action-handler'ов на время теста."""
    saved_handlers = dict(action_handler_registry._handlers)
    saved_metadata = dict(action_handler_registry._metadata)
    saved_middleware = list(action_handler_registry._middleware)
    action_handler_registry.clear()
    yield
    action_handler_registry.clear()
    action_handler_registry._handlers.update(saved_handlers)
    action_handler_registry._metadata.update(saved_metadata)
    action_handler_registry._middleware.extend(saved_middleware)


def _module_tree() -> ast.Module:
    """Возвращает AST модуля регистрации доменов."""
    return ast.parse(inspect.getsource(registers_domains))


def _imported_modules(tree: ast.AST) -> list[str]:
    """Собирает имена модулей, импортируемых в AST-дереве."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _called_names(tree: ast.AST) -> set[str]:
    """Собирает имена вызываемых функций в AST-дереве."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


class TestNoDirectExtensionsImports:
    """DSL-слой не связан с ``extensions.*`` напрямую (ADR-0457)."""

    def test_module_has_no_extensions_imports(self) -> None:
        """В модуле нет ни одного импорта из пакета ``extensions``."""
        imported = _imported_modules(_module_tree())

        offenders = [name for name in imported if name.split(".")[0] == "extensions"]
        assert not offenders, (
            f"dsl не должен импортировать extensions напрямую: {offenders}"
        )

    @pytest.mark.parametrize(
        "func_name",
        [
            "_register_orders",
            "_register_files",
            "_register_skb_api",
            "_register_dadata",
            "_register_users",
            "_register_orderkinds",
        ],
    )
    def test_register_functions_resolve_via_registry(self, func_name: str) -> None:
        """Каждая доменная регистрация берёт объекты из core-реестра."""
        func = getattr(registers_domains, func_name)
        tree = ast.parse(inspect.getsource(func))

        assert _called_names(tree).issuperset({"get_extension_resource"}), (
            f"{func_name} должен резолвить объекты расширений через реестр"
        )
        offenders = [
            name for name in _imported_modules(tree) if name.startswith("extensions")
        ]
        assert not offenders, (
            f"{func_name} не должен импортировать extensions.* напрямую: {offenders}"
        )

    def test_files_service_not_taken_from_deprecated_shim(self) -> None:
        """Сервис файлов берётся из реестра, а не из deprecated-shim'а."""
        tree = ast.parse(inspect.getsource(registers_domains._register_files))

        assert "src.backend.services.io.files" not in _imported_modules(tree), (
            "deprecated-shim src.backend.services.io.files больше не используется"
        )


class TestLazyResolution:
    """Ресурсы расширений резолвятся лениво — на момент регистрации."""

    def test_no_module_level_resource_resolution(self) -> None:
        """На уровне модуля нет вызовов ``get_extension_resource(...)``."""
        module_level_calls = [
            node
            for node in _module_tree().body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "get_extension_resource"
        ]

        assert not module_level_calls, (
            "резолв ресурсов расширений должен оставаться внутри функций — "
            "иначе регистрация перестанет быть отложенной"
        )


class TestRegisteredActionsUnchanged:
    """Набор зарегистрированных action'ов не изменился (ADR-0457)."""

    def test_action_set_matches_expected(self, _isolated_registry: None) -> None:
        """Регистрация доменов даёт ровно ожидаемый набор action'ов."""
        registers_domains._register_orders()
        registers_domains._register_files()
        registers_domains._register_users()
        registers_domains._register_orderkinds()
        registers_domains._register_skb_api()
        registers_domains._register_dadata()

        expected = {
            action for actions in EXPECTED_ACTIONS.values() for action in actions
        }

        assert set(action_handler_registry.list_actions()) == expected

    def test_handlers_use_extension_objects(self, _isolated_registry: None) -> None:
        """В спецификации action'ов — те же объекты, что отдаёт реестр."""
        registers_domains._register_orders()
        registers_domains._register_files()
        registers_domains._register_users()
        registers_domains._register_orderkinds()
        registers_domains._register_skb_api()
        registers_domains._register_dadata()

        handlers = action_handler_registry._handlers

        # orders: сервис + схема запроса по id.
        order_service = get_extension_resource("orders", "service", "orders")
        order_id_query = get_extension_resource("orders", "schema", "id_query")
        assert handlers["orders.create_skb_order"].service_getter is order_service
        assert handlers["orders.create_skb_order"].payload_model is order_id_query

        # files / users / orderkinds: CRUD-сервисы расширений.
        assert handlers["files.get"].service_getter is get_extension_resource(
            "files", "service", "files"
        )
        assert handlers["users.get"].service_getter is get_extension_resource(
            "users", "service", "users"
        )
        assert handlers["orderkinds.get"].service_getter is get_extension_resource(
            "orderkinds", "service", "orderkinds"
        )

        # skb / dadata: схемы расширений, сервисы — из слоя services.
        assert handlers["skb.add_request"].payload_model is get_extension_resource(
            "skb", "schema", "api_skb_order_in"
        )
        assert handlers[
            "skb.get_objects_by_address"
        ].payload_model is get_extension_resource("skb", "schema", "objects_by_address")
        assert handlers["skb.get_orders_list"].payload_model is get_extension_resource(
            "skb", "schema", "orders_list"
        )
        assert handlers[
            "skb.get_response_by_order"
        ].payload_model is get_extension_resource("skb", "schema", "result")
        assert handlers["dadata.get_geolocate"].payload_model is get_extension_resource(
            "dadata", "schema", "geolocate"
        )
