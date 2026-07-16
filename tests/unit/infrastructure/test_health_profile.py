"""Tests for HealthProfile DSL."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.monitoring.health_profile import (
    HealthProfile,
    load_health_profiles,
)


@pytest.mark.unit
def test_default_profile() -> None:
    p = HealthProfile(name="redis")
    assert p.mode == "fast"
    assert p.timeout_s == 1.0
    assert p.critical is True


@pytest.mark.unit
def test_load_profiles_from_yaml(tmp_path: Path) -> None:
    yaml_content = """
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
    f = tmp_path / "health.yaml"
    f.write_text(yaml_content)
    profiles = load_health_profiles(f)
    assert "kafka_main" in profiles
    assert profiles["kafka_main"].mode == "deep"
    assert profiles["kafka_main"].timeout_s == 2.0
    assert profiles["redis_cache"].critical is False
