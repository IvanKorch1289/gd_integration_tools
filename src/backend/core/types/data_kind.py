"""W14.2 — единый контракт для batch- и stream-обработки.

:class:`DataKind` маркирует форму данных в ``Message``:

* ``SINGLE`` — одиночное событие (default — обратная совместимость).
* ``BATCH`` — конечный список (накоплен оконным процессором или CDC-pull).
* ``STREAM`` — асинхронный поток (continuous).

Поле ``Message.data_kind`` всегда ``SINGLE`` по умолчанию — существующие
DSL-маршруты не меняют поведение. Процессоры, осознанно работающие
с batch/stream, читают это поле и оптимизируют свой ``process``
соответственно (через собственный typeguard или явную проверку
``exchange.in_message.data_kind``).
"""

from __future__ import annotations

from enum import Enum, StrEnum

__all__ = ("DataKind",)


class DataKind(StrEnum):
    """Форма payload'а ``Message``.

    Наследуется от ``str`` для прозрачной YAML/JSON-сериализации
    (``DataKind.SINGLE.value == "single"``).
    """

    SINGLE = "single"
    BATCH = "batch"
    STREAM = "stream"
