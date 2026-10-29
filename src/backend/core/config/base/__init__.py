"""Config base classes (S65 W3 decomp from base.py 485 LOC).

2 classes → 2 files (per-class file split):
- app_base.py: AppBaseSettings
- scheduler.py: SchedulerSettings

Backward-compat: from src.backend.core.config.base import AppBaseSettings works.
"""

from __future__ import annotations

from src.backend.core.config.base.app_base import (
    AppBaseSettings,  # S65 W3: re-export as AppBaseSettings  # S65 W3: re-export
)
from src.backend.core.config.base.scheduler import (
    SchedulerSettings,  # S65 W3: re-export
)

# ADR-0375: константы runtime-кода как конфигурация. Импорт здесь (а не в
# ``core/config/__init__.py``) — потому что ``core/config/__init__.py``
# выполняется до инициализации ``core.logging``, а создание настроек в этот
# момент тянет логирование (циклический импорт). Здесь уже создаются
# ``app_base_settings``/``scheduler_settings`` — тот же профиль риска.
# Модуль обязан быть в ``sys.modules``: ``Settings.reload()`` пересобирает
# модульные синглтоны только импортированных модулей пакета — так
# hot-reload обновляет значения констант (ADR-0375, ЧАСТЬ C).
from src.backend.core.config.constants_settings import (  # noqa: F401
    ConstantsSettings,
    constants_settings,
)

#: ``__all__`` не расширяется хелпером ``mask_url_password`` — ratchet-тест
#: экспортов facade'а (``tests/unit/core/config/base/test_init.py``) фиксирует
#: ровно 2 символа. Явный импорт ``from ... import mask_url_password`` работает
#: независимо от ``__all__``.
__all__ = ("AppBaseSettings", "SchedulerSettings")


def mask_url_password(url: str) -> str:
    """Маскирует пароль в URL/DSN: ``redis://:pass@host`` → ``redis://:***@host``.

    Используется для логов и ``model_dump()`` — рабочее значение DSN
    (для подключения к БД/Redis) остаётся в атрибуте модели.

    Args:
        url: URL/DSN с возможным паролем в userinfo-части.

    Returns:
        Тот же URL с замаскированным паролем; если пароля нет — исходная
        строка без изменений.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    authority, slash, tail = rest.partition("/")
    userinfo, at, host = authority.rpartition("@")
    if not at:
        return url
    user, colon, _password = userinfo.partition(":")
    if not colon:
        return url
    return f"{scheme}://{user}:***@{host}{slash}{tail}"


app_base_settings: AppBaseSettings = AppBaseSettings()

scheduler_settings: SchedulerSettings = (
    SchedulerSettings()
)  # S65 W3 fixup: missing instance
