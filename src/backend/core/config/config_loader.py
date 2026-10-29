import os
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from src.backend.core.config.constants import consts
from src.backend.core.config.profile import get_active_profile

__all__ = (
    "BaseSettingsWithLoader",
    "clear_vault_cache",
    "clear_yaml_cache",
    "ensure_env_file_loaded",
    "env_lookup",
    "load_env_file",
    "reload_settings",
    "vault_yaml_config",
)


def _logger() -> Any:
    """Ленивый логгер (fix circular import, 2026-09-23).

    Module-level ``get_logger(__name__)`` ломал ``manage.py migrate``:
    config_loader → core.logging (lazy __getattr__) → infrastructure/logging
    → structlog_backend.configure → core.config.services (настройки логов)
    → services/cache.py → ещё инициализирующийся config_loader → ImportError.
    config_loader — корень конфиг-пакета: импорты, транзитивно требующие
    settings, в нём допустимы только внутри функций.
    """
    global _logger_instance
    if _logger_instance is None:
        from src.backend.core.logging import get_logger

        _logger_instance = get_logger(__name__)
    return _logger_instance


_logger_instance: Any = None


def _resolve_repo_root() -> Path:
    """Возвращает корень репозитория (директория с ``pyproject.toml``).

    ``consts.ROOT_DIR`` исторически указывает на ``src/`` — для конфигов
    нужен родитель (где лежит ``config_profiles/``). Поиск идёт вверх от
    текущего файла; при провале возвращается родитель ``ROOT_DIR`` как
    лучший доступный fallback.

    Sprint 39: поддержка ``GD_REPO_ROOT`` env-override для инструментов,
    запускающих тесты из поддиректории (mutmut использует ``mutants/``).
    """
    if env_root := os.environ.get("GD_REPO_ROOT"):
        return Path(env_root)
    current = Path(__file__).resolve()
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return consts.ROOT_DIR.parent


_REPO_ROOT: Path = _resolve_repo_root()


def repo_root() -> Path:
    """Публичный доступ к корню репозитория (каталог с ``pyproject.toml``).

    Единая точка истины для ограничения FS-доступа (аудит 2026-10-01,
    F-AL): ``AIFsFacade`` получает этот путь как ``allowed_read_roots``,
    поэтому читать проект можно, а ``/etc`` — нет. Учитывает
    ``GD_REPO_ROOT``-override, как и :func:`_resolve_repo_root`.

    Returns:
        Абсолютный путь к корню репозитория.
    """
    return _REPO_ROOT


_ENV_FILE_VALUES: dict[str, str] = {}
"""Содержимое ``.env`` (кэш): ``KEY -> значение`` из файла.

Нужно, чтобы отличать «переменную из ``.env``» от «настоящей переменной
окружения»: если значение в ``os.environ`` совпадает со значением из
файла — источник считается файловым (низкий приоритет), иначе —
настоящим окружением (приоритет №2). Подход устойчив к
``importlib.reload`` модуля (не зависит от накопленного состояния).
"""


def _env_case_variants() -> dict[str, set[str]]:
    """Значения ``os.environ``, сгруппированные по регистронезависимому ключу.

    ``os.environ`` на Linux регистрозависим: ``APP_FOO`` и ``app_foo`` —
    разные переменные, но pydantic схлопывает их в один ключ (последний
    побеждает). Поэтому сравнение с ``.env`` должно быть
    регистронезависимым (ADR-0376).

    Returns:
        Словарь ``ключ в нижнем регистре -> множество значений``.

    """
    variants: dict[str, set[str]] = {}
    for name, value in os.environ.items():
        variants.setdefault(name.lower(), set()).add(value)
    return variants


def _dotenv_only_keys() -> set[str]:
    """Ключи, значения которых в ``os.environ`` пришли из ``.env``.

    Ключ считается «из файла» только если НИ ОДИН его регистрозависимый
    вариант в окружении не содержит другого значения: реальное окружение
    (в т.ч. записанное в другом регистре — ``APP_FOO`` против ``app_foo``)
    приоритетнее файла. Раньше сравнение было регистрозависимым, и
    значение из ``.env`` (lowercase) перебивало реальное окружение
    (uppercase) — настройка уезжала в YAML (ADR-0376).

    Returns:
        Множество имён переменных (в нижнем регистре).

    """
    variants = _env_case_variants()
    only_from_file: set[str] = set()
    for key, value in _ENV_FILE_VALUES.items():
        if os.environ.get(key) != value:
            continue
        if any(v != value for v in variants.get(key.lower(), ())):
            continue
        only_from_file.add(key.lower())
    return only_from_file


