"""Хранилище runtime-конфигурации IP-ограничений.

Поддерживает:
* глобальные ``admin_ips`` / ``admin_routes`` (для /admin/*);
* per-route правила (паттерн пути → список разрешённых IP/сетей);
* hot-reload из YAML-файла и через admin API;
* singleton, thread-safe.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("IPRestrictionStore", "IPRestrictionRule", "get_ip_restriction_store")

logger = get_logger("core.security.ip_restriction")


@dataclass(frozen=True, slots=True)
class IPRestrictionRule:
    """Правило ограничения доступа по IP для одного паттерна пути."""

    allowed_ips: frozenset[str] = field(default_factory=frozenset)
    enabled: bool = True


class IPRestrictionStore:
    """Singleton-хранилище IP-ограничений.

    Args:
        admin_ips: Множество разрешённых IP/сетей для admin-маршрутов.
        admin_routes: Список glob-паттернов административных маршрутов.
    """

    _instance: IPRestrictionStore | None = None
    _lock: Lock = Lock()

    def __new__(cls) -> IPRestrictionStore:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # __new__ гарантирует один экземпляр, но __init__ может вызываться
        # многократно при импортах; избегаем переинициализации состояния.
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._state_lock = Lock()
        self._admin_ips: set[str] = set()
        self._admin_routes: list[str] = []
        self._admin_patterns: list[re.Pattern[str]] = []
        self._route_rules: dict[str, IPRestrictionRule] = {}

    def update_admin(
        self,
        admin_ips: set[str] | list[str] | tuple[str, ...] | None = None,
        admin_routes: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """Обновляет глобальные admin IP-ограничения."""
        with self._state_lock:
            if admin_ips is not None:
                self._admin_ips = set(admin_ips)
            if admin_routes is not None:
                self._admin_routes = list(admin_routes)
                self._admin_patterns = [
                    re.compile(fnmatch.translate(route)) for route in self._admin_routes
                ]
        logger.info(
            "IP restriction admin config updated: %d ips, %d routes",
            len(self._admin_ips),
            len(self._admin_routes),
        )

    def set_route_rule(
        self,
        path_pattern: str,
        allowed_ips: set[str] | list[str] | tuple[str, ...],
        *,
        enabled: bool = True,
    ) -> None:
        """Устанавливает per-route IP-правило."""
        rule = IPRestrictionRule(allowed_ips=frozenset(allowed_ips), enabled=enabled)
        with self._state_lock:
            self._route_rules[path_pattern] = rule
        logger.info(
            "IP restriction per-route rule set: %s (enabled=%s, ips=%d)",
            path_pattern,
            enabled,
            len(allowed_ips),
        )

    def remove_route_rule(self, path_pattern: str) -> None:
        """Удаляет per-route IP-правило."""
        with self._state_lock:
            self._route_rules.pop(path_pattern, None)
        logger.info("IP restriction per-route rule removed: %s", path_pattern)

    def clear_route_rules(self) -> None:
        """Удаляет все per-route правила."""
        with self._state_lock:
            self._route_rules.clear()

    def reload_from_yaml(self, path: str | Path) -> bool:
        """Перезагружает ограничения из YAML-файла.

        Returns:
            True если файл прочитан, False если файл отсутствует.
        """
        file_path = Path(path)
        if not file_path.is_file():
            logger.debug("IP restriction config not found: %s", file_path)
            return False
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML required for IP restriction reload") from exc

        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        admin = raw.get("admin", {})
        self.update_admin(
            admin_ips=set(admin.get("ips", [])),
            admin_routes=list(admin.get("routes", [])),
        )
        self.clear_route_rules()
        for entry in raw.get("routes", []):
            self.set_route_rule(
                path_pattern=entry["path_pattern"],
                allowed_ips=entry.get("allowed_ips", []),
                enabled=bool(entry.get("enabled", True)),
            )
        logger.info("IP restriction config reloaded from %s", file_path)
        return True

    def is_allowed(self, path: str, client_ip: str | None) -> bool:
        """Проверяет, разрешён ли доступ по пути и IP.

        Логика:
        1. Если есть активное per-route правило для ``path`` — проверяем по нему.
        2. Иначе если путь попадает под admin_routes — проверяем admin_ips.
        3. Иначе доступ разрешён.
        """
        if client_ip is None:
            return False

        with self._state_lock:
            route_rules = dict(self._route_rules)
            admin_patterns = list(self._admin_patterns)
            admin_ips = set(self._admin_ips)

        # Per-route rules have priority.
        for pattern, rule in route_rules.items():
            if not rule.enabled:
                continue
            if fnmatch.fnmatch(path, pattern):
                return self._ip_matches(client_ip, rule.allowed_ips)

        # Global admin routes.
        if any(p.match(path) for p in admin_patterns):
            return self._ip_matches(client_ip, admin_ips)

        return True

    @staticmethod
    def _ip_matches(client_ip: str, allowed_ips: set[str] | frozenset[str]) -> bool:
        """Проверяет IP против множества IP/сетей."""
        from ipaddress import ip_address, ip_network

        try:
            client_obj = ip_address(client_ip)
        except ValueError:
            return False

        for allowed in allowed_ips:
            if "/" in allowed:
                try:
                    network = ip_network(allowed, strict=False)
                except ValueError:
                    continue
                if client_obj in network:
                    return True
            elif client_ip == allowed:
                return True
        return False

    def snapshot(self) -> dict[str, Any]:
        """Возвращает текущее состояние хранилища (для admin API)."""
        with self._state_lock:
            return {
                "admin_ips": sorted(self._admin_ips),
                "admin_routes": list(self._admin_routes),
                "route_rules": {
                    path: {
                        "allowed_ips": sorted(rule.allowed_ips),
                        "enabled": rule.enabled,
                    }
                    for path, rule in self._route_rules.items()
                },
            }


def get_ip_restriction_store() -> IPRestrictionStore:
    """Возвращает singleton ``IPRestrictionStore``."""
    return IPRestrictionStore()
