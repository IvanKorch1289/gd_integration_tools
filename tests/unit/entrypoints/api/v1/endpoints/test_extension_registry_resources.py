"""Регресс-тесты инверсии ``entrypoints → extensions`` (ADR-0457).

Эндпоинты получают схемы и сервисы расширений через core-реестр
(:func:`src.backend.core.extension_registry.get_extension_resource`),
а не прямым импортом ``extensions.*``.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from src.backend.core.extension_registry import get_extension_resource

pytestmark = pytest.mark.unit

#: Модули entrypoints, переведённые на core-реестр (ADR-0457).
_ENTRYPOINTS_MODULES = (
    "src.backend.entrypoints.api.v1.endpoints.orders",
    "src.backend.entrypoints.api.v1.endpoints.orderkinds",
    "src.backend.entrypoints.api.v1.endpoints.users",
    "src.backend.entrypoints.api.v1.endpoints.files",
    "src.backend.entrypoints.api.v1.endpoints.skb",
    "src.backend.entrypoints.api.v1.endpoints.dadata",
    "src.backend.entrypoints.api.v1.endpoints.admin",
    "src.backend.entrypoints.api.v1.endpoints.auth_login",
    "src.backend.entrypoints.api.generator.setup",
)


@pytest.mark.parametrize(
    ("module_name", "attr_name", "domain", "kind", "key"),
    [
        (
            "src.backend.entrypoints.api.v1.endpoints.orders",
            "OrderSchemaIn",
            "orders",
            "schema",
            "schema_in",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.orders",
            "get_order_service",
            "orders",
            "service",
            "orders",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.orderkinds",
            "OrderKindSchemaIn",
            "orderkinds",
            "schema",
            "schema_in",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.orderkinds",
            "get_order_kind_service",
            "orderkinds",
            "service",
            "orderkinds",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.users",
            "UserSchemaIn",
            "users",
            "schema",
            "schema_in",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.users",
            "get_user_service",
            "users",
            "service",
            "users",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.files",
            "FileSchemaOut",
            "files",
            "schema",
            "schema_out",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.skb",
            "APISKBOrderSchemaIn",
            "skb",
            "schema",
            "api_skb_order_in",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.dadata",
            "DadataGeolocateQuerySchema",
            "dadata",
            "schema",
            "geolocate",
        ),
        (
            "src.backend.entrypoints.api.v1.endpoints.admin",
            "AdminToggleRouteQuerySchema",
            "core_admin",
            "schema",
            "toggle_route",
        ),
    ],
)
def test_endpoint_module_resolves_resource_via_registry(
    module_name: str, attr_name: str, domain: str, kind: str, key: str
) -> None:
    """Имя в модуле эндпоинта — тот же объект, что в core-реестре."""
    module = importlib.import_module(module_name)

    assert getattr(module, attr_name) is get_extension_resource(domain, kind, key)


def test_auth_login_resolves_user_service_lazily() -> None:
    """``auth_login`` тянет сервис пользователей лениво (внутри функции)."""
    from src.backend.entrypoints.api.v1.endpoints import auth_login

    source = Path(auth_login.__file__ or "")
    text = source.read_text(encoding="utf-8")

    assert "extensions.core_entities" not in text
    assert 'get_extension_resource("users", "service", "users")' in text


@pytest.mark.parametrize("module_name", _ENTRYPOINTS_MODULES)
def test_entrypoints_do_not_import_extensions_directly(module_name: str) -> None:
    """Ни один переведённый модуль не содержит импорта ``extensions.*``."""
    module = importlib.import_module(module_name)
    source = Path(module.__file__ or "")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "extensions"
        ):
            offenders.append(node.module or "")
        elif isinstance(node, ast.Import):
            offenders.extend(
                alias.name
                for alias in node.names
                if alias.name.startswith("extensions")
            )

    assert offenders == []
