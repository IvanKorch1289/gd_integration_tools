"""ADR-0397 (кластер D, дефект 3) — capability-гейт для БД-шагов DSL.

Проба ревью: ``db.read``/``db.write`` не были public → subset-проверка
отвергала декларацию роута (``Route 'demo' requests capabilities not
covered … db.read('orders')``), хотя автору негде было её объявить.

Требования:
* ``db.read``/``db.write`` — public, но **с обязательным scope**;
* scope обязан совпасть с алиасом профиля БД (credit_reports → granted,
  oracle_prod → capability_denied);
* текст ошибки должен называть требуемый scope и место декларации.
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    check_capabilities_subset,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.vocabulary import build_default_vocabulary


def test_db_capabilities_are_public_and_require_scope() -> None:
    """db.read/db.write — public, но scope обязателен."""
    vocabulary = build_default_vocabulary()
    for name in ("db.read", "db.write"):
        definition = vocabulary.get(name)
        assert definition.public is True, f"{name} должен быть public"
        assert definition.scope_required is True, f"{name} требует явный scope"


def test_route_may_declare_db_read_without_plugin_owner() -> None:
    """Декларация db.read в route.toml проходит subset-проверку."""
    check_capabilities_subset(
        route="demo",
        route_caps=[CapabilityRef(name="db.read", scope="credit_reports")],
        plugin_caps_by_name={},
        vocabulary=build_default_vocabulary(),
    )


def test_db_capability_declaration_without_scope_is_rejected() -> None:
    """Scope обязателен: декларация без scope → ошибка валидации."""
    gate = CapabilityGate()
    with pytest.raises(ValueError, match="scope"):
        gate.declare("demo", [CapabilityRef(name="db.read")])


def test_db_profile_scope_is_enforced_at_runtime() -> None:
    """Объявленный scope = алиас профиля → granted; другой профиль → denied."""
    gate = CapabilityGate()
    gate.declare("demo", [CapabilityRef(name="db.read", scope="credit_reports")])

    gate.check("demo", "db.read", "credit_reports")

    with pytest.raises(CapabilityDeniedError):
        gate.check("demo", "db.read", "oracle_prod")


def test_runtime_denial_names_required_scope_and_declaration_place() -> None:
    """Сообщение об отказе называет требуемый scope и место декларации."""
    gate = CapabilityGate()
    gate.declare("demo", [CapabilityRef(name="db.read", scope="credit_reports")])

    with pytest.raises(CapabilityDeniedError) as exc_info:
        gate.check("demo", "db.read", "oracle_prod")

    message = str(exc_info.value)
    assert "oracle_prod" in message
    assert "scope" in message
    assert "route.toml" in message


def test_superset_error_names_scope_and_declaration_place() -> None:
    """Subset-ошибка объясняет, какой scope нужен и где объявить."""
    with pytest.raises(CapabilitySupersetError) as exc_info:
        check_capabilities_subset(
            route="demo",
            route_caps=[CapabilityRef(name="rpa.browser.click", scope="chrome")],
            plugin_caps_by_name={},
            vocabulary=build_default_vocabulary(),
        )

    message = str(exc_info.value)
    assert "scope" in message
    assert "route.toml" in message
