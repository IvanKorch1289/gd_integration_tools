"""W14.2 — единый контракт для batch- и stream-обработки.

:class:`DataKind` маркирует форму данных в ``Message``:

* ``SINGLE`` — одиночное событие (default — обратная совместимость).
* ``BATCH`` — конечный список (накоплен оконным процессором или CDC-pull).
* ``STREAM`` — асинхронный поток (continuous).

Поле ``Message.data_kind`` всегда ``SINGLE`` по умолчанию — существующие
DSL-маршруты не меняют поведение. Процессоры, осознанно работающие
с batch/stream, читают это поле и реализуют :class:`BatchCapable`
из ``src.core.interfaces.batch_capable``.
"""

from __future__ import annotations

from enum import Enum

__all__ = ("DataKind",)


class DataKind(str, Enum):
    """Форма payload'а ``Message``.

    Наследуется от ``str`` для прозрачной YAML/JSON-сериализации
    (``DataKind.SINGLE.value == "single"``).
    """

    SINGLE = "single"
    BATCH = "batch"
    STREAM = "stream"
