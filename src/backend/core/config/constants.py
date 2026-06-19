from asyncio import TimeoutError
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

# Wave 0.4.6: aiohttp → httpx. Legacy http.py может ещё импортировать
# aiohttp до полного удаления в H3. RETRY_EXCEPTIONS использует только
# httpx, что покрывает все non-deprecated клиенты проекта.
import httpx

# S168 W10 P1-14: per-domain extraction. CB + retry defaults
# re-exported from _resilience_consts.py для backward-compat.
from src.backend.core.config._resilience_consts import (
    DEFAULT_CB_FAST_FAILURE_THRESHOLD,
    DEFAULT_CB_FAST_RECOVERY_SECONDS,
    DEFAULT_CB_FAILURE_THRESHOLD,
    DEFAULT_CB_RECOVERY_SECONDS,
    DEFAULT_RETRY_BACKOFF_MULTIPLIER,
    DEFAULT_RETRY_INITIAL_BACKOFF,
    DEFAULT_RETRY_JITTER,
    DEFAULT_RETRY_MAX_ATTEMPTS,
)

__all__ = (
    "Constants",
    "consts",
    # Re-exports для backward-compat
    "DEFAULT_CB_FAILURE_THRESHOLD",
    "DEFAULT_CB_RECOVERY_SECONDS",
    "DEFAULT_CB_FAST_FAILURE_THRESHOLD",
    "DEFAULT_CB_FAST_RECOVERY_SECONDS",
    "DEFAULT_RETRY_MAX_ATTEMPTS",
    "DEFAULT_RETRY_INITIAL_BACKOFF",
    "DEFAULT_RETRY_BACKOFF_MULTIPLIER",
    "DEFAULT_RETRY_JITTER",
)


@dataclass
class Constants:
    """
    Класс для хранения констант.

    Атрибуты:
        ROOT_DIR (Path): Корневая директория проекта.
        MOSCOW_TZ (timezone): Временная зона для Москвы (UTC+3).
        RETRY_EXCEPTIONS (Tuple): Исключения, при которых следует повторять запросы.
        CHECK_SERVICES_JOB (Dict[str, Any]): Настройки задачи проверки сервисов.
        INITIAL_DELAY (int): Начальная задержка перед повторной попыткой (в секундах).
        RETRY_DELAY (int): Задержка между повторными попытками (в секундах).
        MAX_RESULT_ATTEMPTS (int): Максимальное количество попыток получения результата.
        RETRIABLE_DB_CODES (Set[str]): Коды ошибок PostgreSQL, при которых следует повторять операцию.

    S168 W10 P1-14: CB + retry defaults вынесены в
    ``_resilience_consts.py`` (per-domain extraction). Здесь
    re-exported через атрибуты dataclass для backward-compat.
    """

    ROOT_DIR: Path = Path(__file__).parent.parent.parent
    MOSCOW_TZ: timezone = timezone(timedelta(hours=3))
    RETRY_EXCEPTIONS: tuple[Any, ...] = (httpx.HTTPError, TimeoutError)
    CHECK_SERVICES_JOB: dict[str, Any] = field(
        default_factory=lambda: {"name": "check_all_services_job", "minutes": 60}
    )
    INITIAL_DELAY: int = 3600  # 60 минут
    RETRY_DELAY: int = 1800  # 30 минут
    MAX_RESULT_ATTEMPTS: int = 4

    # S168 W10 P1-14: CB + retry defaults вынесены в _resilience_consts.py
    # (per-domain extraction). Здесь re-exported через атрибуты dataclass
    # для backward-compat (callers consts.DEFAULT_CB_FAILURE_THRESHOLD).
    DEFAULT_CB_FAILURE_THRESHOLD: int = DEFAULT_CB_FAILURE_THRESHOLD
    DEFAULT_CB_RECOVERY_SECONDS: float = DEFAULT_CB_RECOVERY_SECONDS
    DEFAULT_CB_FAST_FAILURE_THRESHOLD: int = DEFAULT_CB_FAST_FAILURE_THRESHOLD
    DEFAULT_CB_FAST_RECOVERY_SECONDS: float = DEFAULT_CB_FAST_RECOVERY_SECONDS
    DEFAULT_RETRY_MAX_ATTEMPTS: int = DEFAULT_RETRY_MAX_ATTEMPTS
    DEFAULT_RETRY_INITIAL_BACKOFF: float = DEFAULT_RETRY_INITIAL_BACKOFF
    DEFAULT_RETRY_BACKOFF_MULTIPLIER: float = DEFAULT_RETRY_BACKOFF_MULTIPLIER
    DEFAULT_RETRY_JITTER: float = DEFAULT_RETRY_JITTER

    # DB-related: per master prompt P1-14, RETRIABLE_DB_CODES остаётся
    # здесь (DB-domain extraction — separate WIP для минимизации
    # blast radius).
    RETRIABLE_DB_CODES: set[str] = field(
        default_factory=lambda: {
            # Ошибки, связанные с подключением
            "08000",
            "08003",
            "08006",
            "08001",
            "08004",
            "08007",
            # Конфликты транзакций
            "40001",
            "40P01",
            # Ограничения ресурсов
            "55006",
            "55P03",
            "53300",
            # Системные ошибки
            "57P01",
            "57P02",
            "57P03",
            # Прочие ошибки
            "58000",
        }
    )


# Экземпляр конфигурации
consts = Constants()
