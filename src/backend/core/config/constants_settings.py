"""Константы runtime-кода как конфигурация (ADR-0375, wave 14 — ЧАСТЬ C).

Зачем
-----
``src.backend.core.config.constants.consts`` — синглтон с дефолтами
retry/circuit-breaker'а и интервальными задержками. До этой волны его
значения были только в коде: изменить их можно было только релизом.

Теперь те же значения доступны декларативно — секция ``constants`` в
``config_profiles/base.yml`` (ADR-0375). Механика:

1. ``ConstantsSettings`` — обычная модель конфигурации с
   ``yaml_group="constants"``; дефолты модели == текущие значения
   ``consts`` (поведение при загрузке НЕ меняется);
2. при создании экземпляра (в т.ч. при hot-reload) значения применяются к
   инстансу ``consts`` — потребители ``consts.X`` видят новое значение без
   правки вызовов;
3. hot-reload: ``Settings.reload()`` (ADR-0372) пересоздаёт модульный
   синглтон ``constants_settings`` → модель пересобирается → значения
   снова применяются к ``consts``.

Почему НЕ Consul
-----------------
Роль Consul в проекте — DSL-переменные (``core/dsl/variable_backend.py``)
и cert_store. Константы кода — не runtime-конфигурация сервиса, а
параметры кода: их место в YAML-профиле рядом с остальными настройками
(ADR-0375, раздел «Решения»).

Предел применимости
-------------------
Значения, схваченные в момент импорта модуля как default поля dataclass'а
(например ``BreakerConfig.failure_threshold = consts.DEFAULT_CB_FAILURE_THRESHOLD``),
перечитывают константу ОДИН раз — на импорте. Такие потребители увидят
новое значение только после перезапуска процесса; «горячими» остаются
потребители, читающие ``consts.X`` в момент вызова.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader
from src.backend.core.config.constants import Constants, consts

__all__ = (
    "FIELD_TO_CONSTANT",
    "ConstantsSettings",
    "apply_constants",
    "constants_settings",
)


def _code_default(constant_name: str) -> Any:
    """Значение по умолчанию константы из класса ``Constants``.

    Берётся из ``Constants.__dataclass_fields__``, а НЕ из экземпляра
    ``consts``: применённое YAML-значение мутирует инстанс, но не должно
    переписывать дефолты модели — иначе повторный импорт модуля
    зафиксировал бы уже применённое значение вместо исходного.

    Args:
        constant_name: Имя атрибута ``Constants`` (например ``INITIAL_DELAY``).

    Returns:
        Значение по умолчанию из dataclass-поля.

    """
    return Constants.__dataclass_fields__[constant_name].default


#: Соответствие «поле настроек → атрибут синглтона ``consts``».
#:
#: ADR-0379: в маппинге нет констант без потребителя (инертных ключей
#: конфигурации). ``DEFAULT_CB_FAST_FAILURE_THRESHOLD`` /
#: ``DEFAULT_CB_FAST_RECOVERY_SECONDS`` были объявлены в YAML, но их
#: никто не читал (fast-circuit-breaker'а в проекте нет) — они убраны
#: из конфигурации; кодовые дефолты остались в ``constants.py``.
FIELD_TO_CONSTANT: Final[dict[str, str]] = {
    "initial_delay": "INITIAL_DELAY",
    "retry_delay": "RETRY_DELAY",
    "max_result_attempts": "MAX_RESULT_ATTEMPTS",
    "default_cb_failure_threshold": "DEFAULT_CB_FAILURE_THRESHOLD",
    "default_cb_recovery_seconds": "DEFAULT_CB_RECOVERY_SECONDS",
    "default_retry_max_attempts": "DEFAULT_RETRY_MAX_ATTEMPTS",
    "default_retry_initial_backoff": "DEFAULT_RETRY_INITIAL_BACKOFF",
    "default_retry_max_backoff": "DEFAULT_RETRY_MAX_BACKOFF",
    "default_retry_backoff_multiplier": "DEFAULT_RETRY_BACKOFF_MULTIPLIER",
    "default_retry_jitter": "DEFAULT_RETRY_JITTER",
}


class ConstantsSettings(BaseSettingsWithLoader):
    """Настраиваемые константы runtime-кода (retry / circuit-breaker).

    Дефолты модели совпадают с текущими значениями ``consts`` — включение
    секции ``constants`` в YAML не меняет поведение, но позволяет
    переопределить параметры без правки кода.

    Секретов в группе нет (таймауты/пороги/интервалы — не креденшелы).
    """

    yaml_group: ClassVar[str] = "constants"
    model_config = SettingsConfigDict(
        env_prefix="CONSTANTS_", extra="forbid", validate_default=True
    )

    initial_delay: int = Field(
        default=_code_default("INITIAL_DELAY"),
        ge=0,
        description="Начальная задержка перед повторной попыткой (секунды).",
    )
    retry_delay: int = Field(
        default=_code_default("RETRY_DELAY"),
        ge=0,
        description="Задержка между повторными попытками (секунды).",
    )
    max_result_attempts: int = Field(
        default=_code_default("MAX_RESULT_ATTEMPTS"),
        ge=1,
        description="Максимальное количество попыток получения результата.",
    )
    default_cb_failure_threshold: int = Field(
        default=_code_default("DEFAULT_CB_FAILURE_THRESHOLD"),
        ge=1,
        description="Порог отказа circuit-breaker'а (число подряд идущих ошибок).",
    )
    default_cb_recovery_seconds: float = Field(
        default=_code_default("DEFAULT_CB_RECOVERY_SECONDS"),
        gt=0.0,
        description="Таймаут восстановления circuit-breaker'а (секунды).",
    )
    default_retry_max_attempts: int = Field(
        default=_code_default("DEFAULT_RETRY_MAX_ATTEMPTS"),
        ge=1,
        description="Максимум попыток retry по умолчанию.",
    )
    default_retry_initial_backoff: float = Field(
        default=_code_default("DEFAULT_RETRY_INITIAL_BACKOFF"),
        gt=0.0,
        description="Начальный backoff retry по умолчанию (секунды).",
    )
    default_retry_max_backoff: float = Field(
        default=_code_default("DEFAULT_RETRY_MAX_BACKOFF"),
        gt=0.0,
        description="Потолок backoff retry по умолчанию (секунды).",
    )
    default_retry_backoff_multiplier: float = Field(
        default=_code_default("DEFAULT_RETRY_BACKOFF_MULTIPLIER"),
        gt=0.0,
        description="Множитель backoff retry по умолчанию.",
    )
    default_retry_jitter: float = Field(
        default=_code_default("DEFAULT_RETRY_JITTER"),
        ge=0.0,
        description="Доля джиттера в backoff retry по умолчанию.",
    )

    def model_post_init(self, context: Any) -> None:
        """Применяет значения к синглтону ``consts`` (ADR-0375).

        Вызывается pydantic'ом при каждом создании модели — в том числе
        при hot-reload, когда ``Settings.reload()`` пересоздаёт модульный
        синглтон ``constants_settings``.

        Args:
            context: Контекст валидации pydantic (не используется).

        Returns:
            None.

        """
        apply_constants(self)


def apply_constants(settings: ConstantsSettings | None = None) -> None:
    """Переносит значения настроек в синглтон ``consts``.

    Мутация инстанса (а не подмена объекта) — потребители держат ссылку
    на ``consts`` и видят новое значение без правки вызовов.

    Args:
        settings: Источник значений. По умолчанию — модульный синглтон
            ``constants_settings``.

    Returns:
        None.

    """
    source = constants_settings if settings is None else settings
    for field_name, constant_name in FIELD_TO_CONSTANT.items():
        setattr(consts, constant_name, getattr(source, field_name))


constants_settings: ConstantsSettings = ConstantsSettings()
"""Глобальный экземпляр настроек констант (пересоздаётся при hot-reload)."""
