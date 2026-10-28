"""ADR-0372 — приоритет источников конфигурации (cycle 172, кластер CF2).

Что проверяется
---------------
* фактический порядок источников в ``settings_customise_sources``;
* fail-closed для YAML (отсутствие профиля = ошибка, а не тихий откат
  на дефолты) и fail-soft для Vault/Consul;
* порт Consul не теряется;
* ``VAULT_ADDR``/``VAULT_SECRET_PATH`` — fallback на YAML-секцию ``vault``;
* секрет Vault читается один раз (кэш по пути);
* YAML-кэш инвалидируется по изменению файла + есть публичный
  ``clear_yaml_cache()``;
* ``.env`` не перебивает YAML/Vault (приоритет ниже YAML).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
)

from src.backend.core.config import config_loader as cl
from src.backend.core.config.config_loader import (
    BaseSettingsWithLoader,
    ConsulConfigSettingsSource,
    VaultConfigSettingsSource,
    YamlConfigSettingsLoader,
    clear_yaml_cache,
)
from src.backend.core.config.profile import get_active_profile

_PROFILES_DIR: Path | None = None


class _ChainSettings(BaseSettingsWithLoader):
    """Settings-класс с канонической цепочкой источников."""

    yaml_group: ClassVar[str] = "probe"
    model_config = SettingsConfigDict(env_prefix="PROBE_", extra="forbid")

    value: int = 0


class _ProbeSettings(BaseSettingsWithLoader):
    """Settings-класс, у которого YAML берётся из временного каталога."""

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
        """Подменяем только YAML-источник (тесты не трогают файлы репозитория)."""
        assert _PROFILES_DIR is not None
        sources = super().settings_customise_sources(
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
        return tuple(
            YamlConfigSettingsLoader(settings_cls, profiles_dir=_PROFILES_DIR)
            if type(source).__name__ == "YamlConfigSettingsLoader"
            else source
            for source in sources
        )


def _write_profile(profiles_dir: Path, profile: str, value: int) -> Path:
    """Записывает ``probe.value`` в overlay активного профиля."""
    path = profiles_dir / f"{profile}.yml"
    path.write_text(f"probe:\n  value: {value}\n")
    return path


def _source_types() -> list[str]:
    """Типы источников в порядке фактического приоритета."""
    sources = _ChainSettings.settings_customise_sources(
        _ChainSettings,
        InitSettingsSource(_ChainSettings, {}),
        EnvSettingsSource(_ChainSettings),
        DotEnvSettingsSource(_ChainSettings),
        SecretsSettingsSource(_ChainSettings),
    )
    return [type(source).__name__ for source in sources]


_VAULT_READS: list[str] = []
_VAULT_CREATED: list[tuple[str, str]] = []


class _FakeVaultClient:
    """Заглушка ``hvac.Client`` (считает обращения к Vault)."""

    def __init__(self, url: str, token: str) -> None:
        _VAULT_CREATED.append((url, token))

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
                return {"data": {"data": {"probe_value": "from-vault"}}}

        class _KV:
            v2 = _V2()

        class _Secrets:
            kv = _KV()

        return _Secrets()


@pytest.fixture
def fake_vault(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Подменяет ``hvac.Client`` заглушкой и сбрасывает кэши Vault."""
    import hvac

    _VAULT_READS.clear()
    _VAULT_CREATED.clear()
    monkeypatch.setattr(hvac, "Client", _FakeVaultClient)
    cl._VAULT_UNREACHABLE = False
    cl.clear_vault_cache()
    return _VAULT_READS


class TestSourcePriority:
    """Порядок источников (выше = приоритетнее)."""

    def test_env_source_is_above_vault(self) -> None:
        """Реальное окружение приоритетнее Vault."""
        types = _source_types()
        assert types.index("DotEnvAwareEnvSource") < types.index(
            "VaultConfigSettingsSource"
        )

    def test_vault_is_above_yaml(self) -> None:
        """Vault приоритетнее YAML."""
        types = _source_types()
        assert types.index("VaultConfigSettingsSource") < types.index(
            "YamlConfigSettingsLoader"
        )

    def test_consul_is_above_yaml(self) -> None:
        """Consul приоритетнее YAML (ADR-0372: runtime-config из Consul работал)."""
        types = _source_types()
        assert types.index("ConsulConfigSettingsSource") < types.index(
            "YamlConfigSettingsLoader"
        )

    def test_dotenv_file_is_below_yaml(self) -> None:
        """``.env`` — только секреты: он НИЖЕ YAML (не перебивает конфиг)."""
        types = _source_types()
        assert types.index("YamlConfigSettingsLoader") < types.index(
            "DotEnvSettingsSource"
        )

    def test_dotenv_aware_env_source_is_used(self) -> None:
        """Env-source исключает значения, пришедшие из ``.env``."""
        types = _source_types()
        assert "DotEnvAwareEnvSource" in types
        assert "EnvSettingsSource" not in types


