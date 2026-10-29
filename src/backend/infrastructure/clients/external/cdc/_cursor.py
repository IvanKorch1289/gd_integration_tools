"""ADR-0384 — составной курсор CDC ``(timestamp, PK)`` + UTC-нормализация.

Курсор polling-CDC должен переживать границу батча. Курсор ``max(ts)``
с условием ``ts > :last`` теряет строки, у которых timestamp совпадает с
последней строкой батча (ADR-0384). Каноничный курсор — пара
``(timestamp, PK)``:

* условие выборки — ``ts >= :last_ts AND (ts > :last_ts OR pk > :last_pk)``;
* порядок — ``ORDER BY ts, pk`` (детерминированный);
* хранение — строка ``"<ts>|<pk>"``, лексикографический порядок строки
  совпадает с хронологическим (timestamp фиксированной ширины, PK —
  типизированный префикс).

Модуль также решает проблему PG ``timestamp without time zone``: значения
из БД приводятся к UTC-aware **до** сравнения (иначе ``TypeError:
can't compare offset-naive and offset-aware datetimes``), а в SQL
подставляется naive-UTC представление (значение, как оно лежит в колонке).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.backend.core.utils.datetime_utils import ensure_utc

__all__ = (
    "PollCursor",
    "decode_cursor",
    "encode_cursor",
    "ensure_utc",
    "row_fingerprint",
    "to_db_timestamp",
)

#: Фиксированный формат timestamp в курсоре — лексикографический порядок
#: строк совпадает с хронологическим.
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

#: Максимум строк в dedup-окне (без PK курсор ts-only, нужна дедупликация).
_MAX_SEEN = 10_000


@dataclass(frozen=True)
class PollCursor:
    """Водяной знак polling-CDC: timestamp + опциональный primary key.

    Attributes:
        ts: Момент времени последней обработанной строки (UTC-aware).
        pk: Значение PK последней обработанной строки (``None`` — режим
            ts-only, когда PK определить не удалось).

    """

    ts: datetime
    pk: Any | None = None


def to_db_timestamp(value: datetime) -> datetime:
    """Привести datetime к naive-UTC для bind-параметра SQL.

    Args:
        value: Исходный datetime (naive или aware).

    Returns:
        datetime без tzinfo, содержащий ту же точку времени в UTC.

    """
    return ensure_utc(value).replace(tzinfo=None)


def encode_pk(value: Any) -> str:
    """Закодировать значение PK в лексикографически сортируемую строку.

    Args:
        value: Значение PK (``None`` → пустая строка).

    Returns:
        Строка с типизированным префиксом (``i:``/``s:``/``b:``), чтобы
        разные типы не сравнивались друг с другом.

    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return f"b:{int(value):d}"
    if isinstance(value, int):
        return f"i:{value:020d}"
    if isinstance(value, str):
        return f"s:{len(value)}:{value}"
    return ""


def decode_pk(raw: str) -> Any | None:
    """Декодировать значение PK из курсора.

    Args:
        raw: Строка, полученная из :func:`encode_pk`.

    Returns:
        Исходное значение PK либо ``None``, если значение не поддерживается
        (тогда курсор деградирует до ts-only).

    """
    if not raw:
        return None
    prefix, _, rest = raw.partition(":")
    if prefix == "i":
        try:
            return int(rest)
        except ValueError:
            return None
    if prefix == "b":
        return rest == "1"
    if prefix == "s":
        _, _, value = rest.partition(":")
        return value
    return None


def encode_cursor(ts: datetime, pk: Any | None = None) -> str:
    """Закодировать курсор ``(timestamp, PK)`` в строку.

    Args:
        ts: Timestamp (naive трактуется как UTC).
        pk: Значение PK (опционально).

    Returns:
        Строка ``"<ts>|<pk>"`` — монотонная в лексикографическом порядке.

    """
    ts_part = ensure_utc(ts).strftime(_TS_FORMAT)
    return f"{ts_part}|{encode_pk(pk)}"


def decode_cursor(raw: str) -> PollCursor:
    """Декодировать курсор из строки.

    Args:
        raw: Строка, созданная :func:`encode_cursor`.

    Returns:
        :class:`PollCursor` с timestamp (UTC-aware) и PK.

    Raises:
        ValueError: Если строка не является валидным курсором.

    """
    ts_part, _, pk_part = raw.partition("|")
    try:
        ts = datetime.strptime(ts_part, _TS_FORMAT).replace(tzinfo=None)
    except ValueError:
        # Legacy-курсор (ISO-строка без PK) — поддерживается, чтобы
        # обновление не сбрасывало позицию polling'а на «now».
        try:
            ts = datetime.fromisoformat(ts_part)
        except ValueError as exc:
            raise ValueError(f"Invalid CDC cursor: {raw!r}") from exc
        return PollCursor(ts=ensure_utc(ts), pk=None)
    return PollCursor(ts=ensure_utc(ts), pk=decode_pk(pk_part))


def row_fingerprint(row: dict[str, Any]) -> str:
    """Стабильный отпечаток строки — dedup-ключ, когда PK неизвестен.

    Args:
        row: Строка выборки.

    Returns:
        SHA-256 от канонического JSON-представления строки.

    """
    import hashlib

    import orjson

    payload = orjson.dumps(row, default=str, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(payload).hexdigest()


class SeenKeys:
    """Bounded- множество уже обработанных ключей (FIFO-вытеснение).

    Используется в ts-only режиме polling: строки с timestamp == курсор
    перечитываются (условие ``>=``), поэтому дубли нужно отсекать.

    Attributes:
        _keys: OrderedDict-подобное хранилище ключей.

    """

    __slots__ = ("_keys", "_max_size")

    def __init__(self, max_size: int = _MAX_SEEN) -> None:
        """Параметры:

        :param max_size: Максимальный размер окна дедупликации.
        """
        self._keys: dict[str, None] = {}
        self._max_size = max_size

    def add(self, key: str) -> bool:
        """Добавить ключ.

        Args:
            key: Ключ строки.

        Returns:
            ``True`` — ключ был новым, ``False`` — уже обработан.

        """
        if key in self._keys:
            return False
        self._keys[key] = None
        while len(self._keys) > self._max_size:
            self._keys.pop(next(iter(self._keys)))
        return True

    def __len__(self) -> int:
        """Число ключей в окне."""
        return len(self._keys)
