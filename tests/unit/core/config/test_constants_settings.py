"""ЧАСТЬ C — константы runtime-кода как конфигурация (ADR-0375, wave 14).

До этой волны значения ``consts`` (retry/circuit-breaker/интервалы) жили
только в коде: изменить их можно было лишь релизом. Теперь они описаны
в секции ``constants`` файла ``config_profiles/base.yml``.

Контракт:

* дефолты модели ``ConstantsSettings`` == текущие значения ``consts``
  (подключение YAML не меняет поведение);
* после загрузки настроек значения применяются к синглтону ``consts``
  (мутация инстанса — потребители ``consts.X`` видят новое значение);
* hot-reload: ``Settings.reload()`` пересобирает модульный синглтон →
  значения констант переприменяются → правка YAML обновляет константы
  в рантайме;
* секретов в группе нет.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_settings import BaseSettings

from src.backend.core.config import config_loader as cl
from src.backend.core.config.constants import Constants, consts
from src.backend.core.config.constants_settings import (
    FIELD_TO_CONSTANT,
    ConstantsSettings,
    apply_constants,
    constants_settings,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE_YML = REPO_ROOT / "config_profiles" / "base.yml"

#: Каталоги, в которых ищем потребителей констант.
CONSUMER_ROOTS: tuple[Path, ...] = (REPO_ROOT / "src", REPO_ROOT / "extensions")

#: Файлы-определения: в них имя константы встречается как объявление,
#: а не как использование (``consts.X``).
DEFINITION_FILES: frozenset[Path] = frozenset(
    {
        REPO_ROOT / "src" / "backend" / "core" / "config" / "constants.py",
        REPO_ROOT / "src" / "backend" / "core" / "config" / "_resilience_consts.py",
        REPO_ROOT / "src" / "backend" / "core" / "config" / "constants_settings.py",
    }
)


def _constant_consumers() -> set[str]:
    """Имена констант, которые реально читаются кодом (``consts.<ИМЯ>``).

    Returns:
        Множество имён констант с хотя бы одним использованием.

    """
    consumers: set[str] = set()
    for root in CONSUMER_ROOTS:
        for path in root.rglob("*.py"):
            if path in DEFINITION_FILES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:  # pragma: no cover — нечитаемый файл
                continue
            consumers.update(re.findall(r"\bconsts\.([A-Z][A-Z0-9_]+)\b", text))
    return consumers


@pytest.fixture(autouse=True)
def _restore_consts() -> Any:
    """Восстанавливает значения ``consts`` после каждого теста."""
    snapshot = {name: getattr(consts, name) for name in FIELD_TO_CONSTANT.values()}
    yield
    for name, value in snapshot.items():
        setattr(consts, name, value)


def _base_section() -> dict[str, Any]:
    """Секция ``constants`` из ``config_profiles/base.yml``.

    Returns:
        Разобранный mapping (пустой dict, если секции нет).
    """
    with open(BASE_YML) as fh:
        data = yaml.safe_load(fh) or {}
    section = data.get("constants") or {}
    return section if isinstance(section, dict) else {}


class _ConstantsRoot(BaseSettings):
    """Корень-агрегатор для проверки ``reload_settings`` (без глобальных сессий)."""

    constants: ConstantsSettings


class TestDefaultsMatchCode:
    """Дефолты модели == значения констант в коде (поведение не меняется)."""

    def test_model_defaults_equal_dataclass_defaults(self) -> None:
        """Каждое поле модели == дефолт соответствующего поля ``Constants``."""
        for field_name, constant_name in FIELD_TO_CONSTANT.items():
            model_default = ConstantsSettings.model_fields[field_name].default
            code_default = Constants.__dataclass_fields__[constant_name].default
            assert model_default == code_default, (
                f"{field_name}: дефолт модели {model_default!r} != "
                f"кодовый дефолт {code_default!r}"
            )

    def test_model_defaults_equal_runtime_values(self) -> None:
        """Дефолты модели == текущие значения синглтона ``consts``."""
        for field_name, constant_name in FIELD_TO_CONSTANT.items():
            assert ConstantsSettings.model_fields[field_name].default == getattr(
                consts, constant_name
            ), f"{field_name} != consts.{constant_name}"

    def test_base_yml_has_constants_section(self) -> None:
        """В ``base.yml`` объявлена секция ``constants``."""
        assert _base_section(), "в config_profiles/base.yml нет секции constants"

    def test_base_yml_values_equal_code_defaults(self) -> None:
        """Значения YAML == кодовым дефолтам (подключение YAML не меняет поведение)."""
        section = _base_section()
        assert set(section) == set(FIELD_TO_CONSTANT), (
            f"секция constants должна описывать ровно {sorted(FIELD_TO_CONSTANT)}, "
            f"а не {sorted(section)}"
        )
        for field_name, constant_name in FIELD_TO_CONSTANT.items():
            code_default = Constants.__dataclass_fields__[constant_name].default
            assert section[field_name] == code_default, (
                f"constants.{field_name}={section[field_name]!r} != "
                f"кодовый дефолт {code_default!r}"
            )

    def test_no_secrets_in_constants_section(self) -> None:
        """В секции ``constants`` нет секретных полей."""
        assert not [key for key in _base_section() if "secret" in key or "token" in key]

    def test_every_constants_key_has_a_consumer(self) -> None:
        """У каждого ключа секции ``constants`` есть потребитель в коде.

        Регрессия (ADR-0379): часть ключей секции ``constants`` была
        инертной — значение менялось в YAML, но никто его не читал
        (иллюзия настраиваемости). Ключ без потребителя удаляется из
        YAML и из ``FIELD_TO_CONSTANT``.
        """
        consumers = _constant_consumers()
        inert = sorted(
            constant_name
            for constant_name in FIELD_TO_CONSTANT.values()
            if constant_name not in consumers
        )
        assert inert == [], (
            "Ключи конфигурации без потребителя в коде (инертные): "
            f"{inert}. Уберите их из base.yml и FIELD_TO_CONSTANT "
            "или начните использовать."
        )


class TestApplyToSingleton:
    """Значения применяются к синглтону ``consts`` (потребители видят новое)."""

    def test_construction_applies_values(self) -> None:
        """Создание модели применяет её значения к ``consts``."""
        ConstantsSettings(initial_delay=42, max_result_attempts=9)
        assert consts.INITIAL_DELAY == 42
        assert consts.MAX_RESULT_ATTEMPTS == 9

    def test_apply_constants_updates_all_mapped_fields(self) -> None:
        """``apply_constants`` переносит все сопоставленные поля."""
        source = ConstantsSettings.model_construct(
            **dict.fromkeys(FIELD_TO_CONSTANT, 7),
        )
        apply_constants(source)
        for constant_name in FIELD_TO_CONSTANT.values():
            assert getattr(consts, constant_name) == 7

    def test_readers_see_updated_value(self) -> None:
        """Потребитель ``consts.X`` видит обновлённое значение без правки вызовов."""
        ConstantsSettings(default_cb_failure_threshold=11)
        assert consts.DEFAULT_CB_FAILURE_THRESHOLD == 11

    def test_module_singleton_matches_yaml(self) -> None:
        """Модульный синглтон загружен из YAML-профиля."""
        assert constants_settings.initial_delay == _base_section()["initial_delay"]

    def test_package_exposes_singleton(self) -> None:
        """Синглтон доступен из пакета ``core.config.base`` (иначе нет hot-reload)."""
        from src.backend.core.config import base

        assert base.constants_settings is constants_settings


class TestHotReload:
    """Hot-reload переприменяет значения констант."""

    def test_reload_applies_yaml_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Изменение YAML → reload → константы обновлены в рантайме."""
        profiles_dir = tmp_path / "config_profiles"
        profiles_dir.mkdir()
        (profiles_dir / "base.yml").write_text(
            "constants:\n  initial_delay: 111\n  retry_delay: 222\n"
        )
        (profiles_dir / f"{cl.get_active_profile().value}.yml").write_text("{}\n")
        monkeypatch.setattr(cl, "_REPO_ROOT", tmp_path)
        # Глобальные синглтоны не трогаем: в tmp-профиле нет их секций.
        monkeypatch.setattr(
            cl,
            "_iter_settings_singletons",
            lambda: iter(
                [
                    (
                        "src.backend.core.config.constants_settings",
                        "constants_settings",
                        constants_settings,
                    )
                ]
            ),
        )
        cl.clear_yaml_cache()

        report = cl.reload_settings(_ConstantsRoot(constants=ConstantsSettings()))

        assert report["failed"] == []
        assert consts.INITIAL_DELAY == 111
        assert consts.RETRY_DELAY == 222

    def test_reload_of_real_settings_keeps_constants(self) -> None:
        """``Settings.reload()`` переприменяет константы из реального профиля."""
        from src.backend.core.config.settings import settings

        report = settings.reload()

        assert report["failed"] == []
        assert consts.INITIAL_DELAY == _base_section()["initial_delay"]
        assert consts.DEFAULT_RETRY_MAX_ATTEMPTS == _base_section()[
            "default_retry_max_attempts"
        ]

    def test_module_singleton_is_reloaded(self) -> None:
        """Модульный синглтон констант участвует в hot-reload."""
        from src.backend.core.config.settings import settings

        settings.reload()
        assert constants_settings.initial_delay == _base_section()["initial_delay"]
