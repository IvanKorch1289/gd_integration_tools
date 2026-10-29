"""ADR-0376 — payload источников Vault/Consul и единое разрешение endpoint.

Что проверяется
---------------
* Vault-секрет с **плоским** payload (``{"value": 42}``) реально
  применяется к полям модели (раньше ``_filter_data`` требовал вложенности
  ``payload[yaml_group]`` → секреты из Vault не применялись);
* вложенный payload (``{"probe": {"value": 42}}``) продолжает работать;
* Consul runtime-config **перекрывает YAML** (иначе источник был мёртвым);
* флаг ``_VAULT_UNREACHABLE`` сбрасывается при очистке кэша и при reload
  (иначе после «подъёма» Vault секреты не приходили до рестарта);
* кэш секретов Vault имеет TTL (ротация секрета становится видна);
* единый helper ``vault_endpoint()`` берёт адрес из YAML, если его нет
  в окружении (ADR-0372 перенёс ``VAULT_ADDR`` в YAML).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.backend.core.config import config_loader as cl
from src.backend.core.config.config_loader import (
    BaseSettingsWithLoader,
    YamlConfigSettingsLoader,
    clear_vault_cache,
)
from src.backend.core.config.profile import get_active_profile
from src.backend.core.config.vault import vault_endpoint, vault_secret_path

_PROFILES_DIR: Path | None = None
"""Каталог с YAML-профилями для тестов (см. ``_ProbeSettings``)."""


class _ProbeSettings(BaseSettingsWithLoader):
    """Settings-класс с YAML-группой ``probe`` и одним полем ``value``."""

    yaml_group: ClassVar[str] = "probe"
    model_config = SettingsConfigDict(env_prefix="PROBE_", extra="forbid")

    value: int = 0

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Подменяет только YAML-источник (тесты не трогают файлы репозитория)."""
        sources = super().settings_customise_sources(
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
        if _PROFILES_DIR is None:
            return sources
        return tuple(
            YamlConfigSettingsLoader(settings_cls, profiles_dir=_PROFILES_DIR)
            if type(source).__name__ == "YamlConfigSettingsLoader"
            else source
            for source in sources
        )


_VAULT_READS: list[str] = []
_VAULT_PAYLOAD: dict[str, Any] = {}


class _FakeVaultClient:
    """Заглушка ``hvac.Client`` (считает обращения к Vault)."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url

    def is_authenticated(self) -> bool:
        """Всегда успешная авторизация."""
        return True

    @property
    def secrets(self) -> Any:
        """Секреты KV v2 (совместимо с API ``hvac``)."""

        class _V2:
            @staticmethod
            def read_secret_version(path: str) -> dict[str, Any]:
                _VAULT_READS.append(path)
                return {"data": {"data": dict(_VAULT_PAYLOAD)}}

        class _KV:
            v2 = _V2()

        class _Secrets:
            kv = _KV()

        return _Secrets()


@pytest.fixture(autouse=True)
def _reset_vault_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сбрасывает кэш/флаг Vault и подменяет ``hvac.Client`` заглушкой."""
    import hvac

    _VAULT_READS.clear()
    _VAULT_PAYLOAD.clear()
    monkeypatch.setattr(hvac, "Client", _FakeVaultClient)
    cl._VAULT_UNREACHABLE = False
    clear_vault_cache()


def _enable_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает источник Vault и задаёт обязательные переменные."""
    monkeypatch.setenv("VAULT_ENABLED", "true")
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setenv("VAULT_SECRET_PATH", "secret/data/test")


class TestVaultPayloadShape:
    """Формат payload источника Vault (ADR-0376)."""

    def test_flat_payload_is_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Плоский payload (``ключ = имя поля``) применяется к модели."""
        _enable_vault(monkeypatch)
        _VAULT_PAYLOAD.update({"value": 42})

        assert _ProbeSettings().value == 42

    def test_nested_payload_is_applied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Вложенный payload (``payload[yaml_group]``) тоже применяется."""
        _enable_vault(monkeypatch)
        _VAULT_PAYLOAD.update({"probe": {"value": 42}})

        assert _ProbeSettings().value == 42

    def test_unknown_flat_keys_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Неизвестные ключи плоского payload не ломают валидацию."""
        _enable_vault(monkeypatch)
        _VAULT_PAYLOAD.update({"value": 42, "not_a_field": "x"})

        assert _ProbeSettings().value == 42


class TestConsulOverridesYaml:
    """Consul runtime-config перекрывает YAML (ADR-0372/ADR-0376)."""

    def test_consul_value_wins_over_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Значение из Consul KV приоритетнее значения из YAML."""
        global _PROFILES_DIR

        import src.backend.core.config.consul_config as consul_mod

        profile = get_active_profile().value
        (tmp_path / "base.yml").write_text("probe:\n  value: 0\n")
        (tmp_path / f"{profile}.yml").write_text("probe:\n  value: 5\n")
        _PROFILES_DIR = tmp_path
        cl.clear_yaml_cache()

        class _FakeStore:
            def __init__(self, host: str, port: int, **kwargs: Any) -> None:
                self.host = host

            def items(self, prefix: str) -> list[tuple[str, Any]]:
                assert prefix == "runtime/probe/"
                return [("runtime/probe/value", "999")]

        monkeypatch.setattr(consul_mod, "ConsulConfigStore", _FakeStore)
        monkeypatch.setenv("CONSUL_ENABLED", "true")
        monkeypatch.setenv("CONSUL_ADDR", "http://consul.internal:9500")

        try:
            assert _ProbeSettings().value == 999
        finally:
            _PROFILES_DIR = None
            cl.clear_yaml_cache()


class TestVaultUnreachableFlag:
    """Флаг «Vault недоступен» не должен быть липким (ADR-0376)."""

    def test_cleared_by_clear_vault_cache(self) -> None:
        """``clear_vault_cache()`` сбрасывает ``_VAULT_UNREACHABLE``."""
        cl._VAULT_UNREACHABLE = True
        clear_vault_cache()
        assert cl._VAULT_UNREACHABLE is False

    def test_cleared_by_reload_settings(self) -> None:
        """``reload_settings()`` сбрасывает ``_VAULT_UNREACHABLE``."""
        cl._VAULT_UNREACHABLE = True
        cl.reload_settings(_ProbeSettings())
        assert cl._VAULT_UNREACHABLE is False


class TestVaultCacheTTL:
    """Кэш секретов Vault имеет TTL (ротация секрета видна)."""

    def test_default_ttl_is_300s(self) -> None:
        """TTL кэша по умолчанию — 300 секунд."""
        assert cl._VAULT_CACHE_TTL_SECONDS == 300.0

    def test_expired_entry_is_reread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Истёкший кэш приводит к повторному чтению секрета."""
        _enable_vault(monkeypatch)
        _VAULT_PAYLOAD.update({"value": 42})
        monkeypatch.setattr(cl, "_VAULT_CACHE_TTL_SECONDS", 0.0)

        _ProbeSettings()
        _ProbeSettings()

        assert len(_VAULT_READS) == 2, "Истёкший кэш должен приводить к новому чтению"

    def test_fresh_entry_is_reused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Свежий кэш переиспользуется (одно чтение на путь)."""
        _enable_vault(monkeypatch)
        _VAULT_PAYLOAD.update({"value": 42})

        _ProbeSettings()
        _ProbeSettings()

        assert len(_VAULT_READS) == 1


class TestEnvVersusDotEnvCase:
    """Реальное окружение приоритетнее ``.env`` независимо от регистра.

    ADR-0376: ``os.environ`` на Linux регистрозависим, поэтому ``APP_FOO``
    и ``app_foo`` — разные переменные; pydantic схлопывает их в один
    ключ, и значение из ``.env`` (lowercase) перебивало реальное
    окружение (uppercase) — настройка уезжала в YAML.
    """

    def test_real_env_wins_over_lowercase_dotenv_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``.env`` с lowercase-ключом не перебивает реальный env (uppercase)."""
        global _PROFILES_DIR

        profile = get_active_profile().value
        (tmp_path / "base.yml").write_text("probe:\n  value: 0\n")
        (tmp_path / f"{profile}.yml").write_text("probe:\n  value: 5\n")
        _PROFILES_DIR = tmp_path
        cl.clear_yaml_cache()

        monkeypatch.setenv("PROBE_VALUE", "999")
        monkeypatch.setenv("probe_value", "777")
        cl._ENV_FILE_VALUES["probe_value"] = "777"
        try:
            assert _ProbeSettings().value == 999
        finally:
            cl._ENV_FILE_VALUES.pop("probe_value", None)
            cl.clear_yaml_cache()
            _PROFILES_DIR = None

    def test_case_variant_with_other_value_is_not_file_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case-вариант с ДРУГИМ значением → ключ не считается «из файла»."""
        monkeypatch.setenv("PROBE_MIXED", "from-env")
        monkeypatch.setenv("probe_mixed", "from-file")
        cl._ENV_FILE_VALUES["probe_mixed"] = "from-file"
        try:
            assert "probe_mixed" not in cl._dotenv_only_keys()
            assert cl.env_lookup("PROBE_MIXED") == "from-env"
        finally:
            cl._ENV_FILE_VALUES.pop("probe_mixed", None)

    def test_key_only_from_dotenv_stays_file_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ключ, равный значению из ``.env``, остаётся «файловым» (ниже YAML)."""
        key = "PROBE_FROM_FILE"
        monkeypatch.setenv(key, "same")
        cl._ENV_FILE_VALUES[key] = "same"
        try:
            assert key.lower() in cl._dotenv_only_keys()
            assert cl.env_lookup(key) == ""
        finally:
            cl._ENV_FILE_VALUES.pop(key, None)


class TestVaultEndpointResolution:
    """Единый helper ``vault_endpoint()`` (ADR-0372/ADR-0376)."""

    def test_endpoint_from_yaml_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без ``VAULT_ADDR`` в окружении адрес берётся из YAML."""
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        assert vault_endpoint() == cl._vault_yaml_config()["addr"]

    def test_endpoint_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``VAULT_ADDR`` в окружении перекрывает YAML."""
        monkeypatch.setenv("VAULT_ADDR", "http://env-vault:8200")
        assert vault_endpoint() == "http://env-vault:8200"

    def test_secret_path_from_yaml_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без ``VAULT_SECRET_PATH`` путь берётся из YAML."""
        monkeypatch.delenv("VAULT_SECRET_PATH", raising=False)
        assert vault_secret_path() == cl._vault_yaml_config()["secret_path"]