def load_env_file(path: Path | None = None, *, override: bool = False) -> bool:
    """Явно загружает ``.env`` в ``os.environ`` (ADR-0372).

    Решение владельца (cycle 172): «в ``.env`` — только секреты».
    Поэтому ``.env`` — отдельный ИСТОЧНИК с фиксированным приоритетом
    (ниже env/Vault/Consul/YAML), а не неявная подмена окружения на
    уровне импорта модуля.

    Раньше ``load_dotenv()`` вызывался на уровне модуля — переменные из
    ``.env`` попадали в ``os.environ`` ДО сборки цепочки источников и
    поэтому перебивали и Vault, и YAML.

    Args:
        path: Путь к ``.env`` (по умолчанию — ``<repo_root>/.env``).
        override: Перезаписывать ли уже установленные переменные окружения.

    Returns:
        ``True`` — файл прочитан, ``False`` — файла нет.

    """
    from dotenv import dotenv_values

    env_path = path or (_REPO_ROOT / ".env")
    if not env_path.is_file():
        return False

    values = {
        key: value
        for key, value in dotenv_values(env_path).items()
        if value is not None
    }
    for key, value in values.items():
        if key in os.environ and not override:
            continue
        os.environ[key] = value
    _ENV_FILE_VALUES.update(values)
    return True


def ensure_env_file_loaded(path: Path | None = None) -> bool:
    """Идемпотентная загрузка ``.env`` (не более одного раза за процесс).

    Args:
        path: Путь к ``.env`` (по умолчанию — ``<repo_root>/.env``).

    Returns:
        ``True`` — ``.env`` загружен (или уже был), ``False`` — файла нет.

    """
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED:
        return True
    _ENV_FILE_LOADED = True
    return load_env_file(path)


_ENV_FILE_LOADED: bool = False
"""Флаг однократной загрузки ``.env`` (см. :func:`ensure_env_file_loaded`)."""


# v6 W5.4 — module-level cache для base + overlay yaml reads.
# Per W5.3 cProfile waterfall (commit 5d8eda56d):
# yaml.safe_load = 10.789s (77% of startup). 240 calls (17 Settings classes × 2 yamls).
# Без cache каждый Settings класс перечитывает base.yml + profile overlay.
# С cache: 2 вызова (один на файл) вместо 240.
# Per W5.4 benchmark doc (commit d066a0e64): actual measured gain = 0.37s
# (NOT 5-8s as original estimate — corrected after W5.4 benchmark).
# Per v6 §10 W5 «Lazy import применять только при доказанном выигрыше»:
# cache invalidation при смене профиля runtime → перечитываем.
#
# ADR-0372: кэш хранит СЛЕДОК ФАЙЛА ((mtime_ns, size)) — при изменении
# файла на диске запись перечитывается автоматически. Раньше кэш жил
# вечно → hot-reload подхватывал старое значение YAML.
_YamlCache = dict[str, tuple[tuple[int, int], dict[str, Any]]]

_BASE_YAML_CACHE: _YamlCache = {}
_OVERLAY_YAML_CACHE: _YamlCache = {}


def clear_yaml_cache() -> None:
    """Сбрасывает кэш прочитанных YAML-профилей.

    Вызывается из hot-reload: без сброса (и без проверки mtime) новое
    значение из ``config_profiles/*.yml`` не попадало бы в настройки.

    Returns:
        None.

    """
    _BASE_YAML_CACHE.clear()
    _OVERLAY_YAML_CACHE.clear()


def _file_stamp(path: Path) -> tuple[int, int]:
    """Возвращает признак актуальности файла: ``(mtime_ns, size)``.

    Args:
        path: Путь к файлу.

    Returns:
        Кортеж ``(mtime_ns, size)``; ``(0, 0)`` — файл недоступен.

    """
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def _read_yaml_cached(path: Path, cache: _YamlCache) -> dict[str, Any]:
    """Читает YAML с кэшем, инвалидируемым по изменению файла.

    Args:
        path: Путь к YAML-файлу.
        cache: Кэш (``path -> (stamp, data)``).

    Returns:
        Разобранное содержимое YAML (пустой dict — если файла нет).

    """
    key = path.as_posix()
    stamp = _file_stamp(path)
    cached = cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    data = _read_yaml(path)
    cache[key] = (stamp, data)
    return data


def _read_base_yaml_cached(profiles_dir: Path) -> dict[str, Any]:
    """Cache для base.yml — перечитываем только при cache miss.

    Key = profiles_dir.as_posix(). Base.yml обычно НЕ меняется runtime →
    cache валиден пока процесс живёт. При смене profile через env
    профильный overlay перечитывается (отдельный cache key).
    """
    return _read_yaml_cached(profiles_dir / "base.yml", _BASE_YAML_CACHE)


