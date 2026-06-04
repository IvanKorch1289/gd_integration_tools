"""msgspec hotpath для (де)сериализации Exchange-объектов.

S39 W2: выделенный fast-path для dict ↔ typed object. msgspec даёт ~2-6x
ускорение против orjson на dataclass/msgspec.Struct за счёт zero-copy encode
и compiled C-extension decode. При недоступности msgspec — graceful fallback
на orjson (encode) и ``cls(**data)`` (decode).

Границы:
  * один модуль, две публичные функции (``to_dict_fast``, ``from_dict_fast``);
  * НЕ глобальная миграция — точечная замена существующих сериализаторов
    остаётся вне scope (см. PLAN.md S39 W2);
  * Все typed-объекты (msgspec.Struct, dataclass, pydantic v1/v2) идут через
    единый duck-typed ``_to_dict_safe``, который пробует msgspec первым и
    валится на orjson с robust ``default=``-callback для случаев, которые
    msgspec не покрывает (pydantic).
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, TypeVar

import orjson

try:
    import msgspec as _msgspec
    _HAS_MSGSPEC = True
except ImportError:  # pragma: no cover — degraded mode без msgspec
    _msgspec = None  # type: ignore[assignment]
    _HAS_MSGSPEC = False


T = TypeVar("T")

__all__ = ("to_dict_fast", "from_dict_fast")


# ---------------------------------------------------------------------------
# Internal: type-erased encoders
# ---------------------------------------------------------------------------


def _iso(obj: Any) -> str:
    """datetime/date/time → ISO 8601 string."""
    return obj.isoformat()


def _msgspec_enc_hook(obj: Any) -> Any:
    """enc_hook для msgspec.to_builtins: datetime-семейство + raise иначе."""
    if isinstance(obj, (datetime, date, time)):
        return _iso(obj)
    raise NotImplementedError(
        f"Type {type(obj).__name__!s} is not JSON serialisable"
    )


def _orjson_default(obj: Any) -> Any:
    """default-callback для orjson: duck-typed pydantic / msgspec.Struct / dataclass.

    msgspec уже покрывает msgspec.Struct / dataclass на первом проходе, так
    что сюда они обычно не доходят — это страховка для режима ``use_msgspec=False``
    и для pydantic-моделей, которые msgspec нативно не знает.
    """
    # pydantic v2
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    # pydantic v1
    dict_method = getattr(obj, "dict", None)
    if callable(dict_method):
        return dict_method()
    # datetime-семейство
    if isinstance(obj, (datetime, date, time)):
        return _iso(obj)
    # msgspec.Struct / dataclass — рекурсивно через msgspec (если он есть).
    if _msgspec is not None:
        try:
            return _msgspec.to_builtins(obj, enc_hook=_msgspec_enc_hook)
        except Exception:
            pass
    # msgspec.Struct в режиме без msgspec: у него есть ``__struct_fields__``.
    # Иначе — dataclass.asdict.
    struct_fields = getattr(obj, "__struct_fields__", None)
    if struct_fields is not None:
        return {f: getattr(obj, f) for f in struct_fields}
    import dataclasses as _dc
    if _dc.is_dataclass(obj):
        return _dc.asdict(obj)  # type: ignore[arg-type]
    raise TypeError(f"Type {type(obj).__name__!s} is not JSON serialisable")


def _encode_msgspec(obj: Any) -> Any:
    """msgspec-путь. Бросает исключение, если тип не поддерживается."""
    assert _msgspec is not None  # noqa: S101 — guarded by caller
    return _msgspec.to_builtins(obj, enc_hook=_msgspec_enc_hook)


def _encode_orjson(obj: Any) -> Any:
    """orjson-путь. Поддерживает pydantic через _orjson_default."""
    return orjson.loads(orjson.dumps(obj, default=_orjson_default))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_dict_fast(obj: Any, *, use_msgspec: bool = True) -> dict[str, Any]:
    """Object → dict. msgspec первым; на любой ошибке → orjson.

    Args:
        obj: ``msgspec.Struct`` / ``@dataclass`` / pydantic-модель / dict /
            list / примитив. Поддерживается всё, что сериализуемо msgspec
            или orjson + duck-typed pydantic fallback.
        use_msgspec: ``True`` — пробовать msgspec; ``False`` — сразу orjson
            (полезно в тестах для принудительного fallback и для замера
            чистого orjson-time).

    Returns:
        ``dict[str, Any]`` с примитивными значениями.

    Raises:
        TypeError: если ``obj`` не сериализуем ни одним из бэкендов.
    """
    if use_msgspec and _HAS_MSGSPEC and _msgspec is not None:
        try:
            return _encode_msgspec(obj)
        except Exception:
            # Тип не поддерживается msgspec (pydantic / exotic) — fallback.
            pass
    return _encode_orjson(obj)


def from_dict_fast(cls: type[T], data: dict[str, Any]) -> T:
    """dict → typed object. msgspec.convert первым; fallback ``cls(**data)``.

    Args:
        cls: Целевой тип. Поддерживает ``msgspec.Struct``, ``@dataclass``,
            pydantic v1/v2 (через ``__init__(**data)``).
        data: Словарь с примитивными значениями.

    Returns:
        Экземпляр ``cls``, заполненный из ``data``.
    """
    if _HAS_MSGSPEC and _msgspec is not None:
        try:
            return _msgspec.convert(data, cls)
        except Exception:
            # cls не поддерживается msgspec.convert (pydantic и пр.) — fallback.
            pass
    return cls(**data)
