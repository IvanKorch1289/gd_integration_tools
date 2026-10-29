"""ЧАСТЬ A — полнота покрытия yaml-групп секциями ``config_profiles/base.yml``.

Мотивация (ADR-0375): 30 из 69 yaml-групп не имели секции в ``base.yml``.
Часть из них — secret-only (только креденшелы), часть — функциональные
параметры, которые было невозможно настроить без правки кода.

Контракт, который фиксирует этот модуль:

* для КАЖДОЙ yaml-группы есть секция в ``base.yml`` **или** группа явно
  перечислена в ``yaml_group_allowlist.txt`` с причиной исключения;
* новые секции содержат значения, РАВНЫЕ дефолтам моделей (поведение при
  загрузке не меняется — параметр просто становится конфигурируемым);
* в секциях ``base.yml`` нет секретных полей (секреты — только env/Vault).

Секции без полей модели и группы с per-profile значениями вынесены в
allowlist-файл: «allowlist = список невыполненной работы» здесь неверно —
это явная фиксация проектного решения.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from src.backend.core.config.ai import (
    AIWorkspaceSettings,
    GigaChatSettings,
    MarkitdownSettings,
    MiniMaxSettings,
    SaluteSpeechSettings,
    YandexGPTSettings,
)
from src.backend.core.config.ai_stack import (
    AIAgentSettings,
    BGESettings,
    LangFuseSettings,
    LangMemSettings,
    LiteLLMGatewaySettings,
    RagCacheSettings,
    RagIngestSettings,
    StreamingLLMSettings,
)
from src.backend.core.config.influxdb import InfluxDBSettings
from src.backend.core.config.lineage import LineageSettings
from src.backend.core.config.plugin_loader import PluginLoaderSettings
from src.backend.core.config.rag import RAGSettings
from src.backend.core.config.services.dlq import DLQCleanupSettings
from src.backend.core.config.services.ldap import LdapSettings
from src.backend.core.config.services.llm import LLMSettings
from src.backend.core.config.services.outbox import OutboxSettings
from src.backend.core.config.services.policy import PolicySettings
from src.backend.core.config.services.sms import SMSSettings
from src.backend.core.config.services.websocket import WSSettings
from src.backend.core.config.waf import WafSettings
from tools import config_audit

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"
BASE_YML = PROFILES_DIR / "base.yml"
ALLOWLIST_FILE = Path(__file__).with_name("yaml_group_allowlist.txt")
# Тот же корень, что у tools/config_audit.py: yaml-модели есть и вне core/config
CONFIG_DIR = REPO_ROOT / "src" / "backend" / "core"

#: Группы, для которых значения YAML обязаны совпадать с дефолтами
#: моделей (подключение YAML не меняет поведение). ADR-0375 (ЧАСТЬ A) —
#: новые секции; ADR-0379 — ``rag`` (вложенная pydantic-модель
#: ``AdaptiveRAGSettings``, которую нужно разворачивать при сравнении).
YAML_GROUPS_MATCHING_DEFAULTS: tuple[str, ...] = (
    "ai_agent",
    "ai_workspace",
    "bge",
    "dlq",
    "gigachat",
    "influxdb",
    "langfuse",
    "langmem",
    "ldap",
    "lineage",
    "litellm_gateway",
    "llm",
    "markitdown",
    "minimax",
    "outbox",
    "policy",
    "rag",
    "rag_cache",
    "rag_ingest",
    "salute_speech",
    "sms",
    "streaming_llm",
    "v11",
    "waf",
    "websocket",
    "yandexgpt",
)

#: Реальные классы моделей для проверяемых групп.
GROUP_MODELS: dict[str, type[BaseSettings]] = {
    "ai_agent": AIAgentSettings,
    "ai_workspace": AIWorkspaceSettings,
    "bge": BGESettings,
    "dlq": DLQCleanupSettings,
    "gigachat": GigaChatSettings,
    "influxdb": InfluxDBSettings,
    "langfuse": LangFuseSettings,
    "langmem": LangMemSettings,
    "ldap": LdapSettings,
    "lineage": LineageSettings,
    "litellm_gateway": LiteLLMGatewaySettings,
    "llm": LLMSettings,
    "markitdown": MarkitdownSettings,
    "minimax": MiniMaxSettings,
    "outbox": OutboxSettings,
    "policy": PolicySettings,
    "rag": RAGSettings,
    "rag_cache": RagCacheSettings,
    "rag_ingest": RagIngestSettings,
    "salute_speech": SaluteSpeechSettings,
    "sms": SMSSettings,
    "streaming_llm": StreamingLLMSettings,
    "v11": PluginLoaderSettings,
    "waf": WafSettings,
    "websocket": WSSettings,
    "yandexgpt": YandexGPTSettings,
}


def _load_base() -> dict[str, Any]:
    """Читает ``config_profiles/base.yml``.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).
    """
    import yaml

    with open(BASE_YML) as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _read_allowlist() -> dict[str, str]:
    """Читает allowlist-файл групп без секции в ``base.yml``.

    Returns:
        Соответствие ``yaml_group -> причина``.
    """
    entries: dict[str, str] = {}
    for raw in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        group, _, reason = line.partition(":")
        entries[group.strip()] = reason.strip()
    return entries


def _all_yaml_groups() -> set[str]:
    """Все yaml-группы моделей конфигурации проекта.

    Returns:
        Множество значений ``yaml_group``.
    """
    registry = config_audit._parse_config_classes(CONFIG_DIR)
    classes = config_audit._settings_classes(registry)
    return set(classes)


def _normalize(value: Any) -> Any:
    """Приводит значение к сравнимому виду.

    Разворачивает вложенные pydantic-модели (``BaseModel``) в mapping'и:
    иначе секция с вложенной моделью (например ``rag.adaptive``) всегда
    «расходилась» с дефолтом — dict из YAML против экземпляра модели.

    Args:
        value: Исходное значение (дефолт модели или YAML).

    Returns:
        Нормализованное значение.
    """
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump())
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _model_defaults(model_cls: type[BaseSettings]) -> dict[str, Any]:
    """Дефолты модели БЕЗ env/YAML (чистые значения ``Field(default=...)``).

    Args:
        model_cls: Класс настроек.

    Returns:
        Соответствие ``field -> default``.
    """
    instance = model_cls.model_construct()
    defaults: dict[str, Any] = {}
    for name in model_cls.model_fields:
        try:
            defaults[name] = getattr(instance, name)
        except AttributeError:  # pragma: no cover — поле без дефолта
            continue
    return defaults


class TestYamlGroupCoverage:
    """Каждая yaml-группа покрыта секцией ``base.yml`` или allowlist'ом."""

    def test_every_group_has_section_or_allowlist_entry(self) -> None:
        """Ни одна yaml-группа не осталась «в тени» (без секции и без причины)."""
        base = _load_base()
        allowlist = _read_allowlist()
        uncovered = sorted(
            group
            for group in _all_yaml_groups()
            if group not in base and group not in allowlist
        )
        assert uncovered == [], (
            "yaml-группы без секции в base.yml и без записи в allowlist: "
            f"{uncovered}"
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        """В allowlist нет групп, у которых секция в ``base.yml`` уже есть."""
        base = _load_base()
        stale = sorted(group for group in _read_allowlist() if group in base)
        assert stale == [], f"allowlist содержит группы с секцией в base.yml: {stale}"

    def test_allowlist_entries_are_real_groups(self) -> None:
        """В allowlist нет несуществующих yaml-групп (опечатка = ложное покрытие)."""
        groups = _all_yaml_groups()
        unknown = sorted(group for group in _read_allowlist() if group not in groups)
        assert unknown == [], f"allowlist содержит неизвестные группы: {unknown}"

    def test_allowlist_entries_have_reason(self) -> None:
        """У каждой записи allowlist есть непустая причина."""
        empty = sorted(group for group, reason in _read_allowlist().items() if not reason)
        assert empty == [], f"allowlist-записи без причины: {empty}"

    def test_allowlist_is_not_empty(self) -> None:
        """Allowlist не пуст — иначе проверка покрытия вырождается в no-op."""
        assert _read_allowlist()


class TestNewSectionsMatchModelDefaults:
    """Новые секции ``base.yml`` равны дефолтам моделей (поведение не меняется)."""

    @pytest.mark.parametrize("group", YAML_GROUPS_MATCHING_DEFAULTS)
    def test_section_exists(self, group: str) -> None:
        """Секция группы присутствует в ``base.yml``."""
        assert group in _load_base(), f"в base.yml нет секции {group!r}"

    @pytest.mark.parametrize("group", YAML_GROUPS_MATCHING_DEFAULTS)
    def test_values_equal_model_defaults(self, group: str) -> None:
        """Значения YAML равны дефолтам модели (ничего не поменялось)."""
        model_cls = GROUP_MODELS[group]
        section = _load_base()[group]
        defaults = _model_defaults(model_cls)
        mismatches: dict[str, tuple[Any, Any]] = {}
        for key, value in section.items():
            if key not in defaults:
                mismatches[key] = (value, "<нет такого поля в модели>")
                continue
            if _normalize(value) != _normalize(defaults[key]):
                mismatches[key] = (value, defaults[key])
        assert mismatches == {}, f"{group}: значения YAML != дефолты модели: {mismatches}"

    @pytest.mark.parametrize("group", YAML_GROUPS_MATCHING_DEFAULTS)
    def test_section_keys_are_model_fields(self, group: str) -> None:
        """В секции нет ключей, отсутствующих в модели (иначе — orphan-ключ)."""
        model_cls = GROUP_MODELS[group]
        unknown = sorted(set(_load_base()[group]) - set(model_cls.model_fields))
        assert unknown == [], f"{group}: ключи вне модели: {unknown}"


class TestNoSecretsInBaseSections:
    """В секциях ``base.yml`` нет секретных полей (секреты — env/Vault)."""

    def test_new_sections_have_no_secret_fields(self) -> None:
        """Ни одна новая секция не содержит секретного поля модели."""
        base = _load_base()
        offenders: dict[str, list[str]] = {}
        for group in YAML_GROUPS_MATCHING_DEFAULTS:
            model_cls = GROUP_MODELS[group]
            secret_names = {
                name
                for name, field in model_cls.model_fields.items()
                if config_audit.is_secret_field(name, str(field.annotation))
            }
            found = sorted(secret_names & set(base[group]))
            if found:
                offenders[group] = found
        assert offenders == {}, f"секреты в base.yml: {offenders}"