def _read_overlay_yaml_cached(profiles_dir: Path, profile_name: str) -> dict[str, Any]:
    """Cache для {profile}.yml overlay.

    Key = (profiles_dir, profile_name). При смене profile через env
    (get_active_profile() возвращает новое имя) → cache miss → перечитываем.
    """
    return _read_yaml_cached(profiles_dir / f"{profile_name}.yml", _OVERLAY_YAML_CACHE)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно сливает ``overlay`` поверх ``base``, не мутируя исходники."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    """Безопасное чтение YAML-файла. Отсутствие файла → пустой dict."""
    from yaml import safe_load

    try:
        with open(path) as fh:
            data = safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise RuntimeError(f"YAML loading error ({path}): {exc}") from exc
    return data if isinstance(data, dict) else {}


def _profiles_dir() -> Path:
    """Каталог с YAML-профилями (``config_profiles/``)."""
    return _REPO_ROOT / "config_profiles"


def _merged_profile_yaml() -> dict[str, Any]:
    """Слияние ``base.yml`` + overlay активного профиля (с кэшем).

    Returns:
        Итоговый словарь конфигурации.

    """
    profiles_dir = _profiles_dir()
    return _deep_merge(
        _read_base_yaml_cached(profiles_dir),
        _read_overlay_yaml_cached(profiles_dir, get_active_profile().value),
    )


def vault_yaml_config() -> dict[str, Any]:
    """Секция ``vault`` из YAML-профиля (с кэшем чтения).

    ADR-0372: ``VAULT_ADDR``/``VAULT_SECRET_PATH`` — не секреты, они
    задаются в ``config_profiles/*.yml::vault`` (см. ``.env.example``).

    Returns:
        Словарь настроек Vault из YAML (пустой — если секции нет).

    """
    vault_cfg = _merged_profile_yaml().get("vault") or {}
    return vault_cfg if isinstance(vault_cfg, dict) else {}


_vault_yaml_config = vault_yaml_config
"""Back-compat alias (историческое приватное имя)."""


def env_lookup(name: str) -> str:
    """Значение переменной окружения, заданное НЕ через ``.env``.

    ADR-0372: значения из ``.env`` не должны перебивать YAML/Vault —
    они приходят отдельным источником (dotenv) с низким приоритетом.
    Поэтому для «настоящих» переменных окружения используется этот
    lookup, а ``.env``-значения — как последний fallback.

    Args:
        name: Имя переменной окружения.

    Returns:
        Значение переменной или пустая строка.

    """
    if name.lower() in _dotenv_only_keys():
        return ""
    return os.environ.get(name, "")


_env_lookup = env_lookup
"""Back-compat alias (историческое приватное имя)."""


def _is_vault_enabled() -> bool:
    """Решает, активировать ли VaultConfigSettingsSource.

    Приоритет: env-override (``VAULT_ENABLED``) → YAML (``vault.enabled``)
    → значение по умолчанию ``True``. Helper не инстанциирует
    ``VaultSettings`` — это вызвало бы рекурсию через
    ``customise_sources``; YAML читается напрямую (через кэш — ADR-0372).
    """
    from os import getenv

    raw = getenv("VAULT_ENABLED")
    if raw is not None and raw.strip():
        return raw.strip().lower() not in {"0", "false", "no"}
    vault_cfg = _vault_yaml_config()
    return bool(vault_cfg.get("enabled", True))


class FilteredSettingsSource(PydanticBaseSettingsSource, ABC):
    """Abstract base class for filtered settings sources.

    ``fail_closed`` (ADR-0372) разделяет два принципа загрузки:

    * ``True`` (YAML) — ошибка чтения ПРОБРАСЫВАЕТСЯ: отсутствие
      ``config_profiles/{profile}.yml`` не должно молча откатывать
      приложение на дефолты;
    * ``False`` (Vault/Consul) — fail-soft: внешний источник недоступен →
      источник возвращает ``{}``, конфигурация собирается из остальных.
    """

    fail_closed: ClassVar[bool] = False

    flat_payload: ClassVar[bool] = False
    """Источник отдаёт ПЛОСКИЙ payload (ключ = имя поля модели).

    ADR-0376: Vault-секрет и Consul-KV Runtime-config — плоские словари
    (``{field_name: value}``), а не секции ``payload[yaml_group]``. Раньше
    фильтр требовал вложенности → данные из Vault/Consul отбрасывались
    как «неизвестные» и НЕ применялись. Для плоских источников фильтр
    принимает и вложенный вид (``{yaml_group: {...}}``) — оба формата
    поддержаны.
    """

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        self.yaml_group = settings_cls.yaml_group  # type: ignore
        self.model_fields = settings_cls.model_fields.keys()
        # Wave 13 Q16: флаг «уже предупреждали про неизвестные ключи»
        # (одно WARNING на источник — без log spam при повторных вызовах).
        self._unknown_keys_warned = False

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        """Return default empty value for a field (placeholder for subclasses)."""
        return (None, field_name, False)

    def __call__(self) -> dict[str, Any]:
        try:
            raw_data = self._load_data()

            return self._filter_data(raw_data)
        except Exception as exc:
            if self.fail_closed:
                _logger().error(
                    "Ошибка в %s (fail-closed): %s", self.__class__.__name__, exc
                )
                raise
            self._handle_error(exc)
            return {}

    def _filter_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Filter data using model fields.

        Неизвестные ключи отбрасываются, но НЕ молча (Wave 13 Q16):
        опечатка в имени YAML-ключа иначе приводит к тихой потере
        настройки. ``extra="forbid"`` в моделях на YAML не действует —
        фильтр отбрасывает ключ ДО валидации pydantic, поэтому опечатку
        ловит только warning в логе (см. :meth:`_warn_unknown_keys`).

        ADR-0376: для плоских источников (Vault/Consul) warning о
        неизвестных ключах выдаётся только когда payload относится к
        этой модели (хотя бы одно поле совпало) — иначе один общий
        секрет давал бы 40+ одинаковых WARNING'ов на все Settings-классы.
        """
        group_data = self._select_group_data(raw_data)

        filtered = {k: v for k, v in group_data.items() if k in self.model_fields}
        if not self.flat_payload or filtered:
            self._warn_unknown_keys(group_data)
        return filtered

    def _select_group_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Выбирает секцию данных источника.

        Для YAML-источника — секция ``raw_data[yaml_group]``. Для плоских
        источников (Vault/Consul, ADR-0376) — сам payload, если вложенной
        секции нет; вложенный формат тоже поддерживается.

        Args:
            raw_data: Сырые данные источника.

        Returns:
            Словарь с данными, пригодными для фильтрации по полям модели.

        """
        if not self.yaml_group:
            return raw_data
        if self.yaml_group in raw_data:
            nested = raw_data[self.yaml_group]
            if isinstance(nested, dict):
                return nested
            if self.flat_payload:
                return raw_data
            return nested
        if self.flat_payload:
            return raw_data
        return {}

    def _warn_unknown_keys(self, group_data: dict[str, Any]) -> None:
        """Логирует отброшенные неизвестные ключи (один WARNING на источник).

        Рантайм-fail-loud сознательно НЕ вводится: падение старта из-за
        лишнего ключа опаснее потери настройки. Вместо этого долг
        фиксируется гейтом ``tools/config_audit.py`` (baseline + CI).

        Args:
            group_data: Данные секции источника (до фильтрации).

        """
        if self._unknown_keys_warned:
            return
        unknown = sorted(k for k in group_data if k not in self.model_fields)
        if not unknown:
            return
        self._unknown_keys_warned = True
        _logger().warning(
            "Неизвестные ключи конфигурации отброшены (yaml_group=%s): %s. "
            "Значения НЕ применяются — проверьте имена ключей в YAML.",
            self.yaml_group or "<root>",
            ", ".join(unknown),
        )

    @abstractmethod
    def _load_data(self) -> dict[str, Any]:
        """Load raw data from source."""

    def _handle_error(self, error: Exception) -> None:
        """Handle errors during data loading."""
        # Cycle 72 L2: lazy import hoisted to module-level (no circular import).
        _logger().error("Ошибка в %s: %s", self.__class__.__name__, error)


class YamlConfigSettingsLoader(FilteredSettingsSource):
    """YAML config loader: ``base.yml`` + overlay активного профиля.

    Структура ``config_profiles/``:
        * ``base.yml`` — общие нечувствительные настройки, не зависящие
          от окружения (timeouts, retries, pool_size, encoding и т.д.);
        * ``{profile}.yml`` — env-specific overrides (хосты, порты,
          enabled-флаги для конкретного окружения).

    Финальная конфигурация = ``_deep_merge(base, profile)``. Оба файла
    обязательны — отсутствие любого из них приводит к фатальной ошибке
    (``fail_closed`` — источник пробрасывает исключение, а не откатывается
    на дефолты; ADR-0372).
    Секреты приходят из env / Vault; в YAML их быть не должно (см.
    ``tools/config_audit.py`` и ``.env.example``).
    """

    fail_closed: ClassVar[bool] = True

    def __init__(
        self, settings_cls: type[BaseSettings], profiles_dir: Path | None = None
    ):
        super().__init__(settings_cls)
        self.profiles_dir = profiles_dir or _REPO_ROOT / "config_profiles"

    def _load_data(self) -> dict[str, Any]:
        """Загружает ``base.yml`` и накладывает overlay активного профиля.

        Оба файла обязательны (FileNotFound → RuntimeError); ``_read_yaml``
        здесь оборачивается, чтобы конвертировать отсутствие файла в
        фатальную ошибку (в loader-контексте отсутствие конфига —
        нерабочая ситуация, в отличие от ``_is_vault_enabled``, который
        допускает мягкий fallback).
        """
        base_path = self.profiles_dir / "base.yml"
        profile = get_active_profile()
        overlay_path = self.profiles_dir / f"{profile.value}.yml"
        for path in (base_path, overlay_path):
            if not path.is_file():
                raise RuntimeError(
                    f"Config not found: {path}. "
                    "Ожидается base.yml + {profile}.yml в config_profiles/."
                )
        # v6 W5.4 — use cached readers (per W5.3 cProfile waterfall):
        # 240 yaml.safe_load calls → 2 (один на base, один на overlay).
        return _deep_merge(
            _read_base_yaml_cached(self.profiles_dir),
            _read_overlay_yaml_cached(self.profiles_dir, profile.value),
        )


_VAULT_UNREACHABLE: bool = False
"""Module-level флаг: Vault уже признан недоступным в текущем процессе.

Используется ``VaultConfigSettingsSource`` для подавления повторных
warning-сообщений: при загрузке N Settings-классов попытка достучаться до
Vault выполняется N раз, поэтому 30+ одинаковых строк забивают логи. После
первой неудачи флаг ставится в ``True`` и источник тихо возвращает ``{}``.
"""


_VAULT_CACHE_TTL_SECONDS: float = 300.0
"""TTL кэша секретов Vault (секунды).

ADR-0376: кэш без TTL не видел ротацию секрета — значение в настройках
оставалось старым до рестарта. 300 с — тот же интервал, что и у
``VaultSecretRefresher`` (background refresh).
"""


_VAULT_SECRET_CACHE: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
"""Кэш секретов Vault: ``(addr, secret_path) -> (payload, expires_at)``.

ADR-0372: без кэша Vault читался 46 раз на старте (92 HTTP-запроса:
``is_authenticated`` + ``read_secret_version`` на каждый Settings-класс).
Секрет одинаков для всех классов → достаточно одного чтения. Кэш
сбрасывается в :func:`clear_vault_cache` (hot-reload).

ADR-0376: добавлен TTL (:data:`_VAULT_CACHE_TTL_SECONDS`) — истёкшая
запись перечитывается, поэтому ротация секрета видна без рестарта.
"""


def _vault_cache_get(cache_key: tuple[str, str]) -> dict[str, Any] | None:
    """Возвращает payload из кэша секретов, если запись не истекла.

    Args:
        cache_key: Ключ кэша ``(addr, secret_path)``.

    Returns:
        Payload секрета или ``None`` (нет записи / истекла).

    """
    entry = _VAULT_SECRET_CACHE.get(cache_key)
    if entry is None:
        return None
    payload, expires_at = entry
    if expires_at <= time.monotonic():
        _VAULT_SECRET_CACHE.pop(cache_key, None)
        return None
    return payload


def clear_vault_cache() -> None:
    """Сбрасывает кэш секретов Vault и флаг недоступности (hot-reload).

    ADR-0376: вместе с кэшем сбрасывается ``_VAULT_UNREACHABLE`` — иначе
    флаг оставался бы липким навсегда, и после «подъёма» Vault секреты
    не приходили бы до рестарта процесса.

    Returns:
        None.

    """
    global _VAULT_UNREACHABLE

    _VAULT_SECRET_CACHE.clear()
    _VAULT_UNREACHABLE = False


_HVAC_AVAILABLE: bool | None = None
"""Cached result of ``_hvac_module_available()``. None = not checked yet.

Cycle 158+ fix: pre-check ``hvac`` importability до ``from hvac import Client``.
Если missing в venv → silent skip (no per-class log spam).
"""


def _hvac_module_available() -> bool:
    """Check if ``hvac`` Python module is importable.

    Cycle 158+ fix (`priority B из STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23`):
    ``hvac`` optional dependency — если missing в venv, VaultConfigSettingsSource
    должен short-circuit silently (без log spam). 17+ Settings-классов ×
    1 Vault attempt each = log flood + per-class hvac import attempt overhead.

    :returns: True если ``hvac`` importable, иначе False (cached result).
    """
    import importlib.util

    result = importlib.util.find_spec("hvac") is not None
    # Кэшируем в module-level global (как ``_VAULT_UNREACHABLE``).
    # ``global`` declaration должна быть ПЕРЕД любым use в функции, но
    # module variable должна быть определена раньше функции (иначе Python
    # считает assignment as local).
    global _HVAC_AVAILABLE
    _HVAC_AVAILABLE = result
    return result


class VaultConfigSettingsSource(FilteredSettingsSource):
    """Vault config loader with filtering.

    Активируется только если включён через YAML (``vault.enabled: true``)
    или env-override (``VAULT_ENABLED``), и в окружении заданы все три
    переменных ``VAULT_ADDR``/``VAULT_TOKEN``/``VAULT_SECRET_PATH``. На
    профиле ``dev_light`` поставляется overlay ``vault.enabled: false``,
    что отключает источник без необходимости трогать env.

    ADR-0372: ``VAULT_ADDR``/``VAULT_SECRET_PATH`` — не секреты, они
    задаются в ``config_profiles/*.yml::vault`` (см. ``.env.example``);
    приоритет: реальное окружение → YAML → ``.env``. ``VAULT_TOKEN`` —
    секрет: реальное окружение → ``.env`` (в YAML секретов нет).

    Если Vault недоступен (connection refused, таймаут, auth-fail) —
    источник один раз пишет warning и затем тихо возвращает ``{}`` для
    остальных Settings-классов (см. ``_VAULT_UNREACHABLE``).

    ADR-0376: payload секрета — ПЛОСКИЙ (``{field_name: value}``), он
    применяется к полям модели напрямую; вложенный формат
    (``{yaml_group: {...}}``) тоже поддерживается.
    """

    flat_payload: ClassVar[bool] = True

    def _load_data(self) -> dict[str, Any]:
        """Load data from Vault."""
        global _VAULT_UNREACHABLE

        if not _is_vault_enabled():
            return {}

        if _VAULT_UNREACHABLE:
            return {}

        # Cycle 158+ fix: skip Vault если hvac модуль отсутствует.
        # Раньше пытались ``from hvac import Client`` — ImportError поднимался,
        # ловился ``except Exception`` в ``__call__``, error логировался per-class
        # (17+ дубликатов при cold import 17 Settings-классов).
        # Теперь: cached check + early return = silent degradation.
        if _HVAC_AVAILABLE is False or (
            _HVAC_AVAILABLE is None and not _hvac_module_available()
        ):
            _VAULT_UNREACHABLE = True
            return {}

        yaml_cfg = vault_yaml_config()
        vault_addr = (
            env_lookup("VAULT_ADDR")
            or yaml_cfg.get("addr")
            or os.environ.get("VAULT_ADDR", "")
        )
        vault_token = env_lookup("VAULT_TOKEN") or os.environ.get("VAULT_TOKEN", "")
        vault_secret_path = (
            env_lookup("VAULT_SECRET_PATH")
            or yaml_cfg.get("secret_path")
            or os.environ.get("VAULT_SECRET_PATH", "")
        )

        if not all([vault_addr, vault_token, vault_secret_path]):
            return {}

        cache_key = (vault_addr, vault_secret_path)
        cached = _vault_cache_get(cache_key)
        if cached is not None:
            return cached

        from hvac import Client
        from hvac.exceptions import VaultError
        from requests.exceptions import RequestException

        try:
            client = Client(url=vault_addr, token=vault_token)
            if not client.is_authenticated():
                _VAULT_UNREACHABLE = True
                self._log_vault_unreachable("authentication failed")
                return {}

            response = client.secrets.kv.v2.read_secret_version(path=vault_secret_path)
            payload = response.get("data", {}).get("data", {})
            _VAULT_SECRET_CACHE[cache_key] = (
                payload,
                time.monotonic() + _VAULT_CACHE_TTL_SECONDS,
            )
            return payload
        except (RequestException, VaultError) as exc:
            _VAULT_UNREACHABLE = True
            self._log_vault_unreachable(str(exc) or type(exc).__name__)
            return {}
        except Exception as exc:
            raise RuntimeError(f"Vault error: {exc!s}") from exc

    @staticmethod
    def _log_vault_unreachable(detail: str) -> None:
        """Один warning на процесс при недоступности Vault."""
        # Cycle 72 L2: lazy import hoisted to module-level.
        _logger().warning(
            "Vault недоступен (%s) — secrets-источник пропущен. "
            "Установите vault.enabled=false или поднимите Vault, "
            "чтобы убрать это сообщение.",
            detail,
        )


# S165 W7: Consul KV source для non-secret runtime-config (Rule 7 hot-reload)


def _is_consul_enabled() -> bool:
    """Решить, активировать ли ConsulConfigSettingsSource.

    Приоритет: env-override (``CONSUL_ENABLED``) → default ``False``
    (opt-in для production, default-OFF на dev_light).
    """
    from os import getenv

    raw = getenv("CONSUL_ENABLED")
    if raw is not None and raw.strip():
        return raw.strip().lower() not in {"0", "false", "no"}
    return False


def _parse_consul_addr(consul_addr: str) -> tuple[str, int, str]:
    """Разбирает ``CONSUL_ADDR`` в ``(host, port, scheme)``.

    ADR-0372: раньше порт терялся (``split(":")[0]``) — ``http://consul:9500``
    превращался в ``consul`` + дефолтный 8500, т.е. Consul KV читался не с
    того сервера.

    Args:
        consul_addr: Значение ``CONSUL_ADDR`` (``host``, ``host:port`` или URL).

    Returns:
        Кортеж ``(host, port, scheme)``.

    """
    from urllib.parse import urlsplit

    raw = consul_addr.strip()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or "localhost"
    port = parsed.port or 8500
    scheme = parsed.scheme or "http"
    return host, port, scheme


class ConsulConfigSettingsSource(FilteredSettingsSource):
    """Consul KV source для hot-reload runtime-config (Rule 7).

    Загружает keys с префиксом ``runtime/{yaml_group}/``.
    На prod: opt-in через ``CONSUL_ENABLED=true`` + ``CONSUL_ADDR``.

    ADR-0372: источник стоит **выше** YAML — иначе «runtime-config из
    Consul KV» не работал: YAML перекрывал значения из Consul.
    Недоступность Consul — fail-soft (возвращает ``{}``).

    ADR-0376: значения из Consul — ПЛОСКИЙ payload ``{field_name: value}``
    (ключи KV под префиксом ``runtime/{yaml_group}/``). Раньше фильтр
    требовал вложенности ``payload[yaml_group]`` → значения из Consul
    отбрасывались и YAML оставался единственным источником.
    """

    flat_payload: ClassVar[bool] = True

    def _load_data(self) -> dict[str, Any]:
        """Load data from Consul KV. Fail-silent if unreachable."""
        if not _is_consul_enabled():
            return {}

        from os import getenv

        consul_addr = getenv("CONSUL_ADDR")
        if not consul_addr:
            return {}

        prefix = f"runtime/{self.yaml_group}/"
        try:
            from src.backend.core.config.consul_config import ConsulConfigStore

            host, port, scheme = _parse_consul_addr(consul_addr)
            store = ConsulConfigStore(
                host=host,
                port=port,
                scheme=scheme,
                token=getenv("CONSUL_TOKEN") or None,
            )
            data: dict[str, Any] = {}
            for key, value in store.items(prefix):
                field_name = key.removeprefix(prefix)
                data[field_name] = value
            return data
        except (AttributeError, TypeError, ValueError, KeyError) as items_exc:
            # cycle-9/D-AUDIT-982: narrow exceptions + observability.
            # AttributeError — store.items API change, TypeError — wrong
            # store type, ValueError — invalid prefix, KeyError — missing
            # expected key. Bare `except Exception` маскировал unrelated
            # runtime errors.
            _logger().debug(
                "config_loader.prefix_items_failed",
                extra={"prefix": prefix, "error": str(items_exc)},
            )
            return {}


def _env_vars_for_source(
    *, ignore_empty: bool, parse_none_str: str | None
) -> dict[str, str | None]:
    """Значения окружения для env-source (регистронезависимо).

    ADR-0376: pydantic схлопывает регистрозависимые варианты в один ключ
    (последний побеждает) — из-за этого значение из ``.env`` (обычно
    lowercase) перебивало реальное окружение (обычно uppercase), и
    настройка уезжала в YAML. Здесь для каждого логического ключа
    выбирается вариант, значение которого ОТЛИЧАЕТСЯ от значения ``.env``
    (реальное окружение приоритетнее файла). Если такого варианта нет —
    ключ «из файла» и в env-source не попадает: его отдаёт dotenv-source
    ниже YAML.

    Args:
        ignore_empty: Игнорировать пустые значения (опция pydantic).
        parse_none_str: Значение, трактуемое как ``None`` (опция pydantic).

    Returns:
        Словарь ``ключ в нижнем регистре -> значение`` для env-source.

    """
    file_values = {key.lower(): value for key, value in _ENV_FILE_VALUES.items()}
    variants: dict[str, list[str]] = {}
    for name, value in os.environ.items():
        if ignore_empty and value == "":
            continue
        variants.setdefault(name.lower(), []).append(value)

    env_vars: dict[str, str | None] = {}
    for key, values in variants.items():
        file_value = file_values.get(key)
        if file_value is None:
            env_vars[key] = values[-1]
            continue
        real_values = [value for value in values if value != file_value]
        if not real_values:
            continue  # значение только из ``.env`` → его отдаёт dotenv-source
        chosen = real_values[-1]
        env_vars[key] = None if parse_none_str is not None and chosen == parse_none_str else chosen
    return env_vars


class DotEnvAwareEnvSource(EnvSettingsSource):
    """Env-source, игнорирующий переменные, подставленные из ``.env``.

    ADR-0372: без этого ``.env`` фактически оставался бы приоритетом №2
    (env) и перебивал Vault/YAML. Значения ``.env`` должны приходить
    отдельным источником (dotenv) — с приоритетом ниже env/Vault/Consul.

    Переменные, которые были в ``os.environ`` ДО загрузки ``.env``,
    остаются видимыми: реальное окружение приоритетнее файла.

    ADR-0376: сравнение регистронезависимое — ``os.environ`` на Linux
    регистрозависим, поэтому ``APP_FOO`` и ``app_foo`` — разные
    переменные; pydantic схлопывает их в один ключ (последний побеждает),
    и значение из ``.env`` (lowercase) перебивало реальное окружение
    (uppercase). См. :func:`_env_vars_for_source`.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        if not self.case_sensitive:
            self.env_vars = _env_vars_for_source(
                ignore_empty=self.env_ignore_empty,
                parse_none_str=self.env_parse_none_str,
            )
            return
        dotenv_keys = _dotenv_only_keys()
        if dotenv_keys:
            self.env_vars = {
                key: value
                for key, value in self.env_vars.items()
                if key.lower() not in dotenv_keys
            }


class BaseSettingsWithLoader(BaseSettings):
    """Base class for configuration models with multi-source loading support.

    Combines configuration from:
    - Initialization parameters
    - Environment variables
    - Vault secrets
    - Consul KV runtime-config
    - .env file (secrets only — см. ADR-0372)
    - YAML configuration files
    - File-based secrets

    Subclasses must define:
    - `yaml_group`: Name of the YAML configuration section to use
    - `model_config.env_prefix`: Environment variables prefix for settings group
    """

    yaml_group: ClassVar[str | None] = None
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="forbid",
        env_file=str(_REPO_ROOT / ".env"),
        # Только поля модели: без этого dotenv-source отдаёт лишние ключи
        # из .env как "extra" → ValidationError при extra="forbid".
        dotenv_filtering="only_existing",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize configuration sources and their priority order.

        Priority order (highest first, ADR-0372):

        1. Initialization parameters (``Settings(...)``)
        2. Environment variables (реальное окружение процесса)
        3. Vault secrets (``vault.enabled: true``)
        4. Consul KV runtime-config (``CONSUL_ENABLED=true``)
        5. YAML configuration (``base.yml`` + overlay профиля)
        6. .env file (только секреты — см. ``.env.example``)
        7. File-based secrets

        ADR-0372:
        * Consul поднят ВЫШЕ YAML — раньше он стоял после YAML и
          «runtime-config из Consul KV» молча перекрывался YAML-значениями;
        * значения ``.env`` вынесены из env-source в отдельный источник
          (dotenv) и опущены НИЖЕ YAML: файл не перебивает YAML/Vault,
          а заполняет только то, чего больше нигде нет (то есть секреты).
        """
        if not cls.yaml_group:
            raise ValueError("Subclasses must define `yaml_group` class variable")

        # ADR-0372: явная точка загрузки ``.env`` — вход в цепочку
        # источников (не импорт модуля и не sitecustomize). Значения файла
        # попадают в настройки отдельным источником (dotenv, приоритет
        # ниже YAML), а в ``os.environ`` — только чтобы процесс видел
        # секреты (feature-флаги, прямые читатели ``os.environ``).
        ensure_env_file_loaded()

        return (
            init_settings,
            DotEnvAwareEnvSource(settings_cls),
            VaultConfigSettingsSource(settings_cls),
            ConsulConfigSettingsSource(settings_cls),  # D-AUDIT-A12-02 fix (cycle 1)
            YamlConfigSettingsLoader(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


def _apply_in_place(target: Any, source: Any) -> None:
    """Копирует значения ``source`` в уже существующий объект ``target``.

    Нужно для hot-reload: потребители держат ссылки на модульные
    синглтоны (``app_base_settings`` и т.п.), поэтому настройки обновляются
    **in-place** — ссылки остаются валидными, значения — новыми.

    Args:
        target: Объект-получатель (уже существующий экземпляр модели).
        source: Новый валидный экземпляр той же модели.

    Returns:
        None.

    """
    target.__dict__.clear()
    target.__dict__.update(source.__dict__)
    target.__pydantic_fields_set__.clear()
    target.__pydantic_fields_set__.update(source.__pydantic_fields_set__)
    source_extra = getattr(source, "__pydantic_extra__", None)
    if source_extra:
        if target.__pydantic_extra__ is None:
            target.__pydantic_extra__ = {}
        target.__pydantic_extra__.clear()
        target.__pydantic_extra__.update(source_extra)


def _iter_settings_singletons() -> Iterator[tuple[str, str, Any]]:
    """Перебирает модульные синглтоны настроек пакета ``core.config``.

    ADR-0372: настройки замораживались на импорте — 40+ модульных
    экземпляров. Чтобы hot-reload обновлял их все, обходим уже
    импортированные модули пакета и собираем объекты-настройки.

    Yields:
        Кортежи ``(module_name, attr_name, instance)``.

    """
    prefix = f"{__name__.rsplit('.', 1)[0]}."
    for module_name, module in list(sys.modules.items()):
        if module is None or not module_name.startswith(prefix):
            continue
        for attr_name, value in list(vars(module).items()):
            if isinstance(value, BaseSettings):
                yield module_name, attr_name, value


def reload_settings(root: BaseSettings) -> dict[str, Any]:
    """Перечитывает конфигурацию из всех источников и обновляет настройки.

    Последовательность (ADR-0372):

    1. сбрасываются кэши YAML и секретов Vault, а также флаг
       «Vault недоступен» (ADR-0376);
    2. для каждой вложенной модели корневого ``Settings`` и каждого
       модульного синглтона пакета ``core.config`` создаётся НОВЫЙ
       экземпляр (перечитывание источников);
    3. значения нового экземпляра переносятся в существующий объект
       **in-place** — ссылки потребителей не ломаются.

    Ошибка отдельной модели не роняет весь reload: она попадает в
    ``failed``, а прежние значения сохраняются.

    Args:
        root: Корневой объект настроек (обычно ``settings``).

    Returns:
        Отчёт ``{"reloaded": [...], "failed": [...]}``.

    """
    global _VAULT_UNREACHABLE

    clear_yaml_cache()
    clear_vault_cache()
    # ADR-0376: флаг «Vault недоступен» не должен пережить reload —
    # иначе после подъёма Vault секреты не придут до рестарта.
    _VAULT_UNREACHABLE = False

    targets: list[tuple[str, Any]] = []
    for field_name in type(root).model_fields:
        value = getattr(root, field_name, None)
        if isinstance(value, BaseSettings):
            targets.append((field_name, value))
    for module_name, attr_name, value in _iter_settings_singletons():
        targets.append((f"{module_name}.{attr_name}", value))

    reloaded: list[str] = []
    failed: list[dict[str, str]] = []
    seen: set[int] = set()
    for label, target in targets:
        if target is root or id(target) in seen:
            continue
        seen.add(id(target))
        try:
            fresh = type(target)()
        except Exception as exc:
            _logger().error("Не удалось перезагрузить настройки %s: %s", label, exc)
            failed.append({"name": label, "error": str(exc)})
            continue
        _apply_in_place(target, fresh)
        reloaded.append(label)

    _logger().info(
        "Настройки перезагружены: %d обновлено, %d с ошибками",
        len(reloaded),
        len(failed),
    )
    return {"reloaded": reloaded, "failed": failed}
