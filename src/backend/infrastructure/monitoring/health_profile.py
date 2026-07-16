"""Declarative health-check profiles (Wave 4).

YAML-конфиг для настройки health-check параметров коннекторов::

    health_checks:
      kafka_main:
        mode: deep
        timeout: 2.0
        critical: true
      redis_cache:
        mode: fast
        timeout: 0.5
        critical: false
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.backend.infrastructure.clients.base_connector import HealthMode

__all__ = ("HealthProfile", "load_health_profiles")


@dataclass(slots=True)
class HealthProfile:
    """Конфигурация health-check для одного коннектора."""

    name: str
    mode: HealthMode = "fast"
    timeout_s: float = 1.0
    critical: bool = True


def load_health_profiles(yaml_path: Path) -> dict[str, HealthProfile]:
    """Загружает health-профили из YAML-файла."""
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text()) or {}
    raw_profiles = data.get("health_checks", {})
    profiles: dict[str, HealthProfile] = {}
    for name, cfg in raw_profiles.items():
        profiles[name] = HealthProfile(
            name=name,
            mode=cfg.get("mode", "fast"),
            timeout_s=cfg.get("timeout", 1.0),
            critical=cfg.get("critical", True),
        )
    return profiles
