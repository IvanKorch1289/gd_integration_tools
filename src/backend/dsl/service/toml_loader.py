"""service.toml loader — парсинг декларативного `@service_dsl` манифеста.

Каждый плагин в ``extensions/<name>/services/<service>.service.toml``
описывает сервис: name, version, protocols (REST/SOAP/gRPC/GraphQL/MQ/...),
CRUD-сахар, actions. Loader возвращает :class:`ServiceSpec` для регистрации
в :class:`ServiceDSLRegistry`.

Default-OFF через ``feature_flags.service_toml_loader``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ("ServiceSpec", "load_service_toml", "scan_services")


@dataclass(slots=True)
class ServiceSpec:
    """Манифест сервиса из service.toml.

    Attributes:
        name: Уникальное имя сервиса (например, ``credit_service``).
        version: SemVer версия (``1.0.0``).
        protocols: Список протоколов: ``rest`` / ``soap`` / ``grpc`` /
            ``graphql`` / ``mq`` / ``ws`` / ``sse`` / ``mcp`` / ``mqtt``.
            Спецзначение ``all`` означает все 10 транспортов.
        crud: Если True — auto-registration CRUD endpoints для entity.
        entity: Имя entity для CRUD (если ``crud=True``).
        actions: Список dict'ов с action-определениями
            (``[{name, handler, mode, params_schema, ...}, ...]``).
        raw: Полный TOML-словарь для downstream-инструментов.
    """

    name: str
    version: str
    protocols: list[str] = field(default_factory=lambda: ["rest"])
    crud: bool = False
    entity: str | None = None
    actions: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def load_service_toml(path: Path) -> ServiceSpec:
    """Парсит файл service.toml в :class:`ServiceSpec`.

    Raises:
        FileNotFoundError: Если путь не существует.
        ValueError: Если manifest некорректен (нет name/version).
    """
    if not path.exists():
        raise FileNotFoundError(f"service.toml not found: {path}")

    with path.open("rb") as fh:
        data = tomllib.load(fh)

    svc = data.get("service") or data
    name = svc.get("name")
    version = svc.get("version", "0.1.0")
    if not name:
        raise ValueError(f"service.toml missing required 'name' field: {path}")

    return ServiceSpec(
        name=name,
        version=version,
        protocols=svc.get("protocols", ["rest"]),
        crud=bool(svc.get("crud", False)),
        entity=svc.get("entity"),
        actions=svc.get("actions", []),
        raw=data,
    )


def scan_services(root: Path) -> list[ServiceSpec]:
    """Рекурсивно сканирует ``root`` на ``*.service.toml`` файлы.

    Используется на старте приложения для bulk-регистрации сервисов
    из ``extensions/<name>/services/``.
    """
    if not root.exists() or not root.is_dir():
        return []

    specs: list[ServiceSpec] = []
    for service_toml in root.rglob("*.service.toml"):
        try:
            specs.append(load_service_toml(service_toml))
        except (ValueError, OSError):
            continue
    return specs