class TestYamlFailClosed:
    """Отсутствие YAML-профиля — фатальная ошибка, а не тихий откат."""

    def test_missing_profile_raises(self, tmp_path: Path) -> None:
        """Пустой каталог профилей → источник пробрасывает RuntimeError."""
        source = YamlConfigSettingsLoader(_ChainSettings, profiles_dir=tmp_path)
        with pytest.raises(RuntimeError, match="Config not found"):
            source()

    def test_missing_profile_is_not_silently_empty(self, tmp_path: Path) -> None:
        """Источник НЕ возвращает ``{}`` при ошибке (иначе — откат на дефолты)."""
        source = YamlConfigSettingsLoader(_ChainSettings, profiles_dir=tmp_path)
        try:
            data = source()
        except RuntimeError:
            return
        pytest.fail(f"Ожидался RuntimeError, получен {data!r}")

    def test_vault_source_stays_fail_soft(self) -> None:
        """Vault — fail-soft: недоступен → ``{}``, без исключения."""
        assert cl.FilteredSettingsSource.fail_closed is False
        assert VaultConfigSettingsSource.fail_closed is False

    def test_consul_source_stays_fail_soft(self) -> None:
        """Consul — fail-soft: недоступен → ``{}``, без исключения."""
        assert ConsulConfigSettingsSource.fail_closed is False

    def test_yaml_source_is_fail_closed(self) -> None:
        """YAML — fail-closed (ADR-0372)."""
        assert YamlConfigSettingsLoader.fail_closed is True


class TestConsulAddress:
    """``CONSUL_ADDR`` разбирается без потери порта."""

    def test_port_is_preserved(self) -> None:
        """Порт из ``CONSULT_ADDR`` не теряется (было: ``split(':')[0]``)."""
        assert cl._parse_consul_addr("http://consul.internal:9500") == (
            "consul.internal",
            9500,
            "http",
        )

    def test_host_without_port_uses_default(self) -> None:
        """Без порта — дефолт 8500."""
        assert cl._parse_consul_addr("consul.internal") == (
            "consul.internal",
            8500,
            "http",
        )

    def test_scheme_is_preserved(self) -> None:
        """Схема из URL сохраняется."""
        assert cl._parse_consul_addr("https://consul:8500")[2] == "https"

    def test_source_uses_parsed_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Источник Consul создаёт store с портом из ``CONSUL_ADDR``."""
        import src.backend.core.config.consul_config as consul_mod

        captured: dict[str, Any] = {}

        class _FakeStore:
            def __init__(self, host: str, port: int, **kwargs: Any) -> None:
                captured["host"] = host
                captured["port"] = port

            def items(self, prefix: str) -> list[tuple[str, Any]]:
                captured["prefix"] = prefix
                return []

        monkeypatch.setattr(consul_mod, "ConsulConfigStore", _FakeStore)
        monkeypatch.setenv("CONSUL_ENABLED", "true")
        monkeypatch.setenv("CONSUL_ADDR", "http://consul.internal:9500")

        source = ConsulConfigSettingsSource(_ChainSettings)
        assert source._load_data() == {}
        assert captured["host"] == "consul.internal"
        assert captured["port"] == 9500


class TestVaultYamlFallback:
    """``VAULT_ADDR``/``VAULT_SECRET_PATH`` — fallback на YAML (ADR-0372)."""

    def test_yaml_vault_section_is_read(self) -> None:
        """Секция ``vault`` читается из YAML активного профиля."""
        cfg = cl._vault_yaml_config()
        assert "addr" in cfg
        assert str(cfg["addr"]).startswith("http")

    def test_addr_falls_back_to_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Без ``VAULT_ADDR`` в окружении берётся значение из YAML."""
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        cfg = cl._vault_yaml_config()
        assert cl._env_lookup("VAULT_ADDR") == ""
        assert cfg.get("addr")

    def test_yaml_fallback_used_by_source(
        self, monkeypatch: pytest.MonkeyPatch, fake_vault: list[str]
    ) -> None:
        """Источник Vault использует YAML-адрес, если его нет в окружении."""
        monkeypatch.setenv("VAULT_ENABLED", "true")
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.setenv("VAULT_TOKEN", "test-token")
        monkeypatch.setenv("VAULT_SECRET_PATH", "secret/data/test")

        source = VaultConfigSettingsSource(_ChainSettings)
        data = source._load_data()
        assert data == {"probe_value": "from-vault"}
        assert _VAULT_CREATED[0][0] == cl._vault_yaml_config()["addr"]


