"""Единая точка импорта опционального драйвера ``clickhouse_connect``.

Wave 13 Q8: пакет ``clickhouse_connect`` использовался в 6 местах ``src/``,
но не был объявлен ни в ``[project].dependencies``, ни в одном extra — только
как mypy-override. 4 из 6 мест импортировали его без fallback'а
(``ModuleNotFoundError`` при первом обращении), ещё 2 — молча деградировали
через широкий ``except Exception``.

Модуль закрывает класс дефекта «висячая зависимость» (импорт есть —
объявления нет), а не только симптом:

* ``required=True`` (по умолчанию) → :class:`ClickHouseDriverError` с
  указанием пакета и extra, в котором он должен быть объявлен. Fail-loud
  для путей записи (audit-события, saga/HITL-история, оценка стоимости):
  молчаливая потеря данных хуже явной ошибки;
* ``required=False`` → ``None`` + WARNING в лог. Деградация для путей
  чтения UI (дашборд cron, админ-клиент).

Импорт пакета и чтение параметров подключения собраны в одном месте, чтобы
6 потребителей не разъезжались по настройкам.

Слой: ``infrastructure`` — используется и из ``infrastructure``, и из
``services`` (правило ``services → infrastructure`` разрешено в
``tools/check_layers.py``).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger

__all__ = (
    "CLICKHOUSE_DRIVER_EXTRA",
    "CLICKHOUSE_DRIVER_PACKAGE",
    "ClickHouseDriverError",
    "create_clickhouse_async_client",
    "import_clickhouse_driver",
)

_logger = get_logger(__name__)

#: Имя пакета в PyPI (совпадает с именем импортируемого модуля).
CLICKHOUSE_DRIVER_PACKAGE = "clickhouse_connect"

#: Extra, в котором драйвер должен быть объявлен (вместе с прочими
#: DB-драйверами: oracledb / aioodbc / aiomysql).
CLICKHOUSE_DRIVER_EXTRA = "db_drivers"


class ClickHouseDriverError(ServiceError):
    """Драйвер ``clickhouse_connect`` недоступен в окружении.

    Доменное исключение вместо ``ModuleNotFoundError``: сообщает, какой
    пакет отсутствует и в каком extra он должен быть объявлен.

    Attributes:
        package: Имя отсутствующего пакета.
        extra: Extra, в котором пакет должен быть объявлен.

    """

    def __init__(
        self,
        package: str = CLICKHOUSE_DRIVER_PACKAGE,
        extra: str = CLICKHOUSE_DRIVER_EXTRA,
    ) -> None:
        self.package = package
        self.extra = extra
        super().__init__(
            f"Пакет '{package}' не установлен в окружении. Объявите его в extra "
            f"'{extra}' и установите: uv sync --extra {extra} "
            f"(или pip install 'gd_advanced_tools[{extra}]')."
        )


def import_clickhouse_driver(*, required: bool = True) -> Any | None:
    """Импортирует модуль ``clickhouse_connect``.

    Args:
        required: ``True`` (по умолчанию) — отсутствие пакета считается
            ошибкой конфигурации: поднимается :class:`ClickHouseDriverError`.
            ``False`` — деградация: возвращается ``None`` и пишется WARNING.

    Returns:
        Модуль ``clickhouse_connect`` либо ``None`` (только при
        ``required=False`` и отсутствии пакета).

    Raises:
        ClickHouseDriverError: пакет не установлен, ``required=True``.

    """
    try:
        import clickhouse_connect
    except ImportError as exc:
        if required:
            raise ClickHouseDriverError() from exc
        _logger.warning(
            "Пакет '%s' не установлен — ClickHouse-интеграция недоступна "
            "(ожидается extra '%s')",
            CLICKHOUSE_DRIVER_PACKAGE,
            CLICKHOUSE_DRIVER_EXTRA,
        )
        return None
    return clickhouse_connect


async def create_clickhouse_async_client(*, required: bool = True) -> Any | None:
    """Создаёт async-клиент ClickHouse через ``clickhouse_connect``.

    Args:
        required: Семантика отсутствия драйвера — см.
            :func:`import_clickhouse_driver`.

    Returns:
        Async-клиент ClickHouse либо ``None`` (только при ``required=False``
        и отсутствии пакета).

    Raises:
        ClickHouseDriverError: драйвер не установлен, ``required=True``.

    """
    driver = import_clickhouse_driver(required=required)
    if driver is None:
        return None

    from src.backend.core.config import settings

    host = (
        getattr(settings.clickhouse, "host", "localhost")
        if hasattr(settings, "clickhouse")
        else "localhost"
    )
    port = (
        getattr(settings.clickhouse, "port", 8123)
        if hasattr(settings, "clickhouse")
        else 8123
    )
    database = (
        getattr(settings.clickhouse, "database", "default")
        if hasattr(settings, "clickhouse")
        else "default"
    )
    return await driver.get_async_client(host=host, port=port, database=database)
