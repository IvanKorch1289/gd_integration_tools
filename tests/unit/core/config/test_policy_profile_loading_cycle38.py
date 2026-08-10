"""Cycle 38 Task #1: prod/staging enable ``policy.engine_enabled``.

Задача: гарантировать, что overlay-файлы ``config_profiles/prod.yml`` и
``config_profiles/staging.yml`` явно выставляют ``policy.engine_enabled=true``
в соответствии с B-12 fix (cycle 37), а dev/dev_light остаются с дефолтным
``engine_enabled=false`` (никаких сетевых вызовов к OPA/Casbin при разработке).

Тесты читают YAML напрямую (через ``_deep_merge`` base + profile) — это
идентично поведению ``YamlConfigSettingsLoader``, но не требует инстанциировать
pydantic-модели (которые могут упасть из-за отсутствия секретов в worktree).
"""


from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Рекурсивный merge, идентичный ``config_loader._deep_merge``."""
    merged: dict = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _read_merged_yaml(profile: str) -> dict:
    """Прочитать merged ``base.yml + {profile}.yml``."""
    base = yaml.safe_load(Path("config_profiles/base.yml").read_text()) or {}
    overlay = yaml.safe_load(Path(f"config_profiles/{profile}.yml").read_text()) or {}
    return _deep_merge(base, overlay)


class TestPolicyEngineEnabledInProductionProfiles:
    """Cycle 38 Task #1: prod/staging обязаны включать policy engine."""

    @pytest.mark.parametrize("profile", ["prod", "staging"])
    def test_engine_enabled_true(self, profile: str) -> None:
        """``{profile}.yml`` обязан выставить ``policy.engine_enabled=true``."""
        data = _read_merged_yaml(profile)
        policy = data.get("policy", {})
        assert policy.get("engine_enabled") is True, (
            f"Cycle 38: {profile}.yml обязан содержать policy.engine_enabled=true. "
            f"Текущее значение: {policy.get('engine_enabled')!r}"
        )

    @pytest.mark.parametrize("profile", ["prod", "staging"])
    def test_opa_url_present(self, profile: str) -> None:
        """``{profile}.yml`` обязан объявить ``policy.opa_url`` (для runtime wiring)."""
        data = _read_merged_yaml(profile)
        policy = data.get("policy", {})
        assert policy.get("opa_url"), (
            f"Cycle 38: {profile}.yml обязан объявить policy.opa_url "
            f"(default или env-override)"
        )

    @pytest.mark.parametrize("profile", ["prod", "staging"])
    def test_casbin_model_path_present(self, profile: str) -> None:
        """``{profile}.yml`` обязан объявить ``policy.casbin_model_path``."""
        data = _read_merged_yaml(profile)
        policy = data.get("policy", {})
        assert policy.get("casbin_model_path"), (
            f"Cycle 38: {profile}.yml обязан объявить policy.casbin_model_path "
            f"(для RBAC enforcement)"
        )


class TestPolicyEngineDisabledInDevProfiles:
    """Cycle 38 Task #1: dev/dev_light обязаны оставаться с default OFF."""

    @pytest.mark.parametrize("profile", ["dev", "dev_light"])
    def test_engine_enabled_default_off(self, profile: str) -> None:
        """``{profile}.yml`` НЕ переопределяет ``policy.engine_enabled``.

        Дефолт ``False`` живёт в ``PolicySettings.engine_enabled`` (см.
        ``src/backend/core/config/services/policy.py``); base.yml его не
        задаёт, overlay-файлы dev-профилей тоже не должны — иначе при
        разработке будут сетевые вызовы к OPA/Casbin.
        """
        data = _read_merged_yaml(profile)
        policy = data.get("policy", {})
        # Отсутствие ключа или False — оба варианта валидны (default OFF).
        assert policy.get("engine_enabled", False) is False, (
            f"Cycle 38: {profile}.yml НЕ должен включать policy.engine_enabled. "
            f"Текущее значение: {policy.get('engine_enabled')!r}"
        )


class TestPolicyYamlSourceDeclarations:
    """Прямая проверка исходников overlay-файлов (anti-drift gate)."""

    def test_prod_yml_declares_policy_block(self) -> None:
        """``prod.yml`` обязан содержать корневой блок ``policy:``."""
        src = Path("config_profiles/prod.yml").read_text()
        assert "policy:" in src, (
            "Cycle 38: prod.yml обязан объявить корневой блок 'policy:'"
        )
        # Проверяем, что внутри policy-блока действительно engine_enabled=true
        # (защита от случайного изменения в будущем).
        assert "engine_enabled: true" in src, (
            "Cycle 38: prod.yml обязан иметь engine_enabled: true в policy-блоке"
        )

    def test_staging_yml_declares_policy_block(self) -> None:
        """``staging.yml`` обязан содержать корневой блок ``policy:``."""
        src = Path("config_profiles/staging.yml").read_text()
        assert "policy:" in src, (
            "Cycle 38: staging.yml обязан объявить корневой блок 'policy:'"
        )
        assert "engine_enabled: true" in src, (
            "Cycle 38: staging.yml обязан иметь engine_enabled: true в policy-блоке"
        )

    def test_base_yml_does_not_force_engine_enabled(self) -> None:
        """``base.yml`` НЕ должен включать policy (dev/dev_light default OFF)."""
        src = Path("config_profiles/base.yml").read_text()
        # base.yml может содержать ``policy:`` для других целей, но не должен
        # форсить engine_enabled=true.
        if "policy:" in src:
            assert "engine_enabled: true" not in src, (
                "Cycle 38: base.yml НЕ должен форсить engine_enabled=true — "
                "это сломает dev/dev_light default OFF"
            )

    def test_dev_yml_does_not_override_engine_enabled(self) -> None:
        """``dev.yml`` НЕ должен включать policy.engine_enabled."""
        src = Path("config_profiles/dev.yml").read_text()
        # Прямой grep: "policy:" + "engine_enabled: true" в том же файле
        # = нарушение.
        assert "engine_enabled: true" not in src, (
            "Cycle 38: dev.yml НЕ должен включать engine_enabled=true"
        )

    def test_dev_light_yml_does_not_override_engine_enabled(self) -> None:
        """``dev_light.yml`` НЕ должен включать policy.engine_enabled."""
        src = Path("config_profiles/dev_light.yml").read_text()
        assert "engine_enabled: true" not in src, (
            "Cycle 38: dev_light.yml НЕ должен включать engine_enabled=true"
        )
