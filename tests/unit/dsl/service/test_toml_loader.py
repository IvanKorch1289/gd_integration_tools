"""Unit-тесты service.toml loader + ServiceDSLRegistry (K3 W5 S3)."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.dsl.service.registry import (
    ServiceDSLRegistry,
    get_service_registry,
)
from src.backend.dsl.service.toml_loader import (
    ServiceSpec,
    load_service_toml,
    scan_services,
)


def test_load_service_toml_minimal(tmp_path: Path) -> None:
    """Минимальный manifest: name + version."""
    service_toml = tmp_path / "credit.service.toml"
    service_toml.write_text(
        """
[service]
name = "credit_service"
version = "1.0.0"
""".strip()
    )
    spec = load_service_toml(service_toml)
    assert spec.name == "credit_service"
    assert spec.version == "1.0.0"
    assert spec.protocols == ["rest"]
    assert spec.crud is False


def test_load_service_toml_full_with_crud_actions(tmp_path: Path) -> None:
    """Полный manifest: name + version + protocols + crud + actions."""
    service_toml = tmp_path / "orders.service.toml"
    service_toml.write_text(
        """
[service]
name = "orders_service"
version = "2.1.0"
protocols = ["rest", "grpc", "mq"]
crud = true
entity = "orders"

[[service.actions]]
name = "orders.add"
handler = "extensions.orders.actions:add"
mode = "sync"
""".strip()
    )
    spec = load_service_toml(service_toml)
    assert spec.name == "orders_service"
    assert spec.version == "2.1.0"
    assert spec.protocols == ["rest", "grpc", "mq"]
    assert spec.crud is True
    assert spec.entity == "orders"
    assert len(spec.actions) == 1
    assert spec.actions[0]["name"] == "orders.add"


def test_load_service_toml_missing_name_raises(tmp_path: Path) -> None:
    """Если name отсутствует — ValueError."""
    service_toml = tmp_path / "broken.service.toml"
    service_toml.write_text('[service]\nversion = "1.0.0"\n')
    with pytest.raises(ValueError, match="missing required 'name'"):
        load_service_toml(service_toml)


def test_scan_services_recursive(tmp_path: Path) -> None:
    """scan_services рекурсивно находит все *.service.toml."""
    (tmp_path / "ext1").mkdir()
    (tmp_path / "ext2" / "services").mkdir(parents=True)
    (tmp_path / "ext1" / "a.service.toml").write_text(
        '[service]\nname = "a"\nversion = "1.0"\n'
    )
    (tmp_path / "ext2" / "services" / "b.service.toml").write_text(
        '[service]\nname = "b"\nversion = "1.0"\n'
    )
    specs = scan_services(tmp_path)
    names = sorted(s.name for s in specs)
    assert names == ["a", "b"]


def test_service_registry_register_and_get_when_flag_off() -> None:
    """register() при flag OFF — no-op (по умолчанию)."""
    reg = ServiceDSLRegistry()
    spec = ServiceSpec(name="test_svc", version="1.0.0")
    reg.register(spec)
    # Default-OFF feature flag — реестр пуст
    assert reg.get("test_svc") is None


def test_service_registry_singleton() -> None:
    """get_service_registry() возвращает один и тот же объект."""
    r1 = get_service_registry()
    r2 = get_service_registry()
    assert r1 is r2
    assert isinstance(r1, ServiceDSLRegistry)
