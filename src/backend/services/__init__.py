"""S66 W3: PEP 420 namespace package для ``src.backend.services``.

Подпакеты импортируются явно (``from src.backend.services import ai``)
— этот файл НЕ определяет public API уровня ``services``. ``__all__``
намеренно отсутствует: namespace-пакеты по PEP 420 не должны экспортировать
symbols на уровне корня (см. https://peps.python.org/pep-0420/).
"""