class TestVaultSecretCache:
    """Секрет Vault читается один раз на путь (ADR-0372)."""

    def test_secret_is_read_once(
        self, monkeypatch: pytest.MonkeyPatch, fake_vault: list[str]
    ) -> None:
        """Два источника подряд → одно чтение из Vault."""
        monkeypatch.setenv("VAULT_ENABLED", "true")
        monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
        monkeypatch.setenv("VAULT_TOKEN", "test-token")
        monkeypatch.setenv("VAULT_SECRET_PATH", "secret/data/test")

        first = VaultConfigSettingsSource(_ChainSettings)._load_data()
        second = VaultConfigSettingsSource(_ChainSettings)._load_data()

        assert first == second == {"probe_value": "from-vault"}
        assert len(fake_vault) == 1, (
            "Секрет Vault должен читаться один раз (кэш по пути)"
        )

    def test_cache_can_be_cleared(self) -> None:
        """``clear_vault_cache()`` сбрасывает кэш секретов."""
        cl._VAULT_SECRET_CACHE["addr", "path"] = {"x": 1}
        cl.clear_vault_cache()
        assert cl._VAULT_SECRET_CACHE == {}


class TestYamlCacheInvalidation:
    """YAML-кэш инвалидируется по изменению файла (ADR-0372)."""

    def test_cache_is_invalidated_on_change(self, tmp_path: Path) -> None:
        """Изменённый YAML перечитывается (иначе hot-reload не работает)."""
        global _PROFILES_DIR

        profile = get_active_profile().value
        (tmp_path / "base.yml").write_text("probe:\n  value: 0\n")
        _write_profile(tmp_path, profile, 1)
        _PROFILES_DIR = tmp_path
        clear_yaml_cache()

        assert _ProbeSettings().value == 1

        path = _write_profile(tmp_path, profile, 42)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns + 10**9, stat.st_mtime_ns + 10**9))
        clear_yaml_cache()

        assert _ProbeSettings().value == 42

    def test_mtime_change_invalidates_cache(self, tmp_path: Path) -> None:
        """Кэш сам инвалидируется при изменении mtime файла."""
        profile = get_active_profile().value
        (tmp_path / "base.yml").write_text("probe:\n  value: 0\n")
        path = _write_profile(tmp_path, profile, 7)

        clear_yaml_cache()
        assert cl._read_overlay_yaml_cached(tmp_path, profile)["probe"]["value"] == 7

        _write_profile(tmp_path, profile, 8)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns + 10**9, stat.st_mtime_ns + 10**9))

        assert cl._read_overlay_yaml_cached(tmp_path, profile)["probe"]["value"] == 8

    def test_clear_yaml_cache_is_public(self) -> None:
        """``clear_yaml_cache()`` — публичный API для hot-reload."""
        assert callable(clear_yaml_cache)
        cl._BASE_YAML_CACHE["x"] = ((0, 0), {})
        clear_yaml_cache()
        assert cl._BASE_YAML_CACHE == {}


class TestDotEnvPriority:
    """``.env`` — низкий приоритет (ADR-0372)."""

    def test_env_file_values_do_not_shadow_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Значение из ``.env`` не перебивает YAML (YAML выше по приоритету)."""
        global _PROFILES_DIR

        profile = get_active_profile().value
        (tmp_path / "base.yml").write_text("probe:\n  value: 0\n")
        _write_profile(tmp_path, profile, 5)
        _PROFILES_DIR = tmp_path
        clear_yaml_cache()

        key = "PROBE_VALUE"
        monkeypatch.setenv(key, "999")
        cl._ENV_FILE_VALUES[key] = "999"
        try:
            assert _ProbeSettings().value == 5
        finally:
            cl._ENV_FILE_VALUES.pop(key, None)

    def test_real_env_wins_over_dotenv_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Настоящая переменная окружения приоритетнее значения из ``.env``."""
        key = "PROBE_REAL_ENV"
        monkeypatch.setenv(key, "from-env")
        cl._ENV_FILE_VALUES[key] = "from-file"
        try:
            assert key.lower() not in cl._dotenv_only_keys()
            assert cl._env_lookup(key) == "from-env"
        finally:
            cl._ENV_FILE_VALUES.pop(key, None)

    def test_dotenv_value_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Значение, совпадающее с ``.env``, считается файловым (низкий приоритет)."""
        key = "PROBE_FROM_FILE"
        monkeypatch.setenv(key, "same")
        cl._ENV_FILE_VALUES[key] = "same"
        try:
            assert key.lower() in cl._dotenv_only_keys()
            assert cl._env_lookup(key) == ""
        finally:
            cl._ENV_FILE_VALUES.pop(key, None)

    def test_no_module_level_dotenv_call(self) -> None:
        """``.env`` не читается «из ниоткуда»: в модуле нет вызова на верхнем уровне."""
        import ast

        source = Path(cl.__file__).read_text()
        tree = ast.parse(source)
        module_level_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id
            in {"load_dotenv", "load_env_file", "ensure_env_file_loaded"}
        ]
        assert not module_level_calls, (
            "Загрузка .env не должна выполняться на верхнем уровне модуля"
        )
